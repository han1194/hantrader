"""BB 전략 기본 지표 계산."""

import pandas as pd
import ta


def compute_bb_indicators(
    df: pd.DataFrame,
    bb_period: int,
    bb_std: float,
    adx_rise_lookback: int,
) -> pd.DataFrame:
    """BB/SMA/EMA/MACD/RSI/Volume SMA/ADX 지표를 계산하여 반환한다."""
    out = df.copy()

    # Bollinger Bands
    bb = ta.volatility.BollingerBands(
        out["close"], window=bb_period, window_dev=bb_std,
    )
    out["bb_upper"] = bb.bollinger_hband()
    out["bb_middle"] = bb.bollinger_mavg()
    out["bb_lower"] = bb.bollinger_lband()
    out["bb_width"] = bb.bollinger_wband()
    out["bb_pct"] = bb.bollinger_pband()  # BB%: (close - lower) / (upper - lower)

    # SMA / EMA
    out["sma_20"] = ta.trend.sma_indicator(out["close"], window=20)
    out["ema_12"] = ta.trend.ema_indicator(out["close"], window=12)
    out["ema_26"] = ta.trend.ema_indicator(out["close"], window=26)

    # MACD
    macd = ta.trend.MACD(out["close"], window_fast=12, window_slow=26, window_sign=9)
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_diff"] = macd.macd_diff()

    # RSI
    out["rsi"] = ta.momentum.rsi(out["close"], window=14)

    # Volume SMA (거래량 추세 판단용)
    out["volume_sma"] = ta.trend.sma_indicator(out["volume"], window=20)

    # ADX (추세 강도 + 방향)
    adx_ind = ta.trend.ADXIndicator(out["high"], out["low"], out["close"], window=14)
    out["adx"] = adx_ind.adx()
    out["di_plus"] = adx_ind.adx_pos()
    out["di_minus"] = adx_ind.adx_neg()

    # ADX 상승 여부 (N캔들 전보다 높으면 상승 중)
    out["adx_rising"] = out["adx"] > out["adx"].shift(adx_rise_lookback)

    return out.dropna()
