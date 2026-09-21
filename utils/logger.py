import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Compute project root dynamically (100% relative path resolution)
ROOT_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT_DIR / "logs"
LOG_FILE = LOGS_DIR / "app.log"

_initialized = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures root logger with file rotation and console output."""
    global _initialized
    logger = logging.getLogger("jira_sync")
    if _initialized:
        return logger

    logger.setLevel(logging.DEBUG)

    # Ensure logs/ directory exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Detailed file format with module, function name, line number for AI debugging
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d in %(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Clean console format for interactive CLI
    console_fmt = logging.Formatter(
        "[%(levelname)s] %(message)s"
    )

    # Rotating file handler: 10MB per file, keeps 3 backups
    file_handler = RotatingFileHandler(
        str(LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_fmt)

    # Console stream handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(console_fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    _initialized = True
    return logger


def get_logger(name: str = "jira_sync") -> logging.Logger:
    """Returns a child logger under the configured hierarchy."""
    if not _initialized:
        setup_logging()
    return logging.getLogger(f"jira_sync.{name}")
