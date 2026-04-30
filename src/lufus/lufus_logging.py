#!/usr/bin/env python3
import logging
import sys
import os
import atexit

LOG_FILE = os.path.join(os.path.expanduser("~"), ".local", "share", "lufus", "lufus.log")

_FMT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_setup_done = False


def setup_logging() -> None:
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    root = logging.getLogger("lufus")
    root.setLevel(logging.DEBUG)

    plain = logging.Formatter(_FMT, _DATEFMT)

    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8", delay=False)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(plain)

    root.addHandler(fh)

    def _crash_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        root.critical(
            "Unhandled exception — process is about to crash",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        fh.flush()

    sys.excepthook = _crash_hook
    atexit.register(fh.flush)
    print(f"[lufus] Log file: {LOG_FILE}", flush=True)
    root.debug("Logging initialised — log file: %s", LOG_FILE)


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    if not name.startswith("lufus"):
        name = f"lufus.{name}"
    return logging.getLogger(name)
