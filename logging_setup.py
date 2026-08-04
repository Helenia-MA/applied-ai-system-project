"""Logging configuration for PawPal+.

The modules that do the interesting work (`retrieval`, `advisor`) only ever call
`logging.getLogger(__name__)` — they never configure handlers, which is what lets
them be imported by tests without writing files anywhere. This module is where
the actual wiring lives, and it's called once from each entry point: `app.py`,
`main.py`, and `scripts/smoke_check.py`.

Two things it deliberately handles:

Idempotency. Streamlit re-executes the whole script on every interaction, so
`setup_logging()` gets called again on every click. Without a guard that would
attach a fresh pair of handlers each time, and by the tenth click each log line
would appear ten times in the file.

Third-party noise. The Gemini SDK and httpx both log at INFO — one line per HTTP
request, plus SDK internals. At default level those bury the lines that matter
(which chunks were retrieved, which suggestions were rejected). They're pinned to
WARNING unless the level is DEBUG, on the theory that if you asked for DEBUG you
probably do want to see the HTTP traffic.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

DEFAULT_LOG_DIR = Path(__file__).parent / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "pawpal.log"

DEFAULT_LEVEL = "INFO"

# The file always captures at least INFO, even when the console is quieter.
# Console verbosity is a readability choice — main.py keeps it at WARNING so the
# demo output isn't buried — but the file is the audit trail, and an audit trail
# that's empty because the console was quiet is no audit trail at all.
FILE_LEVEL_FLOOR = logging.INFO

# Libraries that log a line per HTTP request, or otherwise chatter at INFO.
NOISY_THIRD_PARTY = ("httpx", "httpcore", "google_genai", "urllib3")

# Rotate at half a megabyte, keep three old files. Enough to cover a working
# session without letting an unattended app fill a disk.
MAX_BYTES = 512 * 1024
BACKUP_COUNT = 3

# Timestamps and logger names go to the file; the console stays terse, since a
# person watching a CLI demo doesn't need a timestamp on every line.
FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
CONSOLE_FORMAT = "%(levelname)-8s %(name)s: %(message)s"

# Marks handlers this module owns, so a re-run can find and replace exactly its
# own and leave anything pytest or Streamlit attached alone.
_HANDLER_TAG = "pawpal"

# Project loggers that actually emit audit-worthy lines. The file handler is
# attached here so the console can stay quieter without starving the log file.
_FILE_LOGGER_NAMES = ("advisor", "retrieval", "logging_setup", "pawpal_system")

_configured = False


def _owned_loggers() -> list[logging.Logger]:
    """All loggers this module configures, including the root logger."""
    return [logging.getLogger()] + [logging.getLogger(name) for name in _FILE_LOGGER_NAMES]


def resolve_level(level: str | int | None = None) -> int:
    """Turn a level name, number, or None into a logging level.

    Falls back to INFO on anything unrecognised rather than raising — a typo in
    an environment variable shouldn't stop the app from starting.
    """
    if level is None:
        level = os.environ.get("PAWPAL_LOG_LEVEL", DEFAULT_LEVEL)
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(str(level).strip().upper())
    if isinstance(resolved, int):
        return resolved
    logging.getLogger(__name__).warning(
        "Unknown PAWPAL_LOG_LEVEL %r; falling back to %s", level, DEFAULT_LEVEL
    )
    return logging.getLevelName(DEFAULT_LEVEL)


def _remove_our_handlers(root: logging.Logger) -> None:
    """Detach handlers this module previously attached."""
    for handler in list(root.handlers):
        if getattr(handler, "_pawpal", None) == _HANDLER_TAG:
            root.removeHandler(handler)
            handler.close()


def setup_logging(
    level: str | int | None = None,
    log_file: Path | str | None = None,
    *,
    force: bool = False,
) -> Path | None:
    """Attach console and rotating-file handlers. Safe to call repeatedly.

    Returns the path being logged to, or None if file logging couldn't be set up
    (console logging still works in that case). Entry points print the returned
    path so it's obvious where the audit trail went.

    `force=True` reconfigures even if already set up; used by the tests, which
    need to build a fresh configuration per case.
    """
    global _configured
    if _configured and not force:
        return _current_log_path()

    console_level = resolve_level(level)
    file_level = min(console_level, FILE_LEVEL_FLOOR)

    root = logging.getLogger()
    root.setLevel(console_level)
    for logger in _owned_loggers():
        _remove_our_handlers(logger)

    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT))
    console._pawpal = _HANDLER_TAG
    root.addHandler(console)

    path = Path(log_file) if log_file is not None else DEFAULT_LOG_FILE
    written_to: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        file_handler._pawpal = _HANDLER_TAG
        for logger_name in _FILE_LOGGER_NAMES:
            logger = logging.getLogger(logger_name)
            logger.setLevel(file_level)
            logger.addHandler(file_handler)
        written_to = path
    except OSError as error:
        # A read-only checkout or a permissions problem shouldn't stop the app.
        # Console logging is already attached, so the run continues without a file.
        logging.getLogger(__name__).warning(
            "File logging disabled — cannot write to %s: %s", path, error
        )

    # Quiet the libraries unless someone explicitly asked for DEBUG. Set on the
    # logger rather than the handlers, so their chatter stays out of the file too.
    third_party_level = (
        logging.INFO if console_level <= logging.DEBUG else logging.WARNING
    )
    for name in NOISY_THIRD_PARTY:
        logging.getLogger(name).setLevel(third_party_level)

    _configured = True
    return written_to


def _current_log_path() -> Path | None:
    """The file our rotating handler is writing to, if one is attached."""
    for logger in _owned_loggers():
        for handler in logger.handlers:
            if (getattr(handler, "_pawpal", None) == _HANDLER_TAG
                    and isinstance(handler, logging.handlers.RotatingFileHandler)):
                return Path(handler.baseFilename)
    return None


def reset_logging() -> None:
    """Detach our handlers and allow a fresh setup. For tests."""
    global _configured
    for logger in _owned_loggers():
        _remove_our_handlers(logger)
    _configured = False
