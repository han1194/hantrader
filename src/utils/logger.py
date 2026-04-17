"""HanTrader 로거 설정.

LogManager 기반으로 로거를 생성한다.
setup_logger()는 하위 호환용 — 새 코드는 LogManager.bind()를 직접 사용한다.
"""

from src.utils.log_manager import (
    LogManager,
    LogCategory,
    HanLogger,
    _KSTFormatter as KSTFormatter,
    KST,
)

__all__ = ["setup_logger", "LogManager", "LogCategory", "HanLogger", "KSTFormatter", "KST"]


def setup_logger(
    name: str = "hantrader",
    level: str = "INFO",
    log_file: str | None = None,
) -> HanLogger:
    """로거를 초기화하고 반환한다.

    하위 호환용. 새 코드는 LogManager.instance().bind()를 사용한다.
    반환되는 HanLogger는 info(), warning(), error(), debug() 메서드를 지원한다.
    """
    mgr = LogManager.instance()
    if not mgr._initialized:
        mgr.init(level=level)
    return mgr.bind()
