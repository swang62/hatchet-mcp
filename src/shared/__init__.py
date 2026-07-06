import logging
import os

logging.basicConfig(
    level=logging.getLevelNamesMapping().get(
        os.getenv("LOG_LEVEL", "WARNING").upper(), logging.WARNING
    ),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
