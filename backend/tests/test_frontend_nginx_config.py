import re
import unittest
from pathlib import Path


class FrontendNginxConfigTests(unittest.TestCase):
    def test_api_proxy_allows_long_audio_imports(self):
        config_path = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"
        if not config_path.is_file():
            self.skipTest("frontend/nginx.conf is unavailable in this backend-only environment")
        config = config_path.read_text(encoding="utf-8")
        api_block_match = re.search(r"location /api/ \{(?P<body>.*?)\n    \}", config, flags=re.DOTALL)

        self.assertIsNotNone(api_block_match)
        api_block = api_block_match.group("body")
        self.assertIn("proxy_read_timeout 1800s;", api_block)
        self.assertIn("proxy_send_timeout 1800s;", api_block)


if __name__ == "__main__":
    unittest.main()
