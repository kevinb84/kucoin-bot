import logging
import os
import sys
from datetime import datetime


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return setup_logger(name)


def setup_logger(name: str, log_level: str = 'INFO') -> logging.Logger:
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    if not logger.handlers:
        log_file = os.path.join(log_dir, f'{name}_{datetime.now().strftime("%Y%m%d")}.log')

        # File handler - UTF-8 so emojis save fine
        file_handler = logging.FileHandler(log_file, encoding='utf-8')

        # Console handler - safe encoding for Windows cp1252
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.stream = open(
            sys.stdout.fileno(),
            mode='w',
            encoding='utf-8',
            errors='replace',   # replace unknown chars instead of crashing
            closefd=False,
            buffering=1
        )

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    return logger
