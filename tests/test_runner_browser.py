import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from chatgpt_browser_cli.models import ErrorCode, TaskStatus
from chatgpt_browser_cli.runner import ChatGPTBrowser


@unittest.skipUnless(shutil.which("chromium") or shutil.which("google-chrome"), "system Chromium/Chrome not installed")
class BrowserRunnerTests(unittest.TestCase):
    def _exe(self):
        return shutil.which("chromium") or shutil.which("google-chrome")

    def test_headed_auth_wait_continues_when_composer_appears(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<button id="login">Log in</button><script>setTimeout(()=>{login.remove();document.body.insertAdjacentHTML("beforeend", "<div id=\\"prompt-textarea\\" contenteditable=\\"true\\" role=\\"textbox\\"></div>")}, 250)</script>')
                runner = ChatGPTBrowser(profile_dir=Path(td) / "profile2", headless=False, executable_path=self._exe(), auth_wait_seconds=2, ready_timeout_seconds=1, poll_seconds=0.05)
                self.assertIsNone(runner._wait_until_ready(page))
            finally:
                context.close()

    def test_headless_auth_requirement_returns_immediately(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<button>Log in</button>')
                runner = ChatGPTBrowser(profile_dir=Path(td) / "profile2", headless=True, executable_path=self._exe(), auth_wait_seconds=5, ready_timeout_seconds=0.2, poll_seconds=0.05)
                started = time.monotonic()
                result = runner._wait_until_ready(page)
                self.assertEqual(result.status, TaskStatus.NEEDS_USER_ACTION)
                self.assertEqual(result.error_code, ErrorCode.AUTH_REQUIRED)
                self.assertLess(time.monotonic() - started, 1.0)
            finally:
                context.close()

    def test_cookie_import_uses_normalized_cookie_file(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            cookie_file = Path(td) / "cookies.json"
            cookie_file.write_text(json.dumps([{"name": "test_cookie", "value": "test_value", "url": "https://chatgpt.com", "sameSite": "Lax"}]), encoding="utf-8")
            context = p.chromium.launch_persistent_context(str(Path(td) / "profile"), headless=True, executable_path=self._exe())
            try:
                runner = ChatGPTBrowser(profile_dir=Path(td) / "other", headless=True, executable_path=self._exe(), cookies_path=cookie_file)
                self.assertIsNone(runner._import_cookies(context))
                self.assertEqual([(cookie["name"], cookie["value"]) for cookie in context.cookies("https://chatgpt.com")], [("test_cookie", "test_value")])
            finally:
                context.close()

    def test_model_selection_is_verified(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p, tempfile.TemporaryDirectory() as td:
            context = p.chromium.launch_persistent_context(td, headless=True, executable_path=self._exe())
            try:
                page = context.pages[0]
                page.set_content('<button id="picker" aria-label="Model selector">Default</button><button id="gpt5">GPT-5</button><script>gpt5.onclick=()=>{picker.textContent="GPT-5";gpt5.setAttribute("aria-selected","true")}</script>')
                runner = ChatGPTBrowser(profile_dir=Path(td), headless=True, executable_path=self._exe())
                self.assertIsNone(runner._select_model(page, "GPT-5"))
            finally:
                context.close()


if __name__ == "__main__":
    unittest.main()
