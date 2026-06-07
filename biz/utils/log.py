import logging
import os
from logging.handlers import RotatingFileHandler


# Custom Logger with emoji-prefixed warn/error
class CustomLogger(logging.Logger):
    def warn(self, msg, *args, **kwargs):
        # Prepend ⚠️ to warn messages
        msg_with_emoji = f"⚠️ {msg}"
        super().warning(msg_with_emoji, *args, **kwargs)  # Note: warn is alias for warning

    def error(self, msg, *args, **kwargs):
        # Prepend ❌ to error messages
        msg_with_emoji = f"❌ {msg}"
        super().error(msg_with_emoji, *args, **kwargs)


log_file = os.environ.get("LOG_FILE", "log/app.log")
log_max_bytes = int(os.environ.get("LOG_MAX_BYTES", 10 * 1024 * 1024))  # Default 10 MB
log_backup_count = int(os.environ.get("LOG_BACKUP_COUNT", 5))  # Default 5 backup files
# Set log level
log_level = os.environ.get("LOG_LEVEL", "INFO")
LOG_LEVEL = getattr(logging, log_level.upper(), logging.INFO)

file_handler = RotatingFileHandler(
    filename=log_file,
    mode="a",
    maxBytes=log_max_bytes,
    backupCount=log_backup_count,
    encoding="utf-8",
    delay=False,
)
file_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s"
    )
)
file_handler.setLevel(LOG_LEVEL)

console_handler = logging.StreamHandler()
console_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s"
    )
)
console_handler.setLevel(LOG_LEVEL)


# Use custom Logger class
logger = CustomLogger(__name__)
logger.setLevel(LOG_LEVEL)
logger.addHandler(file_handler)
logger.addHandler(console_handler)
