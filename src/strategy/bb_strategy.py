"""Bollinger Bands 기반 트레이딩 전략.

횡보장: BB% 기반 반전매매 (물타기 3단계 + 손절, 횡보장 레버리지 제한)
추세장: MACD/RSI/Volume 확인 후 추세추종 또는 반전매매
"""

import numpy as np
import pandas as pd
import ta

from src.utils.logger import setup_logger
from .base import BaseStrategy, Signal, SignalType, MarketRegime
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb")

# === 기본 진입/손절 레벨 ===
LONG_ENTRY_LEVELS = [
    {"bbp": 0.15, "ratio": 0.30, "step": 1},  # 1차 진입
    {"bbp": 0.10, "ratio": 0.30, "step": 2},  # 2차 물타기
    {"bbp": 0.05, "ratio": 0.30, "step": 3},  # 3차 물타기
]

SHORT_ENTRY_LEVELS = [
    {"bbp": 0.85, "ratio": 0.30, "step": 1},  # 1차 진입
    {"bbp": 0.90, "ratio": 0.30, "step": 2},  # 2차 물타기
    {"bbp": 0.95, "ratio": 0.30, "step": 3},  # 3차 물타기
]

LONG_STOP_LEVELS = [
    {"bbp": -0.05, "stop_ratio": 1.00},  # BB 하단 이탈 → 전량 손절
]

SHORT_STOP_LEVELS = [
    {"bbp": 1.05, "stop_ratio": 1.00},  # BB 상단 이탈 → 전량 손절
]


