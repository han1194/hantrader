"""Bollinger Bands V4 전략.

BB V2를 상속하여 국면 전환 직후 쿨다운을 추가한다.

C. 국면 전환 쿨다운
   - 직전 캔들이 추세(TREND_UP/TREND_DOWN)였다가 현재 캔들이 sideways로 전환된 순간부터
     `cooldown_candles` 캔들 동안 횡보 **신규 진입** 차단.
   - 추세 전환 구간의 애매한 국면에서 BB 극단값이 잡혀 역추세 진입하는 문제 방지.
   - 기존 포지션의 물타기/청산/손절/익절은 영향 없음.

국면 전환 추적을 위해 generate_signals를 오버라이드한다.
로직 자체는 BBV2Strategy와 동일하되, trend→sideways 전환 인덱스를 추적하고
쿨다운 내 신규 진입을 차단하는 부분만 추가된다.
"""

import pandas as pd

from src.utils.logger import setup_logger
from ..base import Signal, SignalType, MarketRegime
from ..registry import register_strategy
from .v2 import BBV2Strategy

logger = setup_logger("hantrader.strategy.bb_v4")


@register_strategy("bb_v4")
class BBV4Strategy(BBV2Strategy):
    """BB V4 전략: 국면 전환 쿨다운.

    BBV2Strategy를 상속하여 generate_signals만 오버라이드한다.
    """

    def __init__(
        self,
        cooldown_candles: int = 5,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V4_Strategy"
        self.cooldown_candles = cooldown_candles

        logger.info(
            f"BB V4 전략 초기화: cooldown_candles={self.cooldown_candles}, "
            f"min_bbw={self.min_bbw_for_sideways}, "
            f"min_interval={self.min_entry_interval}"
        )

    # ------------------------------------------------------------------
    # 시그널 생성 (국면 전환 쿨다운 추적)
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """OHLCV DataFrame에서 트레이딩 시그널을 생성한다.

        BBV2 로직 + trend→sideways 전환 직후 N캔들 횡보 신규진입 차단.
        """
        indicators = self.compute_indicators(df)
        regimes = self.detect_regime(indicators)
        indicators["regime"] = regimes

        signals: list[Signal] = []

        long_step = 0
        short_step = 0
        entry_price = 0.0
        total_weight = 0.0
        peak_price = 0.0
        trough_price = float("inf")
        self._last_entry_idx = -999

        # 국면 전환 추적
        last_trend_exit_idx = -999  # 마지막 trend→sideways 전환 캔들 인덱스
        prev_regime: MarketRegime | None = None

        for i in range(len(indicators)):
            row = indicators.iloc[i]
            ts = indicators.index[i]
            price = row["close"]
            bbp = row["bb_pct"]
            bb_width = row["bb_width"]
            regime = row["regime"]
            leverage = self.calc_leverage(bb_width)

            # 국면 전환 감지: trend → sideways
            if (
                prev_regime is not None
                and prev_regime != MarketRegime.SIDEWAYS
                and regime == MarketRegime.SIDEWAYS
            ):
                last_trend_exit_idx = i
                logger.debug(
                    f"[V4] 국면 전환 감지 @ {ts}: {prev_regime.value} → sideways "
                    f"(쿨다운 {self.cooldown_candles}캔들 시작)"
                )
            prev_regime = regime

            if long_step > 0:
                peak_price = max(peak_price, price)
            if short_step > 0:
                trough_price = min(trough_price, price)

            in_cooldown = (i - last_trend_exit_idx) < self.cooldown_candles

            if regime == MarketRegime.SIDEWAYS:
                leverage = min(leverage, self.sideways_leverage_max)
                adx_val = row["adx"]
                adx_rising = bool(row["adx_rising"])

                has_position = long_step > 0 or short_step > 0
                # 신규 진입인 경우에만 쿨다운 차단
                if in_cooldown and not has_position:
                    logger.debug(
                        f"[V4] {ts} 신규진입 차단: 국면 전환 쿨다운 중 "
                        f"({i - last_trend_exit_idx}/{self.cooldown_candles}캔들)"
                    )
                    sigs: list[Signal] = []
                else:
                    sigs = self._sideways_signals_v2(
                        ts, price, bbp, bb_width, leverage, long_step, short_step,
                        entry_price, adx=adx_val, adx_rising=adx_rising,
                    )
            else:
                sigs = self._trend_signals_v2(
                    ts, price, bbp, bb_width, leverage, regime, row,
                    long_step, short_step, entry_price,
                    peak_price=peak_price, trough_price=trough_price,
                    candle_idx=i,
                )

            meta = {
                "bbp": float(bbp),
                "bb_width": float(bb_width),
                "rsi": float(row["rsi"]),
                "macd_diff": float(row["macd_diff"]),
                "adx": float(row["adx"]),
                "regime": regime.value,
            }
            for sig in sigs:
                sig.metadata = meta
                signals.append(sig)
                long_step, short_step, entry_price, total_weight = self._update_position(
                    sig, long_step, short_step, entry_price, total_weight,
                )
                if sig.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
                    self._last_entry_idx = i
                if long_step == 0 and short_step == 0:
                    peak_price = 0.0
                    trough_price = float("inf")
                    self._last_entry_idx = -999

        logger.info(f"시그널 생성 완료: {len(signals)}건")
        return signals
