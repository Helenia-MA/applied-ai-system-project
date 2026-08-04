"""Tests for logging configuration (logging_setup.py).

The interesting case is idempotency. Streamlit re-executes app.py on every
interaction, so setup_logging() runs again on every click — and if each call
attached a fresh pair of handlers, log lines would be duplicated once per click.
That's the bug these tests exist to prevent.

Every test writes to tmp_path, so running the suite never creates a real logs/
directory, and the fixture restores global logging state afterwards.
"""

import logging
import logging.handlers

import pytest

import logging_setup
from logging_setup import resolve_level, setup_logging


@pytest.fixture(autouse=True)
def isolate_logging():
    """Save and restore global logging state around every test.

    Logging config is process-wide, so without this a test would leak handlers
    and level changes into whatever ran next.
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_third_party = {
        name: logging.getLogger(name).level
        for name in logging_setup.NOISY_THIRD_PARTY
    }

    yield

    logging_setup.reset_logging()
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved_third_party.items():
        logging.getLogger(name).setLevel(level)


def our_handlers():
    """The handlers logging_setup owns, ignoring pytest's own.

    File logging is attached to the project loggers, while the console handler
    stays on root. De-duplicate by identity because the same rotating handler is
    shared across multiple project loggers.
    """
    seen: dict[int, logging.Handler] = {}
    loggers = [logging.getLogger()]
    loggers.extend(logging.getLogger(name) for name in logging_setup._FILE_LOGGER_NAMES)
    for logger in loggers:
        for handler in logger.handlers:
            if getattr(handler, "_pawpal", None) == logging_setup._HANDLER_TAG:
                seen[id(handler)] = handler
    return list(seen.values())


# --- Feature: handlers are attached ---------------------------------------

def test_setup_attaches_a_console_and_a_file_handler(tmp_path):
    """Console for the person running it, shared file handler for the audit trail."""
    path = setup_logging("INFO", tmp_path / "pawpal.log", force=True)

    handlers = our_handlers()
    assert len(handlers) == 2
    assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in handlers)
    assert path == tmp_path / "pawpal.log"


def test_log_records_reach_the_file(tmp_path):
    """The point of the file handler: messages actually land on disk."""
    log_file = tmp_path / "pawpal.log"
    setup_logging("INFO", log_file, force=True)

    logging.getLogger("retrieval").info("Retrieved 3 chunks for Biscuit")
    for handler in our_handlers():
        handler.flush()

    assert "Retrieved 3 chunks for Biscuit" in log_file.read_text()


def test_the_file_handler_rotates(tmp_path):
    """Bounded so an unattended app can't fill a disk."""
    setup_logging("INFO", tmp_path / "pawpal.log", force=True)

    handler = next(h for h in our_handlers()
                   if isinstance(h, logging.handlers.RotatingFileHandler))

    assert handler.maxBytes == logging_setup.MAX_BYTES
    assert handler.backupCount == logging_setup.BACKUP_COUNT


# --- Feature: idempotency across Streamlit reruns -------------------------

def test_repeated_setup_does_not_stack_handlers(tmp_path):
    """The Streamlit rerun case: ten calls must not mean ten copies of each line."""
    log_file = tmp_path / "pawpal.log"
    setup_logging("INFO", log_file, force=True)

    for _ in range(10):
        setup_logging("INFO", log_file)

    assert len(our_handlers()) == 2


def test_repeated_setup_does_not_duplicate_log_lines(tmp_path):
    """The observable symptom the guard prevents."""
    log_file = tmp_path / "pawpal.log"
    setup_logging("INFO", log_file, force=True)
    for _ in range(5):
        setup_logging("INFO", log_file)

    logging.getLogger("advisor").info("unique-marker")
    for handler in our_handlers():
        handler.flush()

    assert log_file.read_text().count("unique-marker") == 1


def test_force_replaces_handlers_rather_than_adding_to_them(tmp_path):
    """Reconfiguring swaps our handlers out; it doesn't accumulate them."""
    setup_logging("INFO", tmp_path / "one.log", force=True)
    setup_logging("DEBUG", tmp_path / "two.log", force=True)

    assert len(our_handlers()) == 2
    assert logging_setup._current_log_path() == tmp_path / "two.log"


# --- Feature: level resolution --------------------------------------------

def test_level_comes_from_the_environment(tmp_path, monkeypatch):
    """PAWPAL_LOG_LEVEL is the documented knob, so it has to be honoured."""
    monkeypatch.setenv("PAWPAL_LOG_LEVEL", "WARNING")

    setup_logging(log_file=tmp_path / "pawpal.log", force=True)

    assert logging.getLogger().level == logging.WARNING


def test_an_explicit_level_beats_the_environment(tmp_path, monkeypatch):
    """Callers that pass a level mean it — smoke_check always wants INFO."""
    monkeypatch.setenv("PAWPAL_LOG_LEVEL", "ERROR")

    setup_logging("DEBUG", tmp_path / "pawpal.log", force=True)

    assert logging.getLogger().level == logging.DEBUG


def test_a_bad_level_falls_back_instead_of_raising(monkeypatch):
    """A typo in an env var shouldn't stop the app from starting."""
    monkeypatch.setenv("PAWPAL_LOG_LEVEL", "VERBOSE-ISH")

    assert resolve_level() == logging.INFO


@pytest.mark.parametrize("given,expected", [
    ("debug", logging.DEBUG),
    ("Info", logging.INFO),
    (" warning ", logging.WARNING),
    (logging.ERROR, logging.ERROR),
])
def test_levels_are_accepted_in_several_forms(given, expected):
    """Names are case- and whitespace-insensitive; numbers pass through."""
    assert resolve_level(given) == expected


# --- Feature: third-party noise is quieted --------------------------------

def test_library_chatter_is_quieted_by_default(tmp_path):
    """httpx logs a line per request and the Gemini SDK logs internals at INFO.

    At default level those bury the lines that matter — which chunks were
    retrieved, which suggestions were rejected — so they're pinned to WARNING.
    """
    setup_logging("INFO", tmp_path / "pawpal.log", force=True)

    for name in logging_setup.NOISY_THIRD_PARTY:
        assert logging.getLogger(name).level == logging.WARNING


def test_debug_level_lets_library_logs_through(tmp_path):
    """If you asked for DEBUG you probably do want to see the HTTP traffic."""
    setup_logging("DEBUG", tmp_path / "pawpal.log", force=True)

    assert logging.getLogger("httpx").level == logging.INFO


# --- Feature: file logging failure degrades ------------------------------

def test_an_unwritable_path_leaves_console_logging_working(tmp_path):
    """A read-only checkout shouldn't stop the app — it just loses the file."""
    # A file where a directory needs to be, so mkdir/open must fail.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    path = setup_logging("INFO", blocker / "nested" / "pawpal.log", force=True)

    assert path is None                     # no file, and the caller can tell
    assert len(our_handlers()) == 1         # console handler still attached
    logging.getLogger("advisor").info("still logging")  # must not raise
