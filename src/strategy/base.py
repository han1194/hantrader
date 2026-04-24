from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

import pandas as pd

if TYPE_CHECKING:
    from src.utils.log_manager import HanLogger


class SignalType(Enum):
    """시그널 종류."""
    LONG_ENTRY = "long_entry"
    SHORT_ENTRY = "short_entry"
    LONG_EXIT = "long_exit"
    SHORT_EXIT = "short_exit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class MarketRegime(Enum):
    """시장 국면."""
    SIDEWAYS = "sideways"       # 횡보장
    TREND_UP = "trend_up"       # 상승 추세
    TREND_DOWN = "trend_down"   # 하락 추세


@dataclass
class Signal:
    """트레이딩 시그널."""
    timestamp: pd.Timestamp
    signal_type: SignalType
    price: float
    leverage: int = 50
    position_ratio: float = 1.0   # 진입 비율 (0.0 ~ 1.0)
    entry_step: int = 0           # 물타기 단계 (1~5)
    stop_loss_ratio: float = 0.0  # 손절 비율 (0.0 ~ 1.0)
    reason: str = ""
    metadata: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    """전략 베이스 클래스.

    모든 커스텀 전략은 이 클래스를 상속하여 구현한다.
    """

    def __init__(self, name: str, timeframe: str = "1h"):
        self.name = name
        self.timeframe = timeframe
        # 거래소/심볼/모드 바인딩된 로거 (선택). 주입 시 전략 내부 로그가
        # {exchange}/{symbol}/{날짜}/{mode}/{category}.log 경로로 라우팅된다.
        self._log_ctx: Optional["HanLogger"] = None

    def set_log_context(self, log: "HanLogger") -> None:
        """거래소/심볼/모드 바인딩된 HanLogger 를 주입한다.

        전략은 일반적으로 exchange-agnostic 하지만, 생성 후 엔진이 자신의
        `self.log` 를 이 메서드로 넘겨주면 전략 내부 로그를 signal.log 등
        카테고리 파일로 분리 기록할 수 있다.
        """
        self._log_ctx = log

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """OHLCV + 지표 DataFrame으로부터 시그널을 생성한다."""
        ...

    @abstractmethod
    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """각 캔들에 대한 시장 국면(횡보/추세)을 판단한다."""
        ...
