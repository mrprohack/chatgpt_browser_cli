from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .auth import load_cookie_file
from .models import ErrorCode, RunResult, TaskStatus, UiSnapshot

CHATGPT_URL = "https://chatgpt.com/"
DELEGATION_ENV = "CHATGPT_BROWSER_DELEGATION_ACTIVE"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def decide_terminal_state(
    snapshot: UiSnapshot,
    *,
    initial_assistant_count: int,
    stable_observations: int,
    required_stable_observations: int = 2,
) -> RunResult | None:
    if snapshot.needs_user_action:
        return RunResult(
            TaskStatus.NEEDS_USER_ACTION,
            required_action=snapshot.needs_user_action,
            error_code=snapshot.error_code if snapshot.error_code != ErrorCode.NONE else ErrorCode.AUTH_REQUIRED,
        )
    if snapshot.fatal_error:
        return RunResult(
            TaskStatus.FAILED,
            reason=snapshot.fatal_error,
            error_code=snapshot.error_code if snapshot.error_code != ErrorCode.NONE else ErrorCode.CHATGPT_ERROR,
        )
    has_new_answer = snapshot.assistant_count > initial_assistant_count and bool(snapshot.latest_assistant_text.strip())
    if snapshot.stopped_indicator and has_new_answer:
        return RunResult(
            TaskStatus.STOPPED,
            result=snapshot.latest_assistant_text.strip(),
            reason="ChatGPT generation appears to have been stopped or interrupted.",
            error_code=ErrorCode.GENERATION_STOPPED,
        )
    if has_new_answer and not snapshot.is_running and stable_observations >= max(1, required_stable_observations):
        return RunResult(TaskStatus.COMPLETED, result=snapshot.latest_assistant_text.strip())
    return None


