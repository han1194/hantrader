import pandas as pd
import ta


class TAWrapper:
    """ta 라이브러리 래퍼 클래스.

    OHLCV DataFrame에 기술적 지표를 추가한다.
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    # --- Trend ---

    def sma(self, period: int = 20, column: str = "close") -> pd.Series:
        return ta.trend.sma_indicator(self.df[column], window=period)

    def ema(self, period: int = 20, column: str = "close") -> pd.Series:
        return ta.trend.ema_indicator(self.df[column], window=period)

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
        macd = ta.trend.MACD(self.df["close"], window_fast=fast, window_slow=slow, window_sign=signal)
        return pd.DataFrame({
            "macd": macd.macd(),
            "macd_signal": macd.macd_signal(),
            "macd_diff": macd.macd_diff(),
        })

    def adx(self, period: int = 14) -> pd.Series:
        return ta.trend.adx(self.df["high"], self.df["low"], self.df["close"], window=period)

    # --- Momentum ---

    def rsi(self, period: int = 14) -> pd.Series:
        return ta.momentum.rsi(self.df["close"], window=period)

    def stochastic(self, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> pd.DataFrame:
        stoch = ta.momentum.StochasticOscillator(
            self.df["high"], self.df["low"], self.df["close"],
            window=period, smooth_window=smooth_k,
        )
        return pd.DataFrame({
            "stoch_k": stoch.stoch(),
            "stoch_d": stoch.stoch_signal(),
        })

    def cci(self, period: int = 20) -> pd.Series:
        return ta.trend.cci(self.df["high"], self.df["low"], self.df["close"], window=period)

    # --- Volatility ---

    def bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        bb = ta.volatility.BollingerBands(self.df["close"], window=period, window_dev=std_dev)
        return pd.DataFrame({
            "bb_upper": bb.bollinger_hband(),
            "bb_middle": bb.bollinger_mavg(),
            "bb_lower": bb.bollinger_lband(),
            "bb_width": bb.bollinger_wband(),
        })

    def atr(self, period: int = 14) -> pd.Series:
        return ta.volatility.average_true_range(
            self.df["high"], self.df["low"], self.df["close"], window=period,
        )

    # --- Volume ---

    def obv(self) -> pd.Series:
        return ta.volume.on_balance_volume(self.df["close"], self.df["volume"])

    def vwap(self) -> pd.Series:
        return ta.volume.volume_weighted_average_price(
            self.df["high"], self.df["low"], self.df["close"], self.df["volume"],
        )

    # --- Utility ---

    def add_all_indicators(self) -> pd.DataFrame:
        """주요 지표를 모두 추가한 DataFrame을 반환한다."""
        result = self.df.copy()
        result["sma_20"] = self.sma(20)
        result["ema_20"] = self.ema(20)
        result["rsi_14"] = self.rsi(14)

        macd_df = self.macd()
        result = pd.concat([result, macd_df], axis=1)

        bb_df = self.bollinger_bands()
        result = pd.concat([result, bb_df], axis=1)

        result["atr_14"] = self.atr(14)
        result["obv"] = self.obv()

        return result
