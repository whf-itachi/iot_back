"""日志系统 — 自动轮转，单文件最大 5MB，最多保留 10 个"""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
LOG_FILE = os.path.join(LOG_DIR, "iot_back.log")

os.makedirs(LOG_DIR, exist_ok=True)

# 根 logger
logger = logging.getLogger("iot_back")
logger.setLevel(logging.DEBUG)

# 文件处理器：5MB 轮转，最多 10 个
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5 * 1024 * 1024,   # 5MB
    backupCount=10,
    encoding="utf-8",
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

# 控制台也输出（开发方便）
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(
    "[%(name)s] %(levelname)s - %(message)s"
))

logger.addHandler(file_handler)
logger.addHandler(console_handler)
