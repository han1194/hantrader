"""Bollinger Bands 전략 서브패키지.

모든 BB 계열 전략 클래스와 상수를 이 패키지에 모은다.
외부에서는 상위 src/strategy/__init__.py 또는 하위 호환 shim(src/strategy/bb_*.py)
을 통해 사용하는 것을 권장한다.
"""

from .strategy import (
    BBStrategy,
    LONG_ENTRY_LEVELS,
    SHORT_ENTRY_LEVELS,
    LONG_STOP_LEVELS,
    SHORT_STOP_LEVELS,
)
from .mtf import BBMTFStrategy, ADJACENT_TF
from .v2 import BBV2Strategy
from .v2_mtf import BBV2MTFStrategy
from .v3 import BBV3Strategy
from .v4 import BBV4Strategy
from .v5 import BBV5Strategy
from .v6 import BBV6Strategy
from .v7 import BBV7Strategy
from .v8 import BBV8Strategy
from .v9 import BBV9Strategy

__all__ = [
    "BBStrategy",
    "BBMTFStrategy",
    "BBV2Strategy",
    "BBV2MTFStrategy",
    "BBV3Strategy",
    "BBV4Strategy",
    "BBV5Strategy",
    "BBV6Strategy",
    "BBV7Strategy",
    "BBV8Strategy",
    "BBV9Strategy",
    "LONG_ENTRY_LEVELS",
    "SHORT_ENTRY_LEVELS",
    "LONG_STOP_LEVELS",
    "SHORT_STOP_LEVELS",
    "ADJACENT_TF",
]
