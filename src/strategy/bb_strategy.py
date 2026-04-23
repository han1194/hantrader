"""하위 호환 shim. 실제 구현은 src/strategy/bb/strategy.py 로 이동했다.

외부 코드에서 `from src.strategy.bb_strategy import BBStrategy` 같은 경로를
계속 쓸 수 있도록 심볼을 재노출한다.
"""

from .bb.strategy import (  # noqa: F401
    BBStrategy,
    LONG_ENTRY_LEVELS,
    SHORT_ENTRY_LEVELS,
    LONG_STOP_LEVELS,
    SHORT_STOP_LEVELS,
)

__all__ = [
    "BBStrategy",
    "LONG_ENTRY_LEVELS",
    "SHORT_ENTRY_LEVELS",
    "LONG_STOP_LEVELS",
    "SHORT_STOP_LEVELS",
]
