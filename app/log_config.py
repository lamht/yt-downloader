# log_config.py
import logging
import sys

class FlushStreamHandler(logging.StreamHandler):
    """StreamHandler mà flush ngay sau mỗi emit"""
    def emit(self, record):
        super().emit(record)
        self.flush()

def setup_logger(name: str, level=logging.INFO) -> logging.Logger:
    """
    Tạo logger với FlushStreamHandler, dùng chung cho toàn app.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.hasHandlers():
        ch = FlushStreamHandler(sys.stdout)
        formatter = logging.Formatter('[%(name)s] %(levelname)s: %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger