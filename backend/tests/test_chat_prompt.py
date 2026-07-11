import unittest

from app.routers.chat import build_chat_prompt


def session_data(name, lines, *, briefing="", insights="", started_at="2026-07-01"):
    return {
        "name": name,
        "started_at": started_at,
        "sort_key": started_at,
        "briefing": briefing,
        "insights": insights,
        "lines": lines,
    }


class ChatPromptTests(unittest.TestCase):
    def test_speaker_attribution_and_headers(self):
        sessions = [session_data("Kickoff", [("Alice", "We need SSO."), ("Bob", "Agreed.")])]
        messages = [{"role": "user", "content": "What did Alice ask for?"}]
        prompt = build_chat_prompt(sessions, messages, budget=10000)
        self.assertIn("## Kickoff (2026-07-01)", prompt)
        self.assertIn("Alice: We need SSO.", prompt)
        self.assertIn("What did Alice ask for?", prompt)

    def test_oldest_sessions_truncated_first(self):
        old = session_data("Old", [("A", "x" * 5000)])
        new = session_data("New", [("B", "y" * 200)])
        prompt = build_chat_prompt([old, new], [{"role": "user", "content": "q"}], budget=1000)
        self.assertIn("New", prompt)
        self.assertIn("y" * 200, prompt)
        self.assertNotIn("x" * 5000, prompt)
        self.assertIn("[truncated]", prompt)

    def test_conversation_history_included_in_order(self):
        sessions = [session_data("S", [("A", "hello world")])]
        messages = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
            {"role": "user", "content": "second question"},
        ]
        prompt = build_chat_prompt(sessions, messages, budget=10000)
        self.assertLess(prompt.index("first question"), prompt.index("first answer"))
        self.assertLess(prompt.index("first answer"), prompt.index("second question"))

    def test_conversation_history_is_bounded_to_recent_messages(self):
        sessions = [session_data("S", [("A", "hello world")])]
        messages = [
            {"role": "user", "content": f"message-{index}"}
            for index in range(10)
        ]

        prompt = build_chat_prompt(sessions, messages, budget=10000)

        self.assertNotIn("message-0\n", prompt)
        self.assertNotIn("message-1\n", prompt)
        self.assertIn("message-2", prompt)
        self.assertIn("message-9", prompt)

    def test_briefing_insights_and_transcript_are_layered_in_priority_order(self):
        sessions = [session_data(
            "Discovery",
            [("Alice", "Transcript evidence")],
            briefing='{"top_outcomes":[{"title":"Primary outcome"}]}',
            insights='[{"text":"Supporting insight"}]',
        )]
        prompt = build_chat_prompt(
            sessions,
            [{"role": "user", "content": "What matters?"}],
            budget=10000,
        )

        self.assertIn("# Meeting Briefings (primary context)", prompt)
        self.assertIn("# Saved Insights (supporting context)", prompt)
        self.assertIn("# Meeting Transcripts (grounding evidence)", prompt)
        self.assertLess(prompt.index("Primary outcome"), prompt.index("Supporting insight"))
        self.assertLess(prompt.index("Supporting insight"), prompt.index("Transcript evidence"))

    def test_budget_truncates_transcript_after_preserving_brief_and_insight(self):
        sessions = [session_data(
            "Discovery",
            [("Alice", "T" * 5000)],
            briefing="BRIEFING_PRIORITY",
            insights="INSIGHT_PRIORITY",
        )]
        prompt = build_chat_prompt(
            sessions,
            [{"role": "user", "content": "q"}],
            budget=600,
        )

        self.assertIn("BRIEFING_PRIORITY", prompt)
        self.assertIn("INSIGHT_PRIORITY", prompt)
        self.assertIn("[truncated]", prompt)
        self.assertNotIn("T" * 5000, prompt)

    def test_missing_optional_layers_still_allows_transcript_chat(self):
        sessions = [session_data("Transcript only", [("Bob", "Ground truth")])]
        prompt = build_chat_prompt(
            sessions,
            [{"role": "user", "content": "q"}],
            budget=10000,
        )

        self.assertNotIn("Meeting Briefings", prompt)
        self.assertNotIn("Saved Insights", prompt)
        self.assertIn("Ground truth", prompt)

    def test_newest_session_survives_layer_truncation(self):
        old = session_data("Old", [], briefing="O" * 5000, started_at="2026-07-01")
        new = session_data("New", [], briefing="NEW_BRIEF", started_at="2026-07-02")
        prompt = build_chat_prompt(
            [old, new],
            [{"role": "user", "content": "q"}],
            budget=500,
        )

        self.assertIn("NEW_BRIEF", prompt)
        self.assertIn("[truncated]", prompt)


if __name__ == "__main__":
    unittest.main()
