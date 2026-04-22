"""Bollinger Bands V7 전략.

BB V2를 상속하여 국면 판단을 **가격-밴드 돌파 기반**으로 재설계한다.

문제 (V6까지의 한계):
  - detect_regime이 ADX/EMA/MACD/DI 등 후행 지표 합의에 의존 → 추세 진입/종료 지연.
  - V6의 squeeze 강제 sideways가 "하락 추세 중 일시적 BB 수축"을 횡보로 오판
    (예: 04-18~20 약 46시간 하락을 trend_up 꼬리 + sideways + trend_down + sideways로 4토막).

해결:
  사용자가 차트에서 직접 판단하는 직관을 코드로 옮긴다.

  추세 상승 = (BB 폭 확장) AND (종가가 직전 N봉 최고가 상향 돌파)
  추세 하락 = (BB 폭 확장) AND (종가가 직전 N봉 최저가 하향 돌파)
  횡보     = 그 외

  여기에 V5 방식 hysteresis를 적용:
    - sideways → trend: 즉시 전환 (추세 시작은 놓치지 않음)
    - trend → sideways: hysteresis_candles 캔들 연속 sideways 조건 만족 시에만 전환
    - trend_up ↔ trend_down: 즉시 전환 (강한 반전 신호)

기존 BB V2의 BBW 필터, 물타기 간격, 진입/청산 로직은 그대로 유지.
detect_regime + compute_indicators만 오버라이드.
"""

import pandas as pd

from src.utils.logger import setup_logger
from .base import MarketRegime
from .bb_v2_strategy import BBV2Strategy
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb_v7")


@register_strategy("bb_v7")
class BBV7Strategy(BBV2Strategy):
    """BB V7 전략: 가격-밴드 돌파 + Hysteresis."""

    def __init__(
        self,
        width_lookback: int = 5,
        width_expand_ratio: float = 1.05,
        break_lookback: int = 5,
        break_buffer_pct: float = 0.001,
        hysteresis_candles: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V7_Strategy"
        self.width_lookback = width_lookback
        self.width_expand_ratio = width_expand_ratio
        self.break_lookback = break_lookback
        self.break_buffer_pct = break_buffer_pct
        self.hysteresis_candles = hysteresis_candles

        logger.info(
            f"BB V7 전략 초기화: width_lookback={self.width_lookback}, "
            f"width_expand_ratio={self.width_expand_ratio}, "
            f"break_lookback={self.break_lookback}, "
            f"break_buffer_pct={self.break_buffer_pct}, "
            f"hysteresis_candles={self.hysteresis_candles}"
        )

    # ------------------------------------------------------------------
    # 지표 계산: BB 폭 평균, 직전 고점/저점 컬럼 추가
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기존 지표 + width 평균 + 직전 N봉 close 고점/저점."""
        out = super().compute_indicators(df)

        # 직전 N봉 BB 폭 평균 (현재 캔들 제외 — shift(1))
        out["bb_width_avg_n"] = (
            out["bb_width"].rolling(self.width_lookback).mean().shift(1)
        )

        # 직전 N봉 close 고점/저점 (현재 캔들 제외)
        out["prev_high_n"] = out["close"].rolling(self.break_lookback).max().shift(1)
        out["prev_low_n"] = out["close"].rolling(self.break_lookback).min().shift(1)

        return out.dropna()

    # ------------------------------------------------------------------
    # 국면 판단: width 확장 + close 돌파 → hysteresis
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """가격-밴드 돌파 raw 국면에 V5 방식 hysteresis 적용."""
        # === Raw 국면: width 확장 AND 돌파 방향 ===
        width_expanded = df["bb_width"] > df["bb_width_avg_n"] * self.width_expand_ratio
        break_up = df["close"] > df["prev_high_n"] * (1.0 + self.break_buffer_pct)
        break_down = df["close"] < df["prev_low_n"] * (1.0 - self.break_buffer_pct)

        raw = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        raw[width_expanded & break_up] = MarketRegime.TREND_UP
        raw[width_expanded & break_down] = MarketRegime.TREND_DOWN

        # === Hysteresis (V5 동일 로직) ===
        final = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        current = MarketRegime.SIDEWAYS
        sideways_streak = 0
        filtered_count = 0

        for i in range(len(raw)):
            r = raw.iloc[i]

            if current == MarketRegime.SIDEWAYS:
                # 횡보 상태: raw 그대로 반영 (추세 시작 즉시 포착)
                current = r
                sideways_streak = sideways_streak + 1 if r == MarketRegime.SIDEWAYS else 0
            else:
                # 추세 상태
                if r == current:
                    sideways_streak = 0
                elif r == MarketRegime.SIDEWAYS:
                    # 추세 → 횡보 후보: hysteresis 적용
                    sideways_streak += 1
                    if sideways_streak >= self.hysteresis_candles:
                        current = MarketRegime.SIDEWAYS
                    else:
                        # 캔들 부족 → 추세 유지
                        filtered_count += 1
                else:
                    # 반대 추세로 직접 전환
                    current = r
                    sideways_streak = 0

            final.iloc[i] = current

        # 통계 로그
        raw_up = (raw == MarketRegime.TREND_UP).sum()
        raw_dn = (raw == MarketRegime.TREND_DOWN).sum()
        final_up = (final == MarketRegime.TREND_UP).sum()
        final_dn = (final == MarketRegime.TREND_DOWN).sum()
        logger.info(
            f"V7 국면: raw(↑{raw_up}/↓{raw_dn}) → final(↑{final_up}/↓{final_dn}) "
            f"hysteresis 유지 {filtered_count}캔들 (총 {len(df)}캔들)"
        )

        return final