class ChatGPTBrowser:
    COMPOSER = (
        "#prompt-textarea",
        '[data-testid="prompt-textarea"]',
        'textarea[placeholder*="Ask" i]',
        'div[contenteditable="true"][role="textbox"]',
    )
    SEND = ('button[data-testid="send-button"]', 'button[aria-label*="Send" i]')
    STOP = (
        'button[data-testid="stop-button"]',
        'button[aria-label*="Stop" i]',
        'button:has-text("Stop generating")',
    )
    CONTINUE = ('button:has-text("Continue generating")', 'button:has-text("Continue")')
    MODEL_PICKER = ('button[aria-label*="model" i]', 'button[data-testid*="model" i]')
    ATTACH = (
        'button[aria-label*="Attach" i]',
        'button[aria-label*="file" i]',
        'button:has-text("Add files")',
    )

    def __init__(
        self,
        *,
        profile_dir: Path,
        headless: bool = False,
        executable_path: str | None = None,
        timeout_seconds: int = 900,
        poll_seconds: float = 1.5,
        cookies_path: Path | None = None,
        auth_wait_seconds: int = 0,
        ready_timeout_seconds: float = 15,
        stable_observations: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self.profile_dir = profile_dir.expanduser().resolve()
        self.headless = headless
        self.executable_path = executable_path
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.cookies_path = cookies_path.expanduser().resolve() if cookies_path else None
        self.auth_wait_seconds = max(0, int(auth_wait_seconds))
        self.ready_timeout_seconds = max(0.1, float(ready_timeout_seconds))
        self.stable_observations = max(1, int(stable_observations))
        self.logger = logger or logging.getLogger("chatgpt_browser_cli")

    def _first_visible(self, page: Page, selectors: Iterable[str]) -> Locator | None:
        for selector in selectors:
            try:
                loc = page.locator(selector)
                for index in range(min(loc.count(), 8)):
                    candidate = loc.nth(index)
                    if candidate.is_visible(timeout=250):
                        return candidate
            except Exception as exc:
                self.logger.debug("selector probe failed selector=%r error=%s", selector, type(exc).__name__)
        return None

    def _find_composer(self, page: Page) -> Locator | None:
        return self._first_visible(page, self.COMPOSER)

    def _assistant_messages(self, page: Page) -> list[str]:
        messages: list[str] = []
        try:
            loc = page.locator('[data-message-author-role="assistant"]')
            for index in range(loc.count()):
                item = loc.nth(index)
                if item.is_visible(timeout=150):
                    text = item.inner_text(timeout=500).strip()
                    if text:
                        messages.append(text)
        except Exception as exc:
            self.logger.debug("assistant-message inspection failed error=%s", type(exc).__name__)
        return messages

    def _body_text(self, page: Page) -> str:
        try:
            return page.locator("body").inner_text(timeout=1200).lower()
        except Exception as exc:
            self.logger.debug("body inspection failed error=%s", type(exc).__name__)
            return ""

    def _auth_requirement(self, page: Page) -> tuple[str, ErrorCode] | None:
        if self._find_composer(page):
            return None
        if self._first_visible(page, ('iframe[src*="captcha" i]', 'iframe[src*="challenges.cloudflare.com" i]', '[class*="captcha" i]')):
            return ("Complete the CAPTCHA / human-verification challenge in the opened browser.", ErrorCode.CAPTCHA_REQUIRED)
        body = self._body_text(page)
        if any(text in body for text in ("verify you are human", "security check", "captcha")):
            return ("Complete the human-verification/security check in the opened browser.", ErrorCode.CAPTCHA_REQUIRED)
        if any(text in body for text in ("two-factor", "2fa", "verification code", "authenticator")):
            return ("Complete the two-factor authentication step in the opened browser.", ErrorCode.TWO_FACTOR_REQUIRED)
        try:
            has_password = page.locator('input[type="password"]').count() > 0
        except Exception as exc:
            self.logger.debug("password-field inspection failed error=%s", type(exc).__name__)
            has_password = False
        has_login = self._first_visible(page, ('a:has-text("Log in")', 'button:has-text("Log in")'))
        if has_password or has_login:
            return ("Log in to ChatGPT in the opened browser, then continue using the same profile or cookie file.", ErrorCode.AUTH_REQUIRED)
        return None

    def _needs_user_action(self, page: Page) -> str:
        requirement = self._auth_requirement(page)
        return requirement[0] if requirement else ""

    def _fatal_error_detail(self, page: Page) -> tuple[str, ErrorCode] | None:
        body = self._body_text(page)
        if not body:
            return None
        for phrase in ("rate limit", "you have reached your limit", "usage limit"):
            if phrase in body:
                return (f"ChatGPT displayed a limit error: {phrase}", ErrorCode.RATE_LIMIT)
        for phrase in ("something went wrong", "there was an error generating a response", "unable to load", "network error"):
            if phrase in body:
                return (f"ChatGPT displayed an error: {phrase}", ErrorCode.CHATGPT_ERROR)
        return None

    def _fatal_error(self, page: Page) -> str:
        detail = self._fatal_error_detail(page)
        return detail[0] if detail else ""

    def _snapshot(self, page: Page) -> UiSnapshot:
        messages = self._assistant_messages(page)
        fatal = self._fatal_error_detail(page)
        auth = self._auth_requirement(page)
        error_code = fatal[1] if fatal else auth[1] if auth else ErrorCode.NONE
        return UiSnapshot(
            assistant_count=len(messages),
            latest_assistant_text=messages[-1] if messages else "",
            is_running=bool(self._first_visible(page, self.STOP)),
            stopped_indicator=bool(self._first_visible(page, self.CONTINUE)),
            fatal_error=fatal[0] if fatal else "",
            needs_user_action=auth[0] if auth else "",
            error_code=error_code,
        )

    def _wait_until_ready(self, page: Page) -> RunResult | None:
        ready_deadline = time.monotonic() + self.ready_timeout_seconds
        while time.monotonic() < ready_deadline:
            if self._find_composer(page):
                return None
            if fatal := self._fatal_error_detail(page):
                return RunResult(TaskStatus.FAILED, reason=fatal[0], error_code=fatal[1])
            if auth := self._auth_requirement(page):
                if self.headless or self.auth_wait_seconds <= 0:
                    return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=auth[0], error_code=auth[1])
                self.logger.info("waiting for user authentication action code=%s", auth[1].value)
                auth_deadline = time.monotonic() + self.auth_wait_seconds
                while time.monotonic() < auth_deadline:
                    if self._find_composer(page):
                        self.logger.info("authentication action completed; composer is available")
                        return None
                    if fatal := self._fatal_error_detail(page):
                        return RunResult(TaskStatus.FAILED, reason=fatal[0], error_code=fatal[1])
                    time.sleep(self.poll_seconds)
                return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=auth[0], error_code=auth[1])
            time.sleep(self.poll_seconds)
        if self._find_composer(page):
            return None
        if auth := self._auth_requirement(page):
            return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=auth[0], error_code=auth[1])
        return RunResult(TaskStatus.FAILED, reason="ChatGPT loaded, but a usable composer did not appear.", error_code=ErrorCode.COMPOSER_NOT_FOUND)

    def _select_model(self, page: Page, requested: str) -> RunResult | None:
        requested = requested.strip()
        if not requested:
            return None
        self.logger.info("selecting requested model name=%s", requested)
        picker = self._first_visible(page, self.MODEL_PICKER)
        if not picker:
            return RunResult(TaskStatus.FAILED, reason=f'Requested model "{requested}", but no model selector was found.', error_code=ErrorCode.MODEL_UNAVAILABLE)
        try:
            picker.click(timeout=2500)
            options = page.get_by_text(requested, exact=False)
            chosen = next((options.nth(index) for index in range(min(options.count(), 20)) if options.nth(index).is_visible(timeout=250)), None)
            if chosen is None:
                return RunResult(TaskStatus.FAILED, reason=f'Requested model "{requested}" is not available in the current UI.', error_code=ErrorCode.MODEL_UNAVAILABLE)
            chosen.click(timeout=3000)
            time.sleep(0.4)
            picker = self._first_visible(page, self.MODEL_PICKER)
            if picker and requested.casefold() in picker.inner_text(timeout=1000).casefold():
                return None
            selected = page.locator('[aria-selected="true"], [aria-checked="true"], [data-state="checked"], [data-state="selected"]')
            for index in range(min(selected.count(), 30)):
                if requested.casefold() in selected.nth(index).inner_text(timeout=500).casefold():
                    return None
        except Exception as exc:
            self.logger.debug("model selection failed error=%s", type(exc).__name__, exc_info=True)
        return RunResult(TaskStatus.FAILED, reason=f'Requested model "{requested}" could not be selected and verified.', error_code=ErrorCode.MODEL_UNAVAILABLE)

    def _upload_files(self, page: Page, files: Sequence[Path]) -> RunResult | None:
        if not files:
            return None
        paths = [path.expanduser().resolve() for path in files]
        if any(not path.is_file() for path in paths):
            return RunResult(TaskStatus.FAILED, reason="One or more requested attachments do not exist.", error_code=ErrorCode.ATTACHMENT_MISSING)
        self.logger.info("attaching files count=%d", len(paths))
        try:
            file_input = page.locator('input[type="file"]')
            if not file_input.count():
                button = self._first_visible(page, self.ATTACH)
                if button:
                    button.click(timeout=2000)
                    time.sleep(0.3)
            file_input = page.locator('input[type="file"]')
            if not file_input.count():
                return RunResult(TaskStatus.FAILED, reason="ChatGPT file input was not available.", error_code=ErrorCode.UPLOAD_FAILED)
            file_input.first.set_input_files([str(path) for path in paths], timeout=5000)
            time.sleep(0.8)
            return None
        except Exception as exc:
            self.logger.debug("file upload failed error=%s", type(exc).__name__, exc_info=True)
            return RunResult(TaskStatus.FAILED, reason=f"Could not attach requested file(s): {type(exc).__name__}", error_code=ErrorCode.UPLOAD_FAILED)

    def _submit_prompt(self, page: Page, prompt: str) -> RunResult | None:
        composer = self._find_composer(page)
        if not composer:
            auth = self._auth_requirement(page)
            if auth:
                return RunResult(TaskStatus.NEEDS_USER_ACTION, required_action=auth[0], error_code=auth[1])
            return RunResult(TaskStatus.FAILED, reason="ChatGPT composer was not found.", error_code=ErrorCode.COMPOSER_NOT_FOUND)
        try:
            composer.click(timeout=2000)
            try:
                composer.fill(prompt, timeout=5000)
            except Exception:
                composer.press("Control+A")
                composer.type(prompt, delay=0)
            send = self._first_visible(page, self.SEND)
            if send:
                send.click(timeout=3000)
            else:
                composer.press("Enter")
            self.logger.info("task submitted")
            return None
        except Exception as exc:
            self.logger.debug("task submission failed error=%s", type(exc).__name__, exc_info=True)
            return RunResult(TaskStatus.FAILED, reason=f"Could not submit the task to ChatGPT: {type(exc).__name__}", error_code=ErrorCode.SUBMIT_FAILED)

    def _launch_context(self, playwright: Playwright) -> BrowserContext:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {"headless": self.headless, "viewport": {"width": 1440, "height": 1000}}
        if self.executable_path:
            kwargs["executable_path"] = self.executable_path
        self.logger.info("launching browser mode=%s", "headless" if self.headless else "headed")
        return playwright.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)

    def _import_cookies(self, context: BrowserContext) -> RunResult | None:
        if not self.cookies_path:
            return None
        try:
            cookies = load_cookie_file(self.cookies_path)
            context.add_cookies(cookies)
            self.logger.info("cookies imported count=%d", len(cookies))
            return None
        except Exception as exc:
            self.logger.debug("cookie import failed error=%s", type(exc).__name__, exc_info=True)
            return RunResult(TaskStatus.FAILED, reason=f"Could not import cookies from {self.cookies_path}: {type(exc).__name__}", error_code=ErrorCode.COOKIE_IMPORT_FAILED)

    def _monitor_generation(self, page: Page, initial_count: int) -> RunResult:
        deadline = time.monotonic() + self.timeout_seconds
        last_text = ""
        stable = 0
        saw_running = False
        while time.monotonic() < deadline:
            snapshot = self._snapshot(page)
            saw_running = saw_running or snapshot.is_running
            if snapshot.latest_assistant_text:
                stable = stable + 1 if snapshot.latest_assistant_text == last_text else 1
                last_text = snapshot.latest_assistant_text
            else:
                stable = 0
            terminal = decide_terminal_state(snapshot, initial_assistant_count=initial_count, stable_observations=stable, required_stable_observations=self.stable_observations)
            if terminal:
                self.logger.info("task terminal status=%s error_code=%s", terminal.status.value, terminal.error_code.value)
                return terminal
            time.sleep(self.poll_seconds)
        final = self._snapshot(page)
        if final.latest_assistant_text:
            reason = "Monitoring timeout reached while ChatGPT still appeared active." if final.is_running or saw_running else "Monitoring timeout reached before completion could be verified."
            return RunResult(TaskStatus.STOPPED, result=final.latest_assistant_text, reason=reason, error_code=ErrorCode.TIMEOUT)
        return RunResult(TaskStatus.FAILED, reason="Monitoring timeout reached and no ChatGPT answer was observed.", error_code=ErrorCode.TIMEOUT)

    def run(self, prompt: str, *, files: Sequence[Path] = (), requested_model: str = "") -> RunResult:
        if _env_truthy(DELEGATION_ENV):
            return RunResult(TaskStatus.FAILED, reason="Anti-recursion guard: CHATGPT_BROWSER_DELEGATION_ACTIVE is already set.", error_code=ErrorCode.ANTI_RECURSION)
        if not prompt.strip():
            return RunResult(TaskStatus.FAILED, reason="The task prompt is empty.", error_code=ErrorCode.EMPTY_PROMPT)
        old_flag = os.environ.get(DELEGATION_ENV)
        os.environ[DELEGATION_ENV] = "true"
        context: BrowserContext | None = None
        try:
            with sync_playwright() as playwright:
                try:
                    context = self._launch_context(playwright)
                except Exception as exc:
                    self.logger.debug("browser launch failed error=%s", type(exc).__name__, exc_info=True)
                    return RunResult(TaskStatus.FAILED, reason=f"Could not launch Chromium: {type(exc).__name__}", error_code=ErrorCode.BROWSER_LAUNCH_FAILED)
                if cookie_error := self._import_cookies(context):
                    return cookie_error
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(5000)
                self.logger.info("navigating to ChatGPT")
                try:
                    page.goto(CHATGPT_URL, wait_until="domcontentloaded", timeout=30000)
                except PlaywrightTimeoutError:
                    self.logger.warning("ChatGPT navigation timed out; inspecting loaded page state")
                except Exception as exc:
                    self.logger.debug("navigation failed error=%s", type(exc).__name__, exc_info=True)
                    return RunResult(TaskStatus.FAILED, reason=f"Could not open ChatGPT.com: {type(exc).__name__}", error_code=ErrorCode.NAVIGATION_FAILED)
                if ready_error := self._wait_until_ready(page):
                    return ready_error
                if model_error := self._select_model(page, requested_model):
                    return model_error
                if upload_error := self._upload_files(page, files):
                    return upload_error
                initial_count = len(self._assistant_messages(page))
                if submit_error := self._submit_prompt(page, prompt.strip()):
                    return submit_error
                return self._monitor_generation(page, initial_count)
        except Exception as exc:
            self.logger.exception("unrecoverable browser error type=%s", type(exc).__name__)
            return RunResult(TaskStatus.FAILED, reason=f"Unrecoverable browser error: {type(exc).__name__}", error_code=ErrorCode.UNEXPECTED_ERROR)
        finally:
            if context:
                try:
                    context.close()
                except Exception as exc:
                    self.logger.debug("browser context close failed error=%s", type(exc).__name__)
            if old_flag is None:
                os.environ.pop(DELEGATION_ENV, None)
            else:
                os.environ[DELEGATION_ENV] = old_flag
