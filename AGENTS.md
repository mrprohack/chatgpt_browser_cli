# AGENTS.md

## Project purpose

`chatgpt_browser_cli` is a defensive Playwright CLI that delegates one user task to the live ChatGPT website and reports a verified terminal state.

Core workflow:

`Submit -> Observe -> Verify -> Return`

Never report `COMPLETED` while generation is still active or before a new assistant response is stable.

## Architecture

- `chatgpt_browser.py` — backward-compatible executable/import shim. Keep it thin.
- `chatgpt_browser_cli/models.py` — public enums and dataclasses only.
- `chatgpt_browser_cli/auth.py` — cookie JSON loading/normalization. Never log cookie values.
- `chatgpt_browser_cli/logging_utils.py` — logger setup and secret redaction.
- `chatgpt_browser_cli/runner.py` — Playwright browser lifecycle, selectors, auth detection, submission, monitoring.
- `chatgpt_browser_cli/cli.py` — CLI parsing, browser-mode resolution, output formatting, process exit code.
- `tests/` — unit and local DOM/browser tests. Tests must not require a real ChatGPT account.

Keep responsibilities separated. Do not move presentation/printing into the runner and do not put browser automation into the CLI parser.

## Security invariants

Never:

- bypass login, CAPTCHA, 2FA, passkeys, account authorization, rate limits, or security checks;
- print or log passwords, cookie values, auth tokens, session IDs, prompt contents, uploaded file contents, or browser storage state;
- commit `cookies.json`, storage-state files, `.env`, or persistent browser profiles;
- weaken a security check merely to make automation continue.

Cookie files are credentials. If code handles cookie values, register them with the logging redaction layer before diagnostic exceptions can be emitted.

## Browser behavior

- Default mode is headed for backward compatibility.
- `--headless` explicitly disables the visible window.
- `--headed` explicitly enables the visible window.
- If neither is supplied, `CHATGPT_BROWSER_HEADLESS` may select headless mode.
- Manual auth waiting is only useful in headed mode. Headless runs return `NEEDS USER ACTION` for login/CAPTCHA/2FA.
- Use persistent Playwright context for normal session reuse.
- Do not assume ChatGPT.com's DOM is stable. Prefer accessible/test-id selectors and maintain small fallback selector groups.

## Completion rules

A task may be `COMPLETED` only when all are true:

1. a new assistant message exists after submission;
2. generation is not active;
3. the latest answer is unchanged for the configured stability observations.

A visible `Continue generating` control is not enough to report `STOPPED` unless a new assistant response exists.

For file-producing tasks, future changes must also verify the requested artifact exists before returning `COMPLETED`.

## Error handling

Expected failures return `RunResult` with a specific `ErrorCode`.

Use `FAILED` for unrecoverable browser/UI errors, `STOPPED` for interrupted/timeout partial generation, and `NEEDS USER ACTION` for authentication/security/user-interaction gates.

Avoid `except Exception: pass`. Narrow exceptions where practical. Defensive selector probes may catch broad Playwright failures, but log only non-sensitive diagnostic metadata at DEBUG level.

Do not include raw prompt text or cookie data in exception messages.

## Logging

Use `logging.getLogger("chatgpt_browser_cli")` or a child logger.

Safe lifecycle fields include:

- browser mode;
- number of uploaded files;
- requested model name;
- terminal status and error code;
- exception class names.

Unsafe fields include prompt text, cookie values, tokens, uploaded contents, and full browser storage.

## Development workflow

Use test-driven development for behavior changes:

1. write one focused failing test;
2. run it and confirm the intended failure;
3. implement the smallest change;
4. run the focused test;
5. run the complete suite;
6. refactor only while green.

Do not delete regression tests simply because a ChatGPT UI change makes them inconvenient; update selectors/fixtures while preserving the behavior being protected.

## Verification

Before committing or merging, run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q chatgpt_browser.py chatgpt_browser_cli tests
python chatgpt_browser.py --help
```

All commands must exit successfully. Browser integration tests may skip only when Chromium/Chrome is genuinely absent.

## Pull requests and merges

- Work on a feature branch, not directly on `main`.
- Keep compatibility with `python chatgpt_browser.py ...` unless a breaking change is explicitly approved.
- Include tests for every new behavior or bug fix.
- Do not merge with failing CI.
- Re-run the full verification commands on the exact tree being merged.
