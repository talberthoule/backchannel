"""Request limits sized for self-hosted models (ALP-154).

A briefing against a local 4B model failed two ways at once: the meeting lens
exceeded the 120 s request timeout, and the arbiter's JSON was cut off mid
structure by the server's own output default, surfacing as a bare json decode
error rather than anything the user could act on.
"""

import unittest
from unittest import mock

import httpx

from app.config import settings
from app.services import llm
from app.services.llm import LLMReplyTruncated
from app.services.llm_endpoint import OpenAIEndpoint
from tests.test_briefing_provider_routing import FakeHTTPX, _chat_response
from app.services.briefing_synthesis import BriefLensOutput

SELF_HOSTED = "endpoint:lm-studio:qwen3.5-4b"
HOSTED = "gpt-5.5"


class RequestLimitTests(unittest.TestCase):
    def test_a_self_hosted_model_gets_the_longer_timeout(self):
        self.assertEqual(
            settings.LLM_SELF_HOSTED_TIMEOUT_SECONDS, llm._request_timeout(SELF_HOSTED)
        )

    def test_a_hosted_model_keeps_the_short_timeout(self):
        self.assertEqual(settings.LLM_TIMEOUT_SECONDS, llm._request_timeout(HOSTED))
        # A stuck cloud call must still fail reasonably fast.
        self.assertLess(
            llm._request_timeout(HOSTED), llm._request_timeout(SELF_HOSTED)
        )

    def test_the_local_timeout_actually_covers_a_slow_briefing(self):
        # The observed failure was a ReadTimeout at 120 s on one lens.
        self.assertGreaterEqual(llm._request_timeout(SELF_HOSTED), 600)

    def test_every_request_carries_an_output_budget(self):
        local = llm._apply_output_budget({}, SELF_HOSTED)
        self.assertEqual(settings.LLM_SELF_HOSTED_MAX_TOKENS, local["max_tokens"])
        hosted = llm._apply_output_budget({}, HOSTED)
        self.assertEqual(
            settings.LLM_HOSTED_MAX_TOKENS, hosted["max_completion_tokens"]
        )

    def test_the_two_shapes_use_the_field_name_each_one_accepts(self):
        """OpenAI renamed this and rejects the old name outright.

        Observed against a live model: "Unsupported parameter: 'max_tokens' is
        not supported with this model. Use 'max_completion_tokens' instead."
        Every agent call 400'd. Self-hosted OpenAI-compatible servers only know
        max_tokens, so the two paths cannot share one field name.

        This was unreachable until hosted providers started getting a budget at
        all - before that the hosted branch returned early (ALP-295).
        """
        hosted = llm._apply_output_budget({}, HOSTED)
        self.assertIn("max_completion_tokens", hosted)
        self.assertNotIn("max_tokens", hosted)

        local = llm._apply_output_budget({}, SELF_HOSTED)
        self.assertIn("max_tokens", local)
        self.assertNotIn("max_completion_tokens", local)

    def test_a_renamed_parameter_refusal_is_recoverable(self):
        # Whatever the field is called next, a request refused purely over a
        # field name should drop the optional fields rather than fail a cycle.
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        exc = httpx.HTTPStatusError(
            "bad request",
            request=request,
            response=httpx.Response(
                400,
                request=request,
                json={
                    "error": {
                        "message": (
                            "Unsupported parameter: 'max_tokens' is not supported "
                            "with this model. Use 'max_completion_tokens' instead."
                        ),
                        "code": "unsupported_parameter",
                    }
                },
            ),
        )
        self.assertTrue(llm._rejects_generation_limits(exc))

    def test_a_hosted_model_is_not_left_uncapped(self):
        """This assertion used to say the opposite, and that was the bug.

        Leaving hosted providers uncapped was deliberate - their defaults were
        assumed generous enough that a cap "could only make them worse". What it
        actually did was set the price of failure. On one measured session five
        synthesizer calls emitted 47k-63k output tokens each, 22 percent of the
        entire session bill, and every one was discarded unparsed and retried.
        The cap does not rescue those calls, it stops them costing sixteen times
        what they need to before failing (ALP-295).
        """
        # Field name per shape is pinned separately below; here the point is
        # only that some ceiling is sent at all.
        hosted = llm._apply_output_budget({}, HOSTED)
        self.assertTrue({"max_tokens", "max_completion_tokens"} & set(hosted))

    def test_the_hosted_budget_clears_the_widest_legitimate_reply(self):
        """Sized to the briefing contract, not to the synthesizer.

        A first attempt used 4096, derived from the synthesizer's healthy
        median output of 300 tokens. That is one agent's profile: in a replay
        two briefing calls landed on exactly 4096, which is the ceiling rather
        than a coincidence. On OpenAI the budget also counts reasoning tokens,
        so a reasoning model can spend most of it before emitting anything
        visible. The saving never depended on sitting close to normal output -
        8192 still bounds the observed 63k runaway by nearly eight times.
        """
        self.assertGreaterEqual(
            settings.LLM_HOSTED_MAX_TOKENS, settings.LLM_SELF_HOSTED_MAX_TOKENS
        )
        # Still far below what a degenerate reply reached uncapped.
        self.assertLess(settings.LLM_HOSTED_MAX_TOKENS, 47_000)

    def test_the_budget_is_large_enough_for_the_briefing_contract(self):
        # The arbiter reply died at ~6605 characters, roughly 1900 tokens.
        self.assertGreaterEqual(settings.LLM_SELF_HOSTED_MAX_TOKENS, 4096)


