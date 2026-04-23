"""Bollinger Bands 기반 트레이딩 전략 (분할된 헬퍼 모듈 위에 얇게 래핑).

로직 세부는 아래 모듈에 있다:
  - levels: 진입/손절 레벨 상수 (mutation 가능한 모듈 전역)
  - indicators: BB/SMA/EMA/MACD/RSI/ADX 지표 계산
  - regime: 다중지표 2단계 점수 기반 국면 판단
  - leverage: BBW 기반 동적 레버리지
  - position: 시그널→포지션 상태 업데이트
  - sideways: 횡보장 반전매매 시그널
  - trend: 추세장 시그널 + 추세 확인
"""

import pandas as pd

from src.utils.logger import setup_logger
from ..base import BaseStrategy, Signal, SignalType, MarketRegime
from ..registry import register_strategy
from . import levels as _levels
from .indicators import compute_bb_indicators
from .regime import detect_scored_regime
from .leverage import calc_bb_leverage
from .position import update_position_state
from .sideways import generate_sideways_signals
from .trend import generate_trend_signals, confirm_trend

logger = setup_logger("hantrader.strategy.bb")

# 하위 호환: 외부(shim 포함)가 `from .bb.strategy import LONG_ENTRY_LEVELS` 등으로
# 접근할 수 있도록 levels 모듈의 초기 바인딩을 재노출한다.
# 주의: __init__에서 config 오버라이드가 들어오면 `_levels` 모듈 전역을 변경하므로,
# 실제 로직은 `_levels.LONG_ENTRY_LEVELS` 를 지연 참조한다. 여기의 이름은 기본값 캡처.
LONG_ENTRY_LEVELS = _levels.LONG_ENTRY_LEVELS
SHORT_ENTRY_LEVELS = _levels.SHORT_ENTRY_LEVELS
LONG_STOP_LEVELS = _levels.LONG_STOP_LEVELS
SHORT_STOP_LEVELS = _levels.SHORT_STOP_LEVELS


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

        # config에서 오버라이드 가능한 진입/손절 레벨 — levels 모듈 전역을 갱신.
        # (기존 bb_strategy.py의 `global LONG_ENTRY_LEVELS` 재바인딩과 동등한 의미)
        if long_entry_levels is not None:
            _levels.LONG_ENTRY_LEVELS = long_entry_levels
        if short_entry_levels is not None:
            _levels.SHORT_ENTRY_LEVELS = short_entry_levels
        if long_stop_levels is not None:
            _levels.LONG_STOP_LEVELS = long_stop_levels
        if short_stop_levels is not None:
            _levels.SHORT_STOP_LEVELS = short_stop_levels

    # ------------------------------------------------------------------
    # 지표 / 국면 / 레버리지 (헬퍼 모듈 위임)
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return compute_bb_indicators(df, self.bb_period, self.bb_std, self.adx_rise_lookback)

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        return detect_scored_regime(df, self.regime_window, self.regime_threshold)

    def calc_leverage(self, bb_width: float, margin_total: float = 1.0) -> int:
        return calc_bb_leverage(bb_width, self.leverage_max, self.leverage_min)

    # ------------------------------------------------------------------
    # 시그널 생성 (루프는 그대로 유지, 내부 로직만 위임)
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
    # 횡보/추세/포지션 (하위 클래스 오버라이드 포인트 — 헬퍼 모듈 위임)
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
        return generate_sideways_signals(
            ts=ts, price=price, bbp=bbp, leverage=leverage,
            long_step=long_step, short_step=short_step, entry_price=entry_price,
            adx_entry_block=self.adx_entry_block,
            adx=adx, adx_rising=adx_rising,
            logger=logger,
        )

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
        return generate_trend_signals(
            ts=ts, price=price, bbp=bbp, bb_width=bb_width, leverage=leverage,
            regime=regime, row=row,
            long_step=long_step, short_step=short_step, entry_price=entry_price,
            stoploss_pct=self.stoploss_pct,
            takeprofit_pct=self.takeprofit_pct,
            trailing_start_pct=self.trailing_start_pct,
            trailing_stop_pct=self.trailing_stop_pct,
            peak_price=peak_price, trough_price=trough_price,
            logger=logger,
        )

    def _confirm_trend(self, row: pd.Series, is_uptrend: bool) -> bool:
        return confirm_trend(row, is_uptrend, logger)

    def _update_position(
        self,
        sig: Signal,
        long_step: int,
        short_step: int,
        entry_price: float,
        total_weight: float,
    ) -> tuple[int, int, float, float]:
        return update_position_state(sig, long_step, short_step, entry_price, total_weight)

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
