import unittest

from app.routers.chat import build_chat_prompt


def session_data(name, lines):
    return {"name": name, "started_at": "2026-07-01", "lines": lines}


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


if __name__ == "__main__":
    unittest.main()
