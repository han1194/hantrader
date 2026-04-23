"""BB 전략 기본 국면 판단 (다중 지표 2단계 점수)."""

import pandas as pd

from ..base import MarketRegime


def detect_scored_regime(
    df: pd.DataFrame,
    regime_window: int,
    regime_threshold: float,
) -> pd.Series:
    """다중 지표 2단계 점수로 횡보/추세 국면을 판단한다.

    1단계 - 추세 강도: ADX + BB width 확대 여부
    2단계 - 추세 방향: EMA 배열 + 가격/SMA + MACD + DI+/DI-

    기존 BB width 변화율 단독 판단 대비 빠르고 정확한 국면 전환을 감지한다.
    """
    regime = pd.Series(MarketRegime.SIDEWAYS, index=df.index)

    # === 1단계: 추세 강도 (방향 무관) ===
    strength = pd.Series(0.0, index=df.index)

    adx = df["adx"]
    strength += (adx >= 25).astype(float) * 2.0        # ADX 강추세
    strength += ((adx >= 20) & (adx < 25)).astype(float) * 1.0  # ADX 중추세

    bb_width = df["bb_width"]
    width_ma = bb_width.rolling(regime_window).mean()
    width_change = (bb_width / width_ma) - 1.0
    strength += (width_change > regime_threshold).astype(float) * 1.0

    # === 2단계: 추세 방향 (양수=상승, 음수=하락) ===
    direction = pd.Series(0.0, index=df.index)

    # EMA 배열 (12 vs 26)
    ema_bull = (df["ema_12"] > df["ema_26"]).astype(float)
    ema_bear = (df["ema_12"] < df["ema_26"]).astype(float)
    direction += ema_bull * 1.5 - ema_bear * 1.5

    # 가격 vs SMA 20
    direction += (df["close"] > df["sma_20"]).astype(float) * 1.0
    direction -= (df["close"] < df["sma_20"]).astype(float) * 1.0

    # MACD diff
    direction += (df["macd_diff"] > 0).astype(float) * 1.0
    direction -= (df["macd_diff"] < 0).astype(float) * 1.0

    # DI+ vs DI-
    direction += (df["di_plus"] > df["di_minus"]).astype(float) * 1.0
    direction -= (df["di_plus"] < df["di_minus"]).astype(float) * 1.0

    # === 국면 결정 ===
    # 추세 강도 >= 2.0 이고 방향 합의 >= 2.0 이면 추세
    is_trend = strength >= 2.0
    regime[is_trend & (direction >= 2.0)] = MarketRegime.TREND_UP
    regime[is_trend & (direction <= -2.0)] = MarketRegime.TREND_DOWN

    return regime
