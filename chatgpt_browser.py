"""Backward-compatible entry point for the chatgpt_browser_cli package."""

from chatgpt_browser_cli import (
    ChatGPTBrowser,
    ErrorCode,
    RunResult,
    TaskStatus,
    UiSnapshot,
    decide_terminal_state,
    format_result,
    load_cookie_file,
    main,
    parse_args,
    resolve_headless,
)

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
