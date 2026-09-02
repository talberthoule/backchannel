"""Provider keys never reach a log line or an error message verbatim."""

import io
import logging
import unittest

from app.services import redaction

GOOGLE_KEY = "AIzaSyD4mmyKeyValue0123456789abcdefghij"
OPENAI_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
OPAQUE_KEY = "opaque-endpoint-token-9f8e7d6c5b4a"


class RedactTextTests(unittest.TestCase):
    def setUp(self):
        redaction.clear_registered_secrets()

    def tearDown(self):
        redaction.clear_registered_secrets()

    def test_registered_value_is_scrubbed_wherever_it_appears(self):
        redaction.register_secret(OPAQUE_KEY)
        text = f"GET https://proxy.example/v1/models token={OPAQUE_KEY} failed: {OPAQUE_KEY}"
        self.assertNotIn(OPAQUE_KEY, redaction.redact_text(text))

    def test_short_values_are_not_registered(self):
        redaction.register_secret("abc")
        self.assertEqual(0, redaction.registered_secret_count())
        self.assertEqual("abc def", redaction.redact_text("abc def"))

    def test_everyday_words_used_as_keys_do_not_eat_log_lines(self):
        # A self-hosted server whose "key" is the same word as its name.
        redaction.register_secret("lm-studio")
        self.assertEqual(0, redaction.registered_secret_count())
        line = "Using response_format 'json_schema' for endpoint:lm-studio:qwen"
        self.assertEqual(line, redaction.redact_text(line))
        # The header shapes still cover a short key where it is a credential.
        self.assertNotIn("lm-studio", redaction.redact_text("Authorization: Bearer lm-studio"))

    def test_endpoint_slugs_are_exempt_even_when_long(self):
        slug = "my-gpu-box-endpoint-name"
        redaction.exempt_from_redaction(slug)
        redaction.register_secret(slug)
        self.assertEqual(0, redaction.registered_secret_count())
        line = f"Added custom endpoint {slug} (http://gpu:1234/v1)"
        self.assertEqual(line, redaction.redact_text(line))
        # Exempting after registration also un-registers.
        redaction.register_secret(OPAQUE_KEY)
        redaction.exempt_from_redaction(OPAQUE_KEY)
        self.assertEqual(0, redaction.registered_secret_count())

    def test_bearer_tokens_are_scrubbed_regardless_of_length(self):
        for text in ("Authorization: Bearer short", "Bearer abc", "authorization=Bearer x1"):
            with self.subTest(text=text):
                result = redaction.redact_text(text)
                self.assertNotIn("short", result)
                self.assertNotIn("abc", result)
                self.assertNotIn("x1", result)
                self.assertIn("[redacted]", result)

    def test_master_key_diagnostics_survive_redaction(self):
        path = r"C:\Users\someone\AppData\Local\Backchannel\data\master.key"
        message = (
            "Stored credentials.google.api_key credential is unreadable because the "
            f"master key cannot be used - {path} is DPAPI-protected and can only be "
            "read on the Windows account that created it"
        )
        self.assertEqual(message, redaction.redact_text(message))
        recovery = (
            f"The credentials master key at {path} cannot be used on this account or "
            "machine (CryptUnprotectData failed (error 13)). Provider keys stored with "
            "it are unreadable until it is replaced: stop Backchannel, delete that file, "
            "start again, and re-enter the provider keys in Admin -> Connections."
        )
        self.assertEqual(recovery, redaction.redact_text(recovery))

    def test_published_key_prefixes_are_scrubbed_without_registration(self):
        for key in (GOOGLE_KEY, OPENAI_KEY):
            self.assertNotIn(key, redaction.redact_text(f"error for key {key}."))

    def test_bearer_and_header_forms_are_scrubbed(self):
        cases = [
            f"Authorization: Bearer {OPAQUE_KEY}",
            f"x-goog-api-key: {OPAQUE_KEY}",
            f'headers={{"api_key": "{OPAQUE_KEY}"}}',
            f"Token auth_tokens/{OPAQUE_KEY}",
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertNotIn(OPAQUE_KEY, redaction.redact_text(text))

    def test_query_parameters_and_userinfo_are_scrubbed(self):
        url = f"https://user:{OPAQUE_KEY}@proxy.example/v1?api_key={OPAQUE_KEY}&x=1&key={OPAQUE_KEY}"
        result = redaction.redact_text(url)
        self.assertNotIn(OPAQUE_KEY, result)
        self.assertIn("x=1", result)
        self.assertIn("proxy.example/v1", result)

    def test_ordinary_text_is_untouched(self):
        text = "Transcribed segment (48000 bytes) with model gemini-3.5-flash; token usage recorded"
        self.assertEqual(text, redaction.redact_text(text))

    def test_none_and_empty(self):
        self.assertEqual("", redaction.redact_text(None))
        self.assertEqual("", redaction.redact_text(""))


class LogRedactionTests(unittest.TestCase):
    def setUp(self):
        redaction.clear_registered_secrets()
        redaction.install_log_redaction()
        redaction.register_secret(OPAQUE_KEY)
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.logger = logging.getLogger("test.redaction")
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)

    def tearDown(self):
        self.logger.removeHandler(self.handler)
        redaction.clear_registered_secrets()

    def test_formatted_message_and_args_are_scrubbed(self):
        self.logger.warning("provider error for %s with %s", "openai", f"Bearer {OPAQUE_KEY}")
        self.logger.info(f"connect failed: key={GOOGLE_KEY}")
        output = self.stream.getvalue()
        self.assertNotIn(OPAQUE_KEY, output)
        self.assertNotIn(GOOGLE_KEY, output)
        self.assertIn("provider error for openai", output)

    def test_exception_text_and_traceback_are_scrubbed(self):
        try:
            raise RuntimeError(f"Client error for url 'https://x.example/v1/models?key={OPAQUE_KEY}'")
        except RuntimeError:
            self.logger.exception("call failed")
        output = self.stream.getvalue()
        self.assertIn("RuntimeError", output)
        self.assertIn("call failed", output)
        self.assertNotIn(OPAQUE_KEY, output)

    def test_stack_info_is_scrubbed(self):
        self.logger.info(f"stack for {OPAQUE_KEY}", stack_info=True)
        output = self.stream.getvalue()
        self.assertIn("Stack (most recent call last)", output)
        self.assertNotIn(OPAQUE_KEY, output)

    def test_assert_logs_sees_scrubbed_output(self):
        with self.assertLogs("test.redaction.child", level="INFO") as captured:
            logging.getLogger("test.redaction.child").info("key %s", OPAQUE_KEY)
        self.assertNotIn(OPAQUE_KEY, "\n".join(captured.output))


class FilterTests(unittest.TestCase):
    """The handler-level filter, for handlers configured outside the factory."""

    def test_filter_scrubs_records_built_by_the_plain_factory(self):
        redaction.register_secret(OPAQUE_KEY)
        self.addCleanup(redaction.clear_registered_secrets)
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "key %s", (OPAQUE_KEY,), None)
        try:
            raise ValueError(OPAQUE_KEY)
        except ValueError:
            import sys

            record.exc_info = sys.exc_info()
        redaction.SecretRedactionFilter().filter(record)
        formatted = logging.Formatter("%(message)s").format(record)
        self.assertNotIn(OPAQUE_KEY, formatted)
        self.assertIn("ValueError", formatted)


if __name__ == "__main__":
    unittest.main()
