from loguru import logger
from pathlib import Path

def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), colorize=True)
    logger.add("logs/run.log", rotation="5 MB", retention=10, enqueue=True)
    return logger
