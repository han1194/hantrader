"""Bollinger Bands V8 전략.

BB V2를 상속하여 국면 판단을 **BB 상/중/하단 price 변화** 기반으로 재설계한다.
BBW(폭) 수치가 아니라 세 밴드의 price 값 변화를 직접 조합해서 추세 여부를 판정.

추세 상승 조건 (모두 AND):
  1. bb_upper > 직전 band_avg_lookback 봉 bb_upper 평균 (상단 상승)
  2. close > bb_upper                                     (종가 상단 돌파)
  3. bb_lower < 직전 band_avg_lookback 봉 bb_lower 평균 (하단 하락)
  4. (bb_upper - bb_lower) > 직전봉 (bb_upper - bb_lower) (폭 확장)
  5. bb_middle > 직전봉 bb_middle                        (중단 상승)

그 외에는 모두 SIDEWAYS. 추세 하락은 아직 정의하지 않음.

기존 BB V2의 BBW 필터, 물타기 간격, 진입/청산 로직은 그대로 유지.
detect_regime + compute_indicators만 오버라이드.
"""

import pandas as pd

from src.utils.logger import setup_logger
from ..base import MarketRegime
from ..registry import register_strategy
from .v2 import BBV2Strategy

logger = setup_logger("hantrader.strategy.bb_v8")


@register_strategy("bb_v8")
class BBV8Strategy(BBV2Strategy):
    """BB V8 전략: 세 밴드 price 변화 기반 국면 판단."""

    def __init__(
        self,
        band_avg_lookback: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V8_Strategy"
        self.band_avg_lookback = band_avg_lookback

        logger.info(
            f"BB V8 전략 초기화: band_avg_lookback={self.band_avg_lookback}"
        )

    # ------------------------------------------------------------------
    # 지표 계산: 상/하단 N봉 평균 + 직전 폭/중단 컬럼 추가
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기존 지표 + 밴드별 비교 기준값."""
        out = super().compute_indicators(df)

        # 직전 N봉 상/하단 평균 (현재 캔들 제외 — shift(1))
        out["bb_upper_avg_n"] = (
            out["bb_upper"].rolling(self.band_avg_lookback).mean().shift(1)
        )
        out["bb_lower_avg_n"] = (
            out["bb_lower"].rolling(self.band_avg_lookback).mean().shift(1)
        )

        # 직전 봉 폭 / 중단
        out["bb_width_abs"] = out["bb_upper"] - out["bb_lower"]
        out["bb_width_abs_prev"] = out["bb_width_abs"].shift(1)
        out["bb_middle_prev"] = out["bb_middle"].shift(1)

        return out.dropna()

    # ------------------------------------------------------------------
    # 국면 판단: 다섯 조건 AND → TREND_UP, 그 외 SIDEWAYS
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """상/중/하단 price 변화 조합으로 국면을 판정한다."""
        upper_rising = df["bb_upper"] > df["bb_upper_avg_n"]
        close_breakout = df["close"] > df["bb_upper"]
        lower_falling = df["bb_lower"] < df["bb_lower_avg_n"]
        width_expanding = df["bb_width_abs"] > df["bb_width_abs_prev"]
        middle_rising = df["bb_middle"] > df["bb_middle_prev"]

        trend_up = (
            upper_rising
            & close_breakout
            & lower_falling
            & width_expanding
            & middle_rising
        )

        regime = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        regime[trend_up] = MarketRegime.TREND_UP

        up_count = int(trend_up.sum())
        logger.info(
            f"V8 국면: TREND_UP {up_count} / SIDEWAYS {len(df) - up_count} "
            f"(총 {len(df)}캔들, band_avg_lookback={self.band_avg_lookback})"
        )

        return regime
