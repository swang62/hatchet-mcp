import logging
import os

_log_levels = {
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.FATAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}

level_name = os.getenv("LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    level=_log_levels.get(level_name, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
