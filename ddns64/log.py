import logging
import sys
from logging import StreamHandler

from ddns64.config import settings

formatter = logging.Formatter("%(asctime)s : %(levelname)-8s [%(filename)-13s:%(lineno)-3d] %(message)s")


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.logging.level.upper(), "INFO"))

    if not logger.hasHandlers():
        handler = StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
