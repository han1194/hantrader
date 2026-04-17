"""Bollinger Bands V2 전략.

BB전략에서 2가지를 개선한다:
1. BBW 최소 기준: 횡보 반전매매 시 밴드가 너무 좁으면 진입 차단
   - BBW < min_bbw_for_sideways → 돌파 가능성 높아 반전매매 위험
2. 추세 물타기 최소 간격: 연속 진입 방지
   - 이전 진입 후 min_entry_interval 캔들이 지나야 추가 진입 가능
   - 가격이 실제로 추세 방향으로 진행하는지 확인 후 물타기

기존 BBStrategy는 그대로 유지하며, 이 클래스가 상속하여 확장한다.
"""

import pandas as pd

from src.utils.logger import setup_logger
from .base import Signal, SignalType, MarketRegime
from .bb_strategy import BBStrategy, SHORT_ENTRY_LEVELS, LONG_ENTRY_LEVELS  
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb_v2")


@register_strategy("bb_v2")
class BBV2Strategy(BBStrategy):
    """BB V2 전략: BBW 필터 + 물타기 간격 제한.

    BBStrategy를 상속하여 _sideways_signals, _trend_signals만 오버라이드한다.
    """

    def __init__(
        self,
        min_bbw_for_sideways: float = 1.0,
        min_entry_interval: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V2_Strategy"
        self.min_bbw_for_sideways = min_bbw_for_sideways
        self.min_entry_interval = min_entry_interval

        # 추세 물타기 마지막 진입 캔들 인덱스 추적
        self._last_entry_idx: int = -999

        logger.info(
            f"BB V2 전략 초기화: min_bbw_sideways={self.min_bbw_for_sideways}, "
            f"min_entry_interval={self.min_entry_interval}"
        )

    # ------------------------------------------------------------------
    # 시그널 생성 (물타기 간격 추적을 위해 오버라이드)
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """OHLCV DataFrame에서 트레이딩 시그널을 생성한다."""
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

        for i in range(len(indicators)):
            row = indicators.iloc[i]
            ts = indicators.index[i]
            price = row["close"]
            bbp = row["bb_pct"]
            bb_width = row["bb_width"]
            regime = row["regime"]
            leverage = self.calc_leverage(bb_width)

            if long_step > 0:
                peak_price = max(peak_price, price)
            if short_step > 0:
                trough_price = min(trough_price, price)

            if regime == MarketRegime.SIDEWAYS:
                leverage = min(leverage, self.sideways_leverage_max)
                adx_val = row["adx"]
                adx_rising = bool(row["adx_rising"])
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
                # 진입 시 마지막 진입 캔들 기록
                if sig.signal_type in (SignalType.LONG_ENTRY, SignalType.SHORT_ENTRY):
                    self._last_entry_idx = i
                if long_step == 0 and short_step == 0:
                    peak_price = 0.0
                    trough_price = float("inf")
                    self._last_entry_idx = -999

        logger.info(f"시그널 생성 완료: {len(signals)}건")
        return signals

    # ------------------------------------------------------------------
    # 횡보장 반전매매 (BBW 필터 추가)
    # ------------------------------------------------------------------

    def _sideways_signals_v2(
        self,
        ts: pd.Timestamp,
        price: float,
        bbp: float,
        bb_width: float,
        leverage: int,
        long_step: int,
        short_step: int,
        entry_price: float,
        adx: float = 0.0,
        adx_rising: bool = False,
    ) -> list[Signal]:
        """횡보장 반전매매 — BBW 필터 추가.

        기존 포지션의 청산/손절/물타기는 BBW와 무관하게 정상 처리한다.
        BBW 필터는 **신규 진입**에만 적용한다.
        """
        has_position = long_step > 0 or short_step > 0

        # 기존 포지션 관리는 부모 클래스에 위임
        if has_position:
            return self._sideways_signals(
                ts, price, bbp, leverage, long_step, short_step, entry_price,
                adx=adx, adx_rising=adx_rising,
            )

        # === 신규 진입: BBW 필터 적용 ===
        if bb_width < self.min_bbw_for_sideways:
            logger.debug(
                f"[횡보V2] 신규진입 차단: BBW={bb_width:.4f} < "
                f"최소기준={self.min_bbw_for_sideways} (밴드 너무 좁음)"
            )
            return []

        # BBW 통과 → 부모 클래스 로직 사용
        return self._sideways_signals(
            ts, price, bbp, leverage, long_step, short_step, entry_price,
            adx=adx, adx_rising=adx_rising,
        )

    # ------------------------------------------------------------------
    # 추세장 추세추종 (물타기 간격 제한 추가)
    # ------------------------------------------------------------------

    def _trend_signals_v2(
        self,
        ts: pd.Timestamp,
        price: float,
        bbp: float,
        bb_width: float,
        leverage: int,
        regime: MarketRegime,
        row: pd.Series,
        long_step: int,
        short_step: int,
        entry_price: float,
        peak_price: float = 0.0,
        trough_price: float = float("inf"),
        candle_idx: int = 0,
    ) -> list[Signal]:
        """추세장 추세추종 — 물타기 간격 제한 추가.

        이미 포지션이 있는 상태에서 추가 진입(물타기)할 때만 간격 제한을 적용한다.
        1차 진입과 청산/손절/익절은 간격 제한 없이 즉시 처리한다.
        """
        has_position = long_step > 0 or short_step > 0

        # 물타기 간격 제한 체크
        if has_position:
            candles_since_entry = candle_idx - self._last_entry_idx
            if candles_since_entry < self.min_entry_interval:
                # 간격 부족 → 청산/손절만 처리, 물타기 차단
                # 부모에서 손절/익절/트레일링 로직만 타도록 step을 3으로 속여서 전달
                # (step >= 3이면 부모가 손절/익절만 처리함)
                if long_step > 0 and long_step < 3:
                    logger.debug(
                        f"[추세V2] Long 물타기 대기: {candles_since_entry}/{self.min_entry_interval}캔들 경과"
                    )
                    # 손절/트레일링만 체크하기 위해 step=3으로 전달
                    return self._trend_signals(
                        ts, price, bbp, bb_width, leverage, regime, row,
                        3, short_step, entry_price,
                        peak_price=peak_price, trough_price=trough_price,
                    )
                if short_step > 0 and short_step < 3:
                    logger.debug(
                        f"[추세V2] Short 물타기 대기: {candles_since_entry}/{self.min_entry_interval}캔들 경과"
                    )
                    return self._trend_signals(
                        ts, price, bbp, bb_width, leverage, regime, row,
                        long_step, 3, entry_price,
                        peak_price=peak_price, trough_price=trough_price,
                    )

        # 간격 충분하거나 신규 진입 → 부모 클래스 로직 사용
        return self._trend_signals(
            ts, price, bbp, bb_width, leverage, regime, row,
            long_step, short_step, entry_price,
            peak_price=peak_price, trough_price=trough_price,
        )