@register_strategy("bb")
class BBStrategy(BaseStrategy):
    """Bollinger Bands 기반 전략.

    Attributes:
        bb_period: BB 기간 (기본 20)
        bb_std: BB 표준편차 (기본 2.0)
        leverage_max: 최대 레버리지 (기본 50)
        leverage_min: 최소 레버리지 (기본 25)
        sideways_leverage_max: 횡보장 레버리지 상한 (기본 15, 강제청산 방지)
        regime_window: 시장 국면 판단용 BB width 이동 윈도우
        regime_threshold: 횡보/추세 판단 임계값 (BB width 변화율)
        stoploss_pct: 물타기 후 손절 기준 (레버리지 적용 전, 기본 2%)
        takeprofit_pct: 추가 매수 후 익절 기준 (레버리지 적용 전, 기본 3%)
    """

    def __init__(
        self,
        timeframe: str = "1h",
        bb_period: int = 20,
        bb_std: float = 2.0,
        leverage_max: int = 50,
        leverage_min: int = 25,
        sideways_leverage_max: int = 15,
        regime_window: int = 20,
        regime_threshold: float = 0.15,
        stoploss_pct: float = 0.02,
        takeprofit_pct: float = 0.03,
        adx_entry_block: float = 20.0,
        adx_rise_lookback: int = 3,
        trailing_start_pct: float = 0.02,
        trailing_stop_pct: float = 0.01,
        long_entry_levels: list[dict] | None = None,
        short_entry_levels: list[dict] | None = None,
        long_stop_levels: list[dict] | None = None,
        short_stop_levels: list[dict] | None = None,
    ):
        super().__init__(name="BB_Strategy", timeframe=timeframe)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.leverage_max = leverage_max
        self.leverage_min = leverage_min
        self.sideways_leverage_max = sideways_leverage_max
        self.regime_window = regime_window
        self.regime_threshold = regime_threshold
        self.stoploss_pct = stoploss_pct
        self.takeprofit_pct = takeprofit_pct
        self.adx_entry_block = adx_entry_block    # 횡보 신규진입 억제 ADX 기준
        self.adx_rise_lookback = adx_rise_lookback  # ADX 상승 판단 캔들 수
        self.trailing_start_pct = trailing_start_pct  # 트레일링 스톱 활성화 기준 PnL
        self.trailing_stop_pct = trailing_stop_pct    # 고점/저점 대비 되돌림 허용폭

        # config에서 오버라이드 가능한 진입/손절 레벨 (모듈 기본값 사용)
        global LONG_ENTRY_LEVELS, SHORT_ENTRY_LEVELS, LONG_STOP_LEVELS, SHORT_STOP_LEVELS
        if long_entry_levels is not None:
            LONG_ENTRY_LEVELS = long_entry_levels
        if short_entry_levels is not None:
            SHORT_ENTRY_LEVELS = short_entry_levels
        if long_stop_levels is not None:
            LONG_STOP_LEVELS = long_stop_levels
        if short_stop_levels is not None:
            SHORT_STOP_LEVELS = short_stop_levels

    # ------------------------------------------------------------------
    # 지표 계산
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """필요한 기술적 지표를 모두 계산하여 DataFrame에 추가한다."""
        out = df.copy()

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(
            out["close"], window=self.bb_period, window_dev=self.bb_std,
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
        out["adx_rising"] = out["adx"] > out["adx"].shift(self.adx_rise_lookback)

        return out.dropna()

    # ------------------------------------------------------------------
    # 시장 국면 판단
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
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
        width_ma = bb_width.rolling(self.regime_window).mean()
        width_change = (bb_width / width_ma) - 1.0
        strength += (width_change > self.regime_threshold).astype(float) * 1.0

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

    # ------------------------------------------------------------------
    # 레버리지 계산
    # ------------------------------------------------------------------

    def calc_leverage(self, bb_width: float, margin_total: float = 1.0) -> int:
        """BB width 크기에 따라 레버리지를 동적으로 조정한다.

        BB width가 클수록 변동성이 높으므로 레버리지를 낮춘다.
        leverage_max ~ leverage_min 사이를 4단계로 균등 분배한다.
        """
        # max ~ min 사이를 4단계로 균등 분배
        step = (self.leverage_max - self.leverage_min) / 3
        leverages = [
            self.leverage_max,
            int(self.leverage_max - step),
            int(self.leverage_max - step * 2),
            self.leverage_min,
        ]

        # BB width를 4단계로 구분
        # 일반적으로 BB width는 0.01 ~ 0.10+ 범위
        thresholds = [0.02, 0.04, 0.06, 0.08]

        for i, threshold in enumerate(thresholds):
            if bb_width < threshold:
                return leverages[i]

        return self.leverage_min

    # ------------------------------------------------------------------
    # 시그널 생성
    # ------------------------------------------------------------------

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        """OHLCV DataFrame에서 트레이딩 시그널을 생성한다."""
        indicators = self.compute_indicators(df)
        regimes = self.detect_regime(indicators)
        indicators["regime"] = regimes

        signals: list[Signal] = []

        # 포지션 상태 추적
        long_step = 0    # 현재 long 물타기 단계
        short_step = 0   # 현재 short 물타기 단계
        entry_price = 0.0
        total_weight = 0.0  # 금액 가중평균용 누적 비중
        peak_price = 0.0   # Long 포지션 고점 (트레일링 스톱용)
        trough_price = float("inf")  # Short 포지션 저점 (트레일링 스톱용)

        for i in range(len(indicators)):
            row = indicators.iloc[i]
            ts = indicators.index[i]
            price = row["close"]
            bbp = row["bb_pct"]
            bb_width = row["bb_width"]
            regime = row["regime"]
            leverage = self.calc_leverage(bb_width)

            # 포지션 고점/저점 갱신 (트레일링 스톱용)
            if long_step > 0:
                peak_price = max(peak_price, price)
            if short_step > 0:
                trough_price = min(trough_price, price)

            if regime == MarketRegime.SIDEWAYS:
                # === 횡보장: 반전매매 (레버리지 제한) ===
                leverage = min(leverage, self.sideways_leverage_max)
                adx_val = row["adx"]
                adx_rising = bool(row["adx_rising"])
                sigs = self._sideways_signals(
                    ts, price, bbp, leverage, long_step, short_step, entry_price,
                    adx=adx_val, adx_rising=adx_rising,
                )
            else:
                # === 추세장: 추세추종 + 반전매매 조합 ===
                sigs = self._trend_signals(
                    ts, price, bbp, bb_width, leverage, regime, row,
                    long_step, short_step, entry_price,
                    peak_price=peak_price, trough_price=trough_price,
                )

            # 모든 시그널에 현재 지표값 metadata 주입
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
                # 포지션 상태 업데이트
                long_step, short_step, entry_price, total_weight = self._update_position(
                    sig, long_step, short_step, entry_price, total_weight,
                )
                # 포지션 청산 시 고점/저점 리셋
                if long_step == 0 and short_step == 0:
                    peak_price = 0.0
                    trough_price = float("inf")

        logger.info(f"시그널 생성 완료: {len(signals)}건")
        return signals

    # ------------------------------------------------------------------
    # 횡보장 반전매매
    # ------------------------------------------------------------------

    def _sideways_signals(
        self,
        ts: pd.Timestamp,
        price: float,
        bbp: float,
        leverage: int,
        long_step: int,
        short_step: int,
        entry_price: float,
        adx: float = 0.0,
        adx_rising: bool = False,
    ) -> list[Signal]:
        """횡보장에서 BB% 기반 반전매매 시그널을 생성한다.

        한 캔들에서는 하나의 방향만 처리한다.
        - 포지션 없음: BB% 위치에 따라 long 또는 short 진입
        - long 보유: 익절(BB상단 65%) 또는 손절만 처리
        - short 보유: 익절(BB하단 35%) 또는 손절만 처리

        ADX >= adx_entry_block 이면서 상승 중이면 추세 전환 임박으로 판단하여
        신규 진입을 억제한다. 기존 포지션의 청산/손절은 정상 처리한다.
        """
        signals: list[Signal] = []
        has_position = long_step > 0 or short_step > 0

        # 추세 전환 임박 여부: ADX가 기준 이상이면서 상승 중
        trend_approaching = adx >= self.adx_entry_block and adx_rising

        logger.debug(
            f"[횡보] {ts} | price={price:,.2f} BB%={bbp:.3f} ADX={adx:.1f} "
            f"ADX상승={adx_rising} 추세임박={trend_approaching} | "
            f"포지션: L{long_step}단계 S{short_step}단계 진입가={entry_price:,.2f}"
        )

        # === Long 포지션 보유 중 ===
        if long_step > 0:
            # 손절 체크 (우선)
            for level in LONG_STOP_LEVELS:
                if bbp <= level["bbp"]:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.STOP_LOSS,
                        price=price,
                        leverage=leverage,
                        stop_loss_ratio=level["stop_ratio"],
                        reason=f"횡보 Long 손절 {int(level['stop_ratio']*100)}% (BB%={bbp:.2f})",
                    ))
                    return signals  # 손절 시 다른 시그널 생성하지 않음

            # BB 상단영역 진입 → 청산 (매도 조건 BB% >= 0.65)
            if bbp >= 0.65:
                pnl_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
                if pnl_pct >= 0:
                    label = f"횡보 Long 익절 BB상단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
                else:
                    label = f"횡보 Long 청산 BB상단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.LONG_EXIT,
                    price=price,
                    leverage=leverage,
                    reason=label,
                ))
                return signals

            # 물타기 (손실 중일 때만, BB 하단 방향으로 더 내려갔을 때)
            # ADX 상승 중이면 추세 전환 임박 → 물타기 억제 (손실 확대 방지)
            if entry_price > 0 and price < entry_price and not trend_approaching:
                for level in LONG_ENTRY_LEVELS:
                    if bbp <= level["bbp"] and long_step < level["step"]:
                        signals.append(Signal(
                            timestamp=ts,
                            signal_type=SignalType.LONG_ENTRY,
                            price=price,
                            leverage=leverage,
                            position_ratio=level["ratio"],
                            entry_step=level["step"],
                            reason=f"횡보 반전매수 {level['step']}차 (BB%={bbp:.2f})",
                        ))
                        break
                else:
                    logger.debug(f"[횡보] Long 물타기 조건 미달: BB%={bbp:.3f} (필요≤{LONG_ENTRY_LEVELS[long_step]['bbp'] if long_step < len(LONG_ENTRY_LEVELS) else 'MAX'})")
            else:
                if trend_approaching:
                    logger.debug(f"[횡보] Long 물타기 억제: ADX 상승 중 (ADX={adx:.1f})")
                elif price >= entry_price:
                    logger.debug(f"[횡보] Long 물타기 스킵: 수익 중 (price={price:,.2f} >= entry={entry_price:,.2f})")
            return signals

        # === Short 포지션 보유 중 ===
        if short_step > 0:
            # 손절 체크 (우선)
            for level in SHORT_STOP_LEVELS:
                if bbp >= level["bbp"]:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.STOP_LOSS,
                        price=price,
                        leverage=leverage,
                        stop_loss_ratio=level["stop_ratio"],
                        reason=f"횡보 Short 손절 {int(level['stop_ratio']*100)}% (BB%={bbp:.2f})",
                    ))
                    return signals

            # BB 하단영역 진입 → 청산 (매수 조건 BB% <= 0.35)
            if bbp <= 0.35:
                pnl_pct = (entry_price - price) / entry_price if entry_price > 0 else 0
                if pnl_pct >= 0:
                    label = f"횡보 Short 익절 BB하단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
                else:
                    label = f"횡보 Short 청산 BB하단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.SHORT_EXIT,
                    price=price,
                    leverage=leverage,
                    reason=label,
                ))
                return signals

            # 물타기 (손실 중일 때만, BB 상단 방향으로 더 올라갔을 때)
            # ADX 상승 중이면 추세 전환 임박 → 물타기 억제 (손실 확대 방지)
            if entry_price > 0 and price > entry_price and not trend_approaching:
                for level in SHORT_ENTRY_LEVELS:
                    if bbp >= level["bbp"] and short_step < level["step"]:
                        signals.append(Signal(
                            timestamp=ts,
                            signal_type=SignalType.SHORT_ENTRY,
                            price=price,
                            leverage=leverage,
                            position_ratio=level["ratio"],
                            entry_step=level["step"],
                            reason=f"횡보 반전매도 {level['step']}차 (BB%={bbp:.2f})",
                        ))
                        break
                else:
                    logger.debug(f"[횡보] Short 물타기 조건 미달: BB%={bbp:.3f} (필요≥{SHORT_ENTRY_LEVELS[short_step]['bbp'] if short_step < len(SHORT_ENTRY_LEVELS) else 'MAX'})")
            else:
                if trend_approaching:
                    logger.debug(f"[횡보] Short 물타기 억제: ADX 상승 중 (ADX={adx:.1f})")
                elif price <= entry_price:
                    logger.debug(f"[횡보] Short 물타기 스킵: 수익 중 (price={price:,.2f} <= entry={entry_price:,.2f})")
            return signals

        # === 포지션 없음: 신규 진입 ===
        # ADX 상승 중이면 추세 전환 임박 → 신규 진입 억제 (관망)
        if trend_approaching:
            logger.debug(f"[횡보] 신규진입 억제: ADX 상승 중 (ADX={adx:.1f}, 기준={self.adx_entry_block})")
            return signals

        # BB 하단 → Long 진입
        for level in LONG_ENTRY_LEVELS:
            if bbp <= level["bbp"]:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.LONG_ENTRY,
                    price=price,
                    leverage=leverage,
                    position_ratio=level["ratio"],
                    entry_step=level["step"],
                    reason=f"횡보 반전매수 {level['step']}차 (BB%={bbp:.2f})",
                ))
                return signals  # 한 방향만

        # BB 상단 → Short 진입
        for level in SHORT_ENTRY_LEVELS:
            if bbp >= level["bbp"]:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.SHORT_ENTRY,
                    price=price,
                    leverage=leverage,
                    position_ratio=level["ratio"],
                    entry_step=level["step"],
                    reason=f"횡보 반전매도 {level['step']}차 (BB%={bbp:.2f})",
                ))
                return signals

        # 조건 미달 → 관망
        logger.debug(
            f"[횡보] 신규진입 조건 미달 — 관망: BB%={bbp:.3f} "
            f"(Long≤{LONG_ENTRY_LEVELS[0]['bbp']}, Short≥{SHORT_ENTRY_LEVELS[0]['bbp']})"
        )
        return signals

    # ------------------------------------------------------------------
    # 추세장 추세추종
    # ------------------------------------------------------------------

    def _trend_signals(
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
    ) -> list[Signal]:
        """추세장에서 추세추종/반전매매 시그널을 생성한다.

        현재 포지션 방향과 충돌하는 시그널은 생성하지 않는다.
        트레일링 스톱: PnL이 trailing_start_pct 이상이면 활성화,
        고점/저점 대비 trailing_stop_pct 되돌리면 익절 청산.
        """
        signals: list[Signal] = []

        is_uptrend = regime == MarketRegime.TREND_UP
        trend_confirmed = self._confirm_trend(row, is_uptrend)

        logger.debug(
            f"[추세] {ts} | price={price:,.2f} BB%={bbp:.3f} BBw={bb_width:.4f} "
            f"regime={'UP' if is_uptrend else 'DOWN'} confirmed={trend_confirmed} | "
            f"포지션: L{long_step}단계 S{short_step}단계 진입가={entry_price:,.2f}"
        )

        # --- 물타기 3회 후 손절/트레일링스톱/익절 (최우선) ---
        if long_step >= 3 and entry_price > 0:
            pnl_pct = (price - entry_price) / entry_price
            # 손절
            if pnl_pct <= -self.stoploss_pct:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.STOP_LOSS,
                    price=price,
                    leverage=leverage,
                    stop_loss_ratio=1.0,
                    reason=f"추세 Long 손절 (PnL={pnl_pct:.2%}, 기준=-{self.stoploss_pct:.2%})",
                ))
                return signals
            # 트레일링 스톱: 수익이 기준 이상 도달한 후 고점 대비 되돌림 시 익절
            peak_pnl = (peak_price - entry_price) / entry_price if peak_price > 0 else 0
            if peak_pnl >= self.trailing_start_pct:
                drawdown_from_peak = (peak_price - price) / peak_price
                if drawdown_from_peak >= self.trailing_stop_pct:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.TAKE_PROFIT,
                        price=price,
                        leverage=leverage,
                        reason=f"추세 Long 트레일링 익절 (PnL={pnl_pct:.2%}, 고점대비=-{drawdown_from_peak:.2%})",
                    ))
                    return signals
            # 고정 익절 (트레일링에 안 걸린 경우 폴백)
            elif pnl_pct >= self.takeprofit_pct:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.TAKE_PROFIT,
                    price=price,
                    leverage=leverage,
                    reason=f"추세 Long 익절 (PnL={pnl_pct:.2%}, 기준=+{self.takeprofit_pct:.2%})",
                ))
                return signals

        if short_step >= 3 and entry_price > 0:
            pnl_pct = (entry_price - price) / entry_price
            # 손절
            if pnl_pct <= -self.stoploss_pct:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.STOP_LOSS,
                    price=price,
                    leverage=leverage,
                    stop_loss_ratio=1.0,
                    reason=f"추세 Short 손절 (PnL={pnl_pct:.2%}, 기준=-{self.stoploss_pct:.2%})",
                ))
                return signals
            # 트레일링 스톱: 수익이 기준 이상 도달한 후 저점 대비 되돌림 시 익절
            trough_pnl = (entry_price - trough_price) / entry_price if trough_price < float("inf") else 0
            if trough_pnl >= self.trailing_start_pct:
                drawdown_from_trough = (price - trough_price) / trough_price
                if drawdown_from_trough >= self.trailing_stop_pct:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.TAKE_PROFIT,
                        price=price,
                        leverage=leverage,
                        reason=f"추세 Short 트레일링 익절 (PnL={pnl_pct:.2%}, 저점대비=+{drawdown_from_trough:.2%})",
                    ))
                    return signals
            # 고정 익절 (트레일링에 안 걸린 경우 폴백)
            elif pnl_pct >= self.takeprofit_pct:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.TAKE_PROFIT,
                    price=price,
                    leverage=leverage,
                    reason=f"추세 Short 익절 (PnL={pnl_pct:.2%}, 기준=+{self.takeprofit_pct:.2%})",
                ))
                return signals

        # --- BB 상단 도달 ---
        if bbp >= 0.80:
            if is_uptrend and trend_confirmed:
                # 상승 추세 → Long 진입/추가 (short 보유 중이면 무시, 최대 3회)
                if short_step == 0 and long_step < 3:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.LONG_ENTRY,
                        price=price,
                        leverage=leverage,
                        position_ratio=0.20,
                        entry_step=long_step + 1,
                        reason=f"추세추종 Long BB상단 (BB%={bbp:.2f}, regime=UP)",
                    ))
                else:
                    if short_step > 0:
                        logger.debug(f"[추세] BB상단 Long 미진입: Short 포지션 보유 중 (S{short_step}단계)")
                    elif long_step >= 3:
                        logger.debug(f"[추세] BB상단 Long 미진입: 최대 단계 도달 (L{long_step}단계)")
            else:
                # 하락 추세 → Short 진입/추가 (long 보유 중이면 무시)
                if long_step == 0:
                    for level in SHORT_ENTRY_LEVELS:
                        if bbp >= level["bbp"] and short_step < level["step"]:
                            signals.append(Signal(
                                timestamp=ts,
                                signal_type=SignalType.SHORT_ENTRY,
                                price=price,
                                leverage=leverage,
                                position_ratio=level["ratio"],
                                entry_step=level["step"],
                                reason=f"추세장 반전매도 {level['step']}차 (BB%={bbp:.2f}, regime=DOWN)",
                            ))
                            break
                else:
                    logger.debug(f"[추세] BB상단 Short 미진입: Long 포지션 보유 중 (L{long_step}단계)")
                if not trend_confirmed:
                    logger.debug(f"[추세] BB상단 미확인: 추세확인 실패 (MACD/RSI/Vol)")
            return signals

        # --- BB 하단 도달 ---
        if bbp <= 0.20:
            if not is_uptrend and trend_confirmed:
                # 하락 추세 → Short 진입/추가 (long 보유 중이면 무시, 최대 3회)
                if long_step == 0 and short_step < 3:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.SHORT_ENTRY,
                        price=price,
                        leverage=leverage,
                        position_ratio=0.20,
                        entry_step=short_step + 1,
                        reason=f"추세추종 Short BB하단 (BB%={bbp:.2f}, regime=DOWN)",
                    ))
                else:
                    if long_step > 0:
                        logger.debug(f"[추세] BB하단 Short 미진입: Long 포지션 보유 중 (L{long_step}단계)")
                    elif short_step >= 3:
                        logger.debug(f"[추세] BB하단 Short 미진입: 최대 단계 도달 (S{short_step}단계)")
            else:
                # 상승 추세 → Long 진입/추가 (short 보유 중이면 무시)
                if short_step == 0:
                    for level in LONG_ENTRY_LEVELS:
                        if bbp <= level["bbp"] and long_step < level["step"]:
                            signals.append(Signal(
                                timestamp=ts,
                                signal_type=SignalType.LONG_ENTRY,
                                price=price,
                                leverage=leverage,
                                position_ratio=level["ratio"],
                                entry_step=level["step"],
                                reason=f"추세장 반전매수 {level['step']}차 (BB%={bbp:.2f}, regime=UP)",
                            ))
                            break
                else:
                    logger.debug(f"[추세] BB하단 Long 미진입: Short 포지션 보유 중 (S{short_step}단계)")
                if not trend_confirmed:
                    logger.debug(f"[추세] BB하단 미확인: 추세확인 실패 (MACD/RSI/Vol)")
            return signals

        # BB 중간대 → 관망
        logger.debug(f"[추세] BB 중간대 — 관망: BB%={bbp:.3f} (진입조건: ≥0.80 또는 ≤0.20)")
        return signals

    def _confirm_trend(self, row: pd.Series, is_uptrend: bool) -> bool:
        """MACD, RSI, Volume을 종합하여 추세 지속 여부를 확인한다."""
        confirmations = 0
        details = []
        direction = "UP" if is_uptrend else "DOWN"

        # MACD: diff 양수면 상승, 음수면 하락
        macd_ok = (is_uptrend and row["macd_diff"] > 0) or (not is_uptrend and row["macd_diff"] < 0)
        if macd_ok:
            confirmations += 1
            details.append(f"MACD=O({row['macd_diff']:.2f})")
        else:
            details.append(f"MACD=X({row['macd_diff']:.2f})")

        # RSI: 50 이상이면 상승 우세, 50 이하이면 하락 우세
        rsi_ok = (is_uptrend and row["rsi"] > 50) or (not is_uptrend and row["rsi"] < 50)
        if rsi_ok:
            confirmations += 1
            details.append(f"RSI=O({row['rsi']:.1f})")
        else:
            details.append(f"RSI=X({row['rsi']:.1f})")

        # Volume: 평균 이상이면 추세 신뢰도 상승
        vol_ok = row["volume"] > row["volume_sma"]
        if vol_ok:
            confirmations += 1
            details.append("Vol=O")
        else:
            details.append("Vol=X")

        confirmed = confirmations >= 2
        logger.debug(f"[추세확인] {direction} {confirmations}/3 → {'확인' if confirmed else '미확인'} | {' '.join(details)}")
        return confirmed

    # ------------------------------------------------------------------
    # 포지션 상태 업데이트
    # ------------------------------------------------------------------

    def _update_position(
        self,
        sig: Signal,
        long_step: int,
        short_step: int,
        entry_price: float,
        total_weight: float,
    ) -> tuple[int, int, float, float]:
        """시그널에 따라 포지션 상태를 업데이트한다."""
        if sig.signal_type == SignalType.LONG_ENTRY:
            long_step = sig.entry_step
            # 금액 가중평균 진입가 갱신 (엔진과 동일 방식)
            w = sig.position_ratio
            if total_weight == 0:
                entry_price = sig.price
                total_weight = w
            else:
                entry_price = (entry_price * total_weight + sig.price * w) / (total_weight + w)
                total_weight += w

        elif sig.signal_type == SignalType.SHORT_ENTRY:
            short_step = sig.entry_step
            w = sig.position_ratio
            if total_weight == 0:
                entry_price = sig.price
                total_weight = w
            else:
                entry_price = (entry_price * total_weight + sig.price * w) / (total_weight + w)
                total_weight += w

        elif sig.signal_type in (
            SignalType.LONG_EXIT, SignalType.SHORT_EXIT,
            SignalType.TAKE_PROFIT,
        ):
            long_step = 0
            short_step = 0
            entry_price = 0.0
            total_weight = 0.0

        elif sig.signal_type == SignalType.STOP_LOSS:
            if sig.stop_loss_ratio >= 1.0:
                long_step = 0
                short_step = 0
                entry_price = 0.0
                total_weight = 0.0
            # 50% 손절은 단계 유지 (일부 청산)

        return long_step, short_step, entry_price, total_weight

    # ------------------------------------------------------------------
    # 시그널 → DataFrame 변환 (분석 편의)
    # ------------------------------------------------------------------

    def signals_to_dataframe(self, signals: list[Signal]) -> pd.DataFrame:
        """시그널 리스트를 DataFrame으로 변환한다."""
        if not signals:
            return pd.DataFrame()

        records = []
        for s in signals:
            records.append({
                "timestamp": s.timestamp,
                "signal_type": s.signal_type.value,
                "price": s.price,
                "leverage": s.leverage,
                "position_ratio": s.position_ratio,
                "entry_step": s.entry_step,
                "stop_loss_ratio": s.stop_loss_ratio,
                "reason": s.reason,
            })
        return pd.DataFrame(records).set_index("timestamp")
