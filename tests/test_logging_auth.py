import io
import json
import tempfile
import unittest
from pathlib import Path

from chatgpt_browser_cli.auth import load_cookie_file
from chatgpt_browser_cli.logging_utils import configure_logging


class CookieModuleTests(unittest.TestCase):
    def test_normalizes_browser_cookie_export(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cookies.json"
            path.write_text(json.dumps([{"name": "session", "value": "test-value", "domain": ".chatgpt.com", "expirationDate": 2_000_000_000.0, "sameSite": "no_restriction", "hostOnly": False}]), encoding="utf-8")
            cookies = load_cookie_file(path)
        self.assertEqual(cookies[0]["expires"], 2_000_000_000.0)
        self.assertEqual(cookies[0]["sameSite"], "None")
        self.assertEqual(cookies[0]["path"], "/")
        self.assertNotIn("hostOnly", cookies[0])


class LoggingTests(unittest.TestCase):
    def test_logger_writes_lifecycle_message(self):
        stream = io.StringIO()
        logger = configure_logging("DEBUG", stream=stream, logger_name="chatgpt_browser_cli.test")
        logger.info("browser mode=headless")
        self.assertIn("browser mode=headless", stream.getvalue())

    def test_logger_does_not_duplicate_handlers_when_reconfigured(self):
        stream = io.StringIO()
        logger = configure_logging("INFO", stream=stream, logger_name="chatgpt_browser_cli.dup")
        logger = configure_logging("INFO", stream=stream, logger_name="chatgpt_browser_cli.dup")
        logger.info("once")
        self.assertEqual(stream.getvalue().count("once"), 1)


if __name__ == "__main__":
    unittest.main()
