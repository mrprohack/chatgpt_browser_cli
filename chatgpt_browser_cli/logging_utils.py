from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TextIO


def configure_logging(
    level: str = "INFO",
    *,
    log_file: Path | None = None,
    stream: TextIO | None = None,
    logger_name: str = "chatgpt_browser_cli",
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    if log_file is not None:
        resolved = log_file.expanduser().resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(resolved, encoding="utf-8")
    else:
        handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(logger.level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    return logger
