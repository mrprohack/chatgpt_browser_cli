# chatgpt_browser_cli Agent Guide

## Purpose

This project is a Python + Playwright CLI that submits one task to the live ChatGPT website, observes execution, verifies the terminal state, and returns the result.

Core workflow: **Submit -> Observe -> Verify -> Return.**

## Project structure

- `chatgpt_browser.py` - backward-compatible command entry point.
- `chatgpt_browser_cli/models.py` - statuses, error codes, and result data structures.
- `chatgpt_browser_cli/auth.py` - browser-session input normalization.
- `chatgpt_browser_cli/logging_utils.py` - lifecycle logging setup.
- `chatgpt_browser_cli/runner.py` - Playwright lifecycle, UI inspection, submission, and monitoring.
- `chatgpt_browser_cli/cli.py` - argument parsing, mode resolution, formatting, and exit codes.
- `tests/` - unit and local browser regression tests.
- `.github/workflows/ci.yml` - automated checks.

## Browser modes

The default mode is headed. Support explicit `--headed` and `--headless` flags. When neither flag is supplied, `CHATGPT_BROWSER_HEADLESS` may select headless mode.

Keep persistent-profile behavior and preserve the existing `python chatgpt_browser.py ...` command interface.

## Completion rules

Return `COMPLETED` only when a new assistant response exists, generation is idle, and the final text remains stable for the configured number of observations.

Return `STOPPED` for interrupted or timed-out runs with partial output. Return `FAILED` for unrecoverable browser or UI errors. Return `NEEDS USER ACTION` when continuing requires interaction outside normal automation.

A stale `Continue generating` control alone must not mark a run as stopped unless a new assistant response exists.

## Error handling and logging

Use `RunResult` plus typed `ErrorCode` values. Important operations must return a meaningful result instead of silently swallowing failures.

Log operational lifecycle metadata only. Keep output concise and deterministic enough for tests and automation.

## Development rules

Use test-driven development for behavior changes:

1. add a focused failing regression test;
2. confirm the expected failure;
3. implement the smallest change;
4. rerun the focused test;
5. rerun the full suite;
6. refactor only while green.

Keep modules focused. Browser automation belongs in `runner.py`; CLI presentation belongs in `cli.py`; shared status data belongs in `models.py`.

## Required verification

Before merging, run:

```bash
python -m unittest discover -s tests -v
python -m compileall -q chatgpt_browser.py chatgpt_browser_cli tests
python chatgpt_browser.py --help
```

Do not merge with failing CI. Also read `AGENTS.md` for the repository's extended conventions.
