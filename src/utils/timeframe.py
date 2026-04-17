from datetime import timezone, timedelta

import pandas as pd

# KST 타임존 (UTC+9)
KST = timezone(timedelta(hours=9))

# 타임프레임 -> pandas resample rule 매핑
TIMEFRAME_MAP = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "6h": "6h",
    "8h": "8h",
    "12h": "12h",
    "1d": "1D",
    "1w": "1W",
    "1M": "1ME",
}

# 타임프레임 -> milliseconds
TIMEFRAME_MS = {
    "1m": 1 * 60 * 1000,
    "3m": 3 * 60 * 1000,
    "5m": 5 * 60 * 1000,
    "10m": 10 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
    "8h": 8 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
    "1w": 7 * 24 * 60 * 60 * 1000,
    "1M": 30 * 24 * 60 * 60 * 1000,
}


def resample_ohlcv(df: pd.DataFrame, target_timeframe: str) -> pd.DataFrame:
    """5m OHLCV 데이터를 상위 타임프레임으로 리샘플링한다.

    Args:
        df: datetime index를 가진 OHLCV DataFrame (open, high, low, close, volume)
        target_timeframe: 목표 타임프레임 (예: "15m", "1h", "1d", "1w", "1M")

    Returns:
        리샘플링된 OHLCV DataFrame
    """
    rule = TIMEFRAME_MAP.get(target_timeframe)
    if rule is None:
        raise ValueError(f"지원하지 않는 타임프레임: {target_timeframe}")

    resampled = df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    return resampled
