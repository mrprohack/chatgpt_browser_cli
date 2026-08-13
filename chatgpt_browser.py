"""Backward-compatible entry point for the modular chatgpt_browser_cli implementation."""

from chatgpt_browser_cli.auth import load_cookie_file
from chatgpt_browser_cli.cli import format_result, main, parse_args, resolve_headless
from chatgpt_browser_cli.models import ErrorCode, RunResult, TaskStatus, UiSnapshot
from chatgpt_browser_cli.runner import ChatGPTBrowser, decide_terminal_state

__all__ = [
    "ChatGPTBrowser",
    "ErrorCode",
    "RunResult",
    "TaskStatus",
    "UiSnapshot",
    "decide_terminal_state",
    "format_result",
    "load_cookie_file",
    "main",
    "parse_args",
    "resolve_headless",
]


if __name__ == "__main__":
    raise SystemExit(main())
