"""统一日志系统模块
基于 loguru 实现静默文件落盘、大小与时间自动轮转，杜绝污染终端 TUI。
"""

import sys
from pathlib import Path
from typing import Optional
from loguru import logger

from src.config import get_default_data_dir


_LOG_INITIALIZED = False


def get_log_dir() -> Path:
    """获取日志存储目录 ~/.local/share/cf-coach/logs/。"""
    log_dir = get_default_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def init_logger(debug: bool = False, log_to_console: bool = False):
    """初始化全局日志配置。

    参数:
        debug: 是否开启 DEBUG 级别追踪。
        log_to_console: 是否将日志镜像输出到终端控制台 (默认 False，避免打乱 TUI)。
    """
    global _LOG_INITIALIZED
    if _LOG_INITIALIZED:
        return logger

    # 1. 移除 loguru 默认的控制台输出 sink
    logger.remove()

    log_level = "DEBUG" if debug else "INFO"
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level:<8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    # 2. 如果开启控制台镜像 (如通过 --debug 诊断时可选择)
    if log_to_console:
        logger.add(
            sys.stderr,
            level=log_level,
            format=log_format,
            colorize=True,
            backtrace=debug,
            diagnose=debug
        )

    # 3. 配置文件落盘 Sink (按 10MB 切割，保留 7 天，自动压缩)
    log_file = get_log_dir() / "cf_coach.log"
    logger.add(
        str(log_file),
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,         # 异步安全队列写入
        backtrace=True,       # 记录详细调用栈
        diagnose=debug        # debug 模式下记录变量快照
    )

    _LOG_INITIALIZED = True
    logger.info("=" * 60)
    logger.info("CF-Coach-CLI 日志系统初始化完成 (Level: {})", log_level)
    logger.info("日志落盘路径: {}", log_file)
    logger.info("=" * 60)
    return logger


# 默认先以静默模式初始化一次，保证任意模块直接 import logger 即可安全使用
init_logger(debug=False, log_to_console=False)

__all__ = ["logger", "init_logger", "get_log_dir"]