class GenerationLimitParityTests(unittest.TestCase):
    """Both provider paths must carry the limits, or a switch reverts them.

    These were set on the Google path first. Moving the analysis agents to
    OpenAI would then have looked like a provider difference while actually
    being a lost setting: the reasoning budget back to the provider default and
    no temperature sent at all (ALP-296).
    """

    def test_the_google_path_carries_all_three_limits(self):
        limits = llm._google_generation_limits()
        self.assertEqual(settings.LLM_HOSTED_MAX_TOKENS, limits["max_output_tokens"])
        self.assertEqual(settings.LLM_JSON_TEMPERATURE, limits["temperature"])
        self.assertEqual(
            settings.LLM_JSON_THINKING_BUDGET,
            limits["thinking_config"].thinking_budget,
        )

    def test_the_openai_path_carries_the_equivalents(self):
        limits = llm._openai_generation_limits(HOSTED, None)
        self.assertEqual(settings.LLM_JSON_REASONING_EFFORT, limits["reasoning_effort"])
        self.assertEqual(settings.LLM_JSON_TEMPERATURE, limits["temperature"])

    def test_neither_provider_path_is_left_empty(self):
        # The regression this guards is one path keeping its limits while the
        # other quietly loses them, which reads as a provider quirk.
        self.assertTrue(llm._google_generation_limits())
        self.assertTrue(llm._openai_generation_limits(HOSTED, None))

    def test_an_explicit_caller_effort_beats_the_default(self):
        # briefing_synthesis raises the arbiter deliberately; a global default
        # must not silently lower it.
        self.assertEqual(
            "high", llm._openai_generation_limits(HOSTED, "high")["reasoning_effort"]
        )

    def test_a_self_hosted_server_is_left_to_its_own_sampling(self):
        self.assertEqual({}, llm._openai_generation_limits(SELF_HOSTED, None))

    def test_a_refusal_of_the_optional_limits_is_recognised_and_recoverable(self):
        request = httpx.Request("POST", "http://x/chat/completions")
        rejected = httpx.HTTPStatusError(
            "bad request",
            request=request,
            response=httpx.Response(
                400,
                request=request,
                json={"error": "Unsupported parameter: 'temperature' is not supported"},
            ),
        )
        self.assertTrue(llm._rejects_generation_limits(rejected))
        # A context overflow is a different failure and must not be mistaken
        # for one, or the retry drops the wrong thing.
        overflow = httpx.HTTPStatusError(
            "bad request",
            request=request,
            response=httpx.Response(
                400,
                request=request,
                json={"error": "the prompt exceeds the context length"},
            ),
        )
        self.assertFalse(llm._rejects_generation_limits(overflow))


class TruncationDetectionTests(unittest.TestCase):
    def test_a_length_stop_is_recognised(self):
        self.assertTrue(llm._truncated({"choices": [{"finish_reason": "length"}]}))

    def test_a_normal_stop_is_not(self):
        self.assertFalse(llm._truncated({"choices": [{"finish_reason": "stop"}]}))

    def test_a_reply_without_choices_is_not_treated_as_truncated(self):
        self.assertFalse(llm._truncated({}))

    def test_the_message_names_the_agent_and_the_remedy(self):
        message = str(LLMReplyTruncated(SELF_HOSTED, "brief_arbiter"))
        self.assertIn("brief_arbiter", message)
        self.assertIn(SELF_HOSTED, message)
        self.assertIn("output limit", message)
        self.assertIn("max tokens", message)


class TruncatedJsonCallTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(
            mock.patch.object(llm, "is_local_only", mock.AsyncMock(return_value=False))
        )
        self.enterContext(
            mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k"))
        )
        self.enterContext(mock.patch.object(llm, "record_token_usage", mock.AsyncMock()))
        self.enterContext(
            mock.patch.object(
                llm,
                "resolve_endpoint",
                mock.AsyncMock(
                    return_value=OpenAIEndpoint(
                        base_url="http://localhost:1234/v1", model="qwen3.5-4b", api_key=""
                    )
                ),
            )
        )
        llm._json_mode_by_base_url.clear()
        self.addCleanup(llm._json_mode_by_base_url.clear)

    def _truncated_response(self):
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        return httpx.Response(
            200,
            request=request,
            json={
                # Well-formed JSON right up to the cut, which is exactly why the
                # raw decode error was so misleading.
                "choices": [
                    {"message": {"content": '{"notes": "part'}, "finish_reason": "length"}
                ],
                "usage": {},
            },
        )

    async def test_a_truncated_reply_is_reported_as_an_output_limit(self):
        fake = FakeHTTPX([self._truncated_response()])
        self.enterContext(mock.patch.object(llm.httpx, "AsyncClient", fake))

        with self.assertRaises(LLMReplyTruncated) as ctx:
            await llm.generate_json(
                SELF_HOSTED, "Prompt", BriefLensOutput, source="brief_arbiter"
            )
        self.assertEqual("brief_arbiter", ctx.exception.source)
        # Retrying cannot help, so the same ceiling must not be hit twice.
        self.assertEqual(1, len(fake.posts))

    async def test_the_request_carries_the_output_budget(self):
        fake = FakeHTTPX([_chat_response('{"notes": "ok"}')])
        self.enterContext(mock.patch.object(llm.httpx, "AsyncClient", fake))

        await llm.generate_json(SELF_HOSTED, "Prompt", BriefLensOutput)

        self.assertEqual(
            settings.LLM_SELF_HOSTED_MAX_TOKENS, fake.posts[0]["json"]["max_tokens"]
        )


class OutputBudgetNegotiationTests(unittest.IsolatedAsyncioTestCase):
    """A budget is only safe relative to a context window we cannot see."""

    def setUp(self):
        self.enterContext(
            mock.patch.object(llm, "is_local_only", mock.AsyncMock(return_value=False))
        )
        self.enterContext(
            mock.patch.object(llm, "_resolve_key", mock.AsyncMock(return_value="k"))
        )
        self.enterContext(mock.patch.object(llm, "record_token_usage", mock.AsyncMock()))
        self.enterContext(
            mock.patch.object(
                llm,
                "resolve_endpoint",
                mock.AsyncMock(
                    return_value=OpenAIEndpoint(
                        base_url="http://localhost:1234/v1", model="qwen3.5-4b", api_key=""
                    )
                ),
            )
        )
        for cache in (llm._json_mode_by_base_url, llm._json_budget_by_base_url):
            cache.clear()
            self.addCleanup(cache.clear)

    def _context_refusal(self):
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        return httpx.Response(
            400,
            request=request,
            json={"error": "the prompt plus max_tokens exceeds the context length"},
        )

    async def test_the_budget_is_halved_until_the_server_accepts_it(self):
        fake = FakeHTTPX(
            [self._context_refusal(), self._context_refusal(), _chat_response('{"notes": "ok"}')]
        )
        self.enterContext(mock.patch.object(llm.httpx, "AsyncClient", fake))

        parsed = await llm.generate_json(SELF_HOSTED, "Prompt", BriefLensOutput)

        self.assertEqual("ok", parsed.notes)
        budgets = [p["json"]["max_tokens"] for p in fake.posts]
        self.assertEqual(
            [
                settings.LLM_SELF_HOSTED_MAX_TOKENS,
                settings.LLM_SELF_HOSTED_MAX_TOKENS // 2,
                settings.LLM_SELF_HOSTED_MAX_TOKENS // 4,
            ],
            budgets,
        )

    async def test_the_accepted_budget_is_reused_on_the_next_call(self):
        fake = FakeHTTPX(
            [
                self._context_refusal(),
                _chat_response('{"notes": "a"}'),
                _chat_response('{"notes": "b"}'),
            ]
        )
        self.enterContext(mock.patch.object(llm.httpx, "AsyncClient", fake))

        await llm.generate_json(SELF_HOSTED, "Prompt", BriefLensOutput)
        await llm.generate_json(SELF_HOSTED, "Prompt", BriefLensOutput)

        # Three posts, not four: the second call starts at the learned budget.
        self.assertEqual(3, len(fake.posts))
        self.assertEqual(
            settings.LLM_SELF_HOSTED_MAX_TOKENS // 2, fake.posts[2]["json"]["max_tokens"]
        )

    async def test_an_unrelated_400_is_not_mistaken_for_a_budget_problem(self):
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        broken = httpx.Response(400, request=request, json={"error": "model not loaded"})
        fake = FakeHTTPX([broken])
        self.enterContext(mock.patch.object(llm.httpx, "AsyncClient", fake))

        with self.assertRaises(httpx.HTTPStatusError):
            await llm.generate_json(SELF_HOSTED, "Prompt", BriefLensOutput)
        self.assertEqual(1, len(fake.posts))

    async def test_the_server_explanation_survives_in_the_error(self):
        # Losing the body is what reduced a context refusal to a bare HTTP 400.
        request = httpx.Request("POST", "http://localhost:1234/v1/chat/completions")
        fake = FakeHTTPX(
            [httpx.Response(400, request=request, json={"error": "model not loaded"})]
        )
        self.enterContext(mock.patch.object(llm.httpx, "AsyncClient", fake))

        with self.assertRaises(httpx.HTTPStatusError) as ctx:
            await llm.generate_json(SELF_HOSTED, "Prompt", BriefLensOutput)
        self.assertIn("model not loaded", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
