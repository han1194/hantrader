"""Bollinger Bands V5 전략.

BB V2를 상속하여 국면 판단에 **hysteresis(관성)** 를 추가한다.

문제:
  기존 detect_regime()은 1캔들만 조건을 만족해도 즉시 전환됨.
  하락 추세의 일시 정지(ADX 약화, BBW 축소, 되돌림)를 "횡보 시작"으로 오인.
  예) 04-18 17~19:00 ADX 27→25→24.7 턱걸이 하락 + BBW 축소로 sideways 판정되며
      이후 역추세 long 진입 → 대손절.

해결 (A):
  trend → sideways 전환은 **hysteresis_candles 캔들 연속** sideways 조건이 만족될 때만 허용.
  즉 추세가 시작되면 N캔들 이상 명확히 꺾이기 전까지는 추세 유지.
  sideways → trend 전환은 즉시 허용 (추세 시작은 놓치지 않음).
  반대 추세로의 직접 전환(trend_up→trend_down)도 즉시 허용 (강한 반전 신호).

기존 BB V2의 BBW/물타기 간격 필터, 기존 횡보/추세 시그널 로직은 그대로 유지.
detect_regime만 오버라이드한다.
"""

import pandas as pd

from src.utils.logger import setup_logger
from .base import MarketRegime
from .bb_v2_strategy import BBV2Strategy
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb_v5")


@register_strategy("bb_v5")
class BBV5Strategy(BBV2Strategy):
    """BB V5 전략: Regime Hysteresis.

    BBV2Strategy를 상속하여 detect_regime만 오버라이드한다.
    """

    def __init__(
        self,
        hysteresis_candles: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V5_Strategy"
        self.hysteresis_candles = hysteresis_candles

        logger.info(
            f"BB V5 전략 초기화: hysteresis_candles={self.hysteresis_candles}, "
            f"min_bbw={self.min_bbw_for_sideways}, "
            f"min_interval={self.min_entry_interval}"
        )

    # ------------------------------------------------------------------
    # 국면 판단 (hysteresis 보강)
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """Raw 국면에 hysteresis를 적용한 최종 국면 Series를 반환한다.

        규칙:
          - 초기 상태: SIDEWAYS
          - SIDEWAYS → TREND_*: 즉시 전환 (추세 시작 즉시 포착)
          - TREND_* → SIDEWAYS: raw가 N캔들 연속 SIDEWAYS일 때만 전환
          - TREND_UP ↔ TREND_DOWN: 즉시 전환 (강한 반전 신호)
        """
        # 부모(BBStrategy)의 raw 국면 계산
        raw = BBV2Strategy.detect_regime(self, df)

        final = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        current = MarketRegime.SIDEWAYS
        sideways_streak = 0
        filtered_count = 0  # hysteresis로 전환이 억제된 캔들 수

        for i in range(len(raw)):
            r = raw.iloc[i]

            if current == MarketRegime.SIDEWAYS:
                # 횡보 상태: raw 그대로 반영 (추세 시작은 즉시 포착)
                current = r
                sideways_streak = sideways_streak + 1 if r == MarketRegime.SIDEWAYS else 0

            else:
                # 추세 상태
                if r == current:
                    # 동일 추세 유지
                    sideways_streak = 0
                elif r == MarketRegime.SIDEWAYS:
                    # 추세 → 횡보 후보: hysteresis 적용
                    sideways_streak += 1
                    if sideways_streak >= self.hysteresis_candles:
                        current = MarketRegime.SIDEWAYS
                    else:
                        # 아직 캔들 수 부족 → 추세 유지
                        filtered_count += 1
                else:
                    # 반대 추세로 직접 전환 (강한 반전)
                    current = r
                    sideways_streak = 0

            final.iloc[i] = current

        # 필터링 통계
        raw_trend = (raw != MarketRegime.SIDEWAYS).sum()
        final_trend = (final != MarketRegime.SIDEWAYS).sum()
        logger.info(
            f"Hysteresis 적용: raw 추세={raw_trend}캔들 → 최종 추세={final_trend}캔들 "
            f"(hysteresis로 유지 {filtered_count}캔들)"
        )

        return final
