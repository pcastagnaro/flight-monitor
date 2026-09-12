"""Shared console logging for API and scheduled jobs."""
import logging
import os
from logging.config import dictConfig


def configure_logging():
    level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"standard": {
            "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
        }},
        "handlers": {"console": {
            "class": "logging.StreamHandler", "stream": "ext://sys.stdout",
            "formatter": "standard", "level": level,
        }},
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            "uvicorn": {"handlers": [], "propagate": True, "level": level},
            "uvicorn.error": {"handlers": [], "propagate": True, "level": level},
            "uvicorn.access": {"handlers": [], "propagate": True, "level": level},
            # HTTP debug/info output can expose API keys in URLs and headers.
            "httpx": {"handlers": [], "propagate": True, "level": "WARNING"},
            "httpcore": {"handlers": [], "propagate": True, "level": "WARNING"},
        },
    })
