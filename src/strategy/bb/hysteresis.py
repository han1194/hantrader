"""국면 시리즈에 Hysteresis(관성) 를 적용하는 공통 로직.

V5/V7 전략이 공유하는 전환 규칙:
  - SIDEWAYS → TREND_*: 즉시 전환 (추세 시작은 놓치지 않음)
  - TREND_* → SIDEWAYS: raw가 N캔들 연속 SIDEWAYS일 때만 전환
  - TREND_UP ↔ TREND_DOWN: 즉시 전환 (강한 반전 신호)
"""

import pandas as pd

from ..base import MarketRegime


def apply_regime_hysteresis(
    raw: pd.Series,
    hysteresis_candles: int,
) -> tuple[pd.Series, int]:
    """Raw 국면 시리즈에 hysteresis를 적용한다.

    Returns:
        (final_regime_series, filtered_count)
        filtered_count: 추세→횡보 전환이 hysteresis로 억제된 캔들 수
    """
    final = pd.Series(MarketRegime.SIDEWAYS, index=raw.index)
    current = MarketRegime.SIDEWAYS
    sideways_streak = 0
    filtered_count = 0

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
                if sideways_streak >= hysteresis_candles:
                    current = MarketRegime.SIDEWAYS
                else:
                    # 아직 캔들 수 부족 → 추세 유지
                    filtered_count += 1
            else:
                # 반대 추세로 직접 전환 (강한 반전)
                current = r
                sideways_streak = 0

        final.iloc[i] = current

    return final, filtered_count
