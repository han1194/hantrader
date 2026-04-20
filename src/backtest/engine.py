"""백테스트 엔진.

시그널 리스트를 기반으로 가상 매매를 시뮬레이션하고 거래 내역을 생성한다.
"""

from dataclasses import dataclass, field

import pandas as pd

from src.strategy.base import Signal, SignalType
from src.utils.log_manager import LogManager, HanLogger


@dataclass
class Trade:
    """개별 거래 기록."""
    trade_id: int
    position_id: int = 0        # 포지션 그룹 ID
    entry_time: pd.Timestamp = None
    exit_time: pd.Timestamp | None = None
    side: str = ""              # "long" or "short"
    entry_price: float = 0.0
    exit_price: float = 0.0
    leverage: int = 1
    position_size: float = 0.0  # 투입 금액 (마진, USDT)
    quantity: float = 0.0       # 수량 (코인 단위)
    pnl: float = 0.0            # 실현 손익 (USDT, 레버리지 적용 후)
    pnl_pct: float = 0.0        # 수익률 (레버리지 적용 전)
    entry_step: int = 0         # 물타기 단계
    entry_reason: str = ""
    exit_reason: str = ""
    entry_bbp: float = 0.0      # 진입 시 BB%
    exit_bbp: float = 0.0       # 청산 시 BB%
    entry_metadata: dict = field(default_factory=dict)  # 진입 시 지표값
    exit_metadata: dict = field(default_factory=dict)    # 청산 시 지표값
    is_closed: bool = False


@dataclass
class Position:
    """현재 보유 포지션."""
    position_id: int = 0
    side: str = ""
    avg_price: float = 0.0
    total_margin: float = 0.0   # 총 투입 마진
    leverage: int = 1
    entry_steps: int = 0
    trades: list[Trade] = field(default_factory=list)


class BacktestEngine:
    """백테스트 엔진.

    시그널을 순서대로 처리하여 가상 매매를 실행한다.

    Attributes:
        initial_capital: 초기 자본금
        capital: 현재 잔고
        min_investment: 최소 투자 금액 (1회 진입)
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        min_investment: float = 0.001,
        max_margin_per_entry: float = 50.0,
        margin_pct: float = 0.0,
        exchange: str = "",
        symbol: str = "",
        timeframe: str = "",
        db: "object | None" = None,
        save_mode: str = "backtest",
    ):
        self.initial_capital = initial_capital
        self.min_investment = min_investment  # 최소 투자 수량 (코인 단위)
        self.max_margin_per_entry = max_margin_per_entry  # 1회 진입 마진 상한 (USDT, margin_pct=0일 때 사용)
        self.margin_pct = margin_pct  # 자본 대비 마진 비율 (>0이면 동적 마진, 예: 0.05=자본의 5%)
        self.capital = initial_capital
        self.position = Position()
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[dict] = []
        self._trade_counter = 0
        self._position_counter = 0
        # DB 저장: backtest → backtest_trades, simulator → simulator_trades
        self._exchange_for_db = exchange
        self._symbol_for_db = symbol
        self._timeframe_for_db = timeframe
        self._db = db
        self._save_mode = save_mode
        self.log: HanLogger = LogManager.instance().bind(exchange, symbol, mode="backtest")

    def run(self, signals: list[Signal], ohlcv: pd.DataFrame) -> list[Trade]:
        """시그널 리스트를 처리하여 백테스트를 실행한다.

        Args:
            signals: 전략에서 생성된 시그널 리스트
            ohlcv: 원본 OHLCV 데이터 (equity curve 계산용)

        Returns:
            닫힌 거래 목록
        """
        self.capital = self.initial_capital
        self.position = Position()
        self.closed_trades = []
        self.equity_curve = []
        self._trade_counter = 0
        self._position_counter = 0

        margin_desc = f"자본의 {self.margin_pct:.1%}" if self.margin_pct > 0 else f"{self.max_margin_per_entry:,.0f} USDT/회"
        self.log.system(
            f"백테스트 시작: 초기자본={self.initial_capital:,.0f}, "
            f"마진={margin_desc}, 시그널={len(signals)}건"
        )

        for signal in signals:
            self._process_signal(signal)
            self._record_equity(signal.timestamp, signal.price)

            # 파산: equity가 0 이하이면 조기 종료
            if not self.position.side and self.capital <= 0:
                self.log.asset("자본 소진 — 백테스트 조기 종료", level="WARNING")
                break

        # 미청산 포지션 강제 청산
        if self.position.side:
            last_price = signals[-1].price if signals else 0
            last_ts = signals[-1].timestamp if signals else pd.Timestamp.now()
            self._close_position(last_ts, last_price, "백테스트 종료 강제 청산")

        self.log.system(
            f"백테스트 완료: 최종자본={self.capital:,.0f}, "
            f"거래={len(self.closed_trades)}건"
        )
        return self.closed_trades

    def _get_equity(self, price: float) -> float:
        """현재 equity(총자산)를 계산한다."""
        unrealized = 0.0
        if self.position.side and price > 0:
            pos = self.position
            if pos.side == "long":
                pnl_pct = (price - pos.avg_price) / pos.avg_price
            else:
                pnl_pct = (pos.avg_price - price) / pos.avg_price
            unrealized = pos.total_margin * pnl_pct * pos.leverage
        return self.capital + self.position.total_margin + unrealized

    def _process_signal(self, signal: Signal):
        """개별 시그널을 처리한다."""
        # 강제청산 체크: equity가 0 이하이면 즉시 청산 후 거래 중단
        if self.position.side:
            equity = self._get_equity(signal.price)
            if equity <= 0:
                self._close_position(
                    signal.timestamp, signal.price, "강제청산 (equity 소진)")
                return

        if signal.signal_type == SignalType.LONG_ENTRY:
            self._open_or_add("long", signal)
        elif signal.signal_type == SignalType.SHORT_ENTRY:
            self._open_or_add("short", signal)
        elif signal.signal_type == SignalType.LONG_EXIT:
            if self.position.side == "long":
                self._close_position(signal.timestamp, signal.price, signal.reason, signal.metadata)
        elif signal.signal_type == SignalType.SHORT_EXIT:
            if self.position.side == "short":
                self._close_position(signal.timestamp, signal.price, signal.reason, signal.metadata)
        elif signal.signal_type == SignalType.STOP_LOSS:
            self._handle_stop_loss(signal)
        elif signal.signal_type == SignalType.TAKE_PROFIT:
            if self.position.side:
                self._close_position(signal.timestamp, signal.price, signal.reason, signal.metadata)

    def _open_or_add(self, side: str, signal: Signal):
        """포지션 진입 또는 물타기."""
        # 잔고 부족 시 진입 불가
        if self.capital <= 0:
            return

        # 반대 포지션이면 먼저 청산
        if self.position.side and self.position.side != side:
            self._close_position(signal.timestamp, signal.price, f"반대 포지션 전환 ({self.position.side} → {side})", signal.metadata)

        margin = self.capital * signal.position_ratio
        if signal.price <= 0:
            return

        # 마진 상한: margin_pct > 0이면 자본 대비 %, 아니면 고정 USDT
        if self.margin_pct > 0:
            max_margin = self.capital * self.margin_pct
        else:
            max_margin = self.max_margin_per_entry
        margin = min(margin, self.capital, max_margin)

        # 수량 계산 후 최소 투자 수량(코인 단위) 체크
        quantity = (margin * signal.leverage) / signal.price
        if quantity < self.min_investment:
            # 최소 수량에 맞는 마진 역산
            margin = (self.min_investment * signal.price) / signal.leverage
            margin = min(margin, self.capital)
            quantity = (margin * signal.leverage) / signal.price
        if margin <= 0 or quantity <= 0:
            return

        self._trade_counter += 1
        trade = Trade(
            trade_id=self._trade_counter,
            position_id=self.position.position_id if self.position.side else self._position_counter + 1,
            entry_time=signal.timestamp,
            side=side,
            entry_price=signal.price,
            leverage=signal.leverage,
            position_size=margin,
            quantity=quantity,
            entry_step=signal.entry_step,
            entry_reason=signal.reason,
            entry_bbp=signal.metadata.get("bbp", 0.0),
            entry_metadata=dict(signal.metadata),
        )

        # 포지션 업데이트
        if not self.position.side:
            self._position_counter += 1
            self.position.position_id = self._position_counter
            self.position.side = side
            self.position.avg_price = signal.price
            self.position.total_margin = margin
            self.position.leverage = signal.leverage
            self.position.entry_steps = signal.entry_step
        else:
            # 물타기: 평균 단가 갱신
            old_total = self.position.total_margin
            new_total = old_total + margin
            self.position.avg_price = (
                (self.position.avg_price * old_total + signal.price * margin) / new_total
            )
            self.position.total_margin = new_total
            self.position.leverage = signal.leverage
            self.position.entry_steps = signal.entry_step

        self.position.trades.append(trade)
        self.capital -= margin

        action = "entry" if signal.entry_step == 1 else "add"
        self._save_db_event(
            action=action, ts=signal.timestamp, price=signal.price,
            side=side, leverage=signal.leverage,
            margin=margin, quantity=quantity,
            reason=signal.reason, entry_step=signal.entry_step,
        )

    def _close_position(
        self, timestamp: pd.Timestamp, price: float, reason: str,
        exit_metadata: dict | None = None,
    ):
        """포지션 전체 청산."""
        if not self.position.side:
            return

        pos = self.position
        if pos.side == "long":
            pnl_pct = (price - pos.avg_price) / pos.avg_price
        else:
            pnl_pct = (pos.avg_price - price) / pos.avg_price

        pnl = pos.total_margin * pnl_pct * pos.leverage

        # 실거래 제약: 손실은 투입 마진을 초과할 수 없음 (강제청산)
        if pnl < -pos.total_margin:
            pnl = -pos.total_margin
            reason = f"강제청산 (마진 소진) | 원래사유: {reason}"

        exit_meta = exit_metadata or {}

        # 각 개별 거래에 청산 정보 기록
        for trade in pos.trades:
            trade.exit_time = timestamp
            trade.exit_price = price
            trade.exit_reason = reason
            trade.exit_bbp = exit_meta.get("bbp", 0.0)
            trade.exit_metadata = dict(exit_meta)
            trade.is_closed = True
            # 개별 거래의 PnL (비중에 따라 배분)
            ratio = trade.position_size / pos.total_margin if pos.total_margin > 0 else 0
            trade.pnl = pnl * ratio
            trade.pnl_pct = pnl_pct
            self.closed_trades.append(trade)

        self.capital += pos.total_margin + pnl

        self.log.trade(
            f"청산: {pos.side} avg={pos.avg_price:.2f} → {price:.2f} "
            f"PnL={pnl:+,.2f} ({pnl_pct:+.2%}) | {reason}",
            level="DEBUG",
        )

        # DB 저장: 전체 청산 이벤트
        is_stop = self._is_stop_reason(reason)
        total_qty = sum(t.quantity for t in pos.trades) or (pos.total_margin * pos.leverage / price if price else 0)
        self._save_db_event(
            action="stop_loss" if is_stop else "exit",
            ts=timestamp, price=price, side=pos.side,
            leverage=pos.leverage, margin=pos.total_margin,
            quantity=total_qty, pnl=pnl, pnl_pct=pnl_pct,
            reason=reason, entry_step=pos.entry_steps,
        )

        self.position = Position()

    def _handle_stop_loss(self, signal: Signal):
        """손절 처리. stop_loss_ratio에 따라 부분/전체 청산."""
        if not self.position.side:
            return

        if signal.stop_loss_ratio >= 1.0:
            self._close_position(signal.timestamp, signal.price, signal.reason, signal.metadata)
        else:
            # 부분 손절
            pos = self.position
            close_margin = pos.total_margin * signal.stop_loss_ratio

            if pos.side == "long":
                pnl_pct = (signal.price - pos.avg_price) / pos.avg_price
            else:
                pnl_pct = (pos.avg_price - signal.price) / pos.avg_price

            pnl = close_margin * pnl_pct * pos.leverage
            # 실거래 제약: 손실은 청산 마진을 초과할 수 없음
            if pnl < -close_margin:
                pnl = -close_margin
            self.capital += close_margin + pnl
            pos.total_margin -= close_margin

            self.log.trade(
                f"부분 손절 {signal.stop_loss_ratio:.0%}: "
                f"PnL={pnl:+,.2f} ({pnl_pct:+.2%}) | {signal.reason}",
                level="DEBUG",
            )

            # DB 저장: 부분 손절 이벤트 (포지션 유지)
            close_qty = close_margin * pos.leverage / signal.price if signal.price else 0
            self._save_db_event(
                action="stop_loss", ts=signal.timestamp, price=signal.price,
                side=pos.side, leverage=pos.leverage,
                margin=close_margin, quantity=close_qty,
                pnl=pnl, pnl_pct=pnl_pct,
                reason=f"부분손절 {signal.stop_loss_ratio:.0%} | {signal.reason}",
                entry_step=pos.entry_steps,
            )

            if pos.total_margin <= 0:
                self.position = Position()

    # ------------------------------------------------------------------
    # DB 저장 헬퍼 (backtest / simulator 공통 엔진이므로 여기에 둠)
    # ------------------------------------------------------------------

    _STOP_KEYWORDS = ("손절", "stop", "강제청산", "소진")

    def _is_stop_reason(self, reason: str) -> bool:
        r = (reason or "").lower()
        return any(k.lower() in r for k in self._STOP_KEYWORDS)

    def _save_db_event(
        self,
        action: str,
        ts: pd.Timestamp,
        price: float,
        side: str,
        leverage: int,
        margin: float,
        quantity: float,
        pnl: float = 0.0,
        pnl_pct: float = 0.0,
        reason: str = "",
        entry_step: int = 1,
    ):
        """매매 이벤트를 DB에 저장한다. db가 없으면 no-op."""
        if self._db is None:
            return
        try:
            ts_str = (
                ts.strftime("%Y-%m-%d %H:%M:%S+09:00")
                if isinstance(ts, pd.Timestamp) else str(ts)
            )
            self._db.save_trade(
                exchange=self._exchange_for_db,
                symbol=self._symbol_for_db,
                timeframe=self._timeframe_for_db,
                datetime_str=ts_str,
                side=side,
                action=action,
                price=float(price),
                quantity=float(quantity),
                amount=float(quantity) * float(price),
                leverage=int(leverage),
                margin=float(margin),
                pnl=float(pnl),
                pnl_pct=float(pnl_pct),
                reason=str(reason),
                entry_step=int(entry_step),
                mode=self._save_mode,
            )
        except Exception as e:
            try:
                self.log.system(
                    f"DB 저장 실패 ({self._save_mode}): {e}",
                    level="WARNING",
                )
            except Exception:
                pass

    def _record_equity(self, timestamp: pd.Timestamp, price: float):
        """equity curve 기록."""
        unrealized = 0.0
        if self.position.side:
            pos = self.position
            if pos.side == "long":
                pnl_pct = (price - pos.avg_price) / pos.avg_price
            else:
                pnl_pct = (pos.avg_price - price) / pos.avg_price
            unrealized = pos.total_margin * pnl_pct * pos.leverage

        equity = self.capital + self.position.total_margin + unrealized
        self.equity_curve.append({
            "timestamp": timestamp,
            "equity": equity,
            "capital": self.capital,
            "unrealized": unrealized,
        })

    def get_equity_df(self) -> pd.DataFrame:
        """equity curve를 DataFrame으로 반환한다."""
        if not self.equity_curve:
            return pd.DataFrame()
        df = pd.DataFrame(self.equity_curve)
        df.set_index("timestamp", inplace=True)
        return df

    def get_trades_df(self) -> pd.DataFrame:
        """거래 내역을 DataFrame으로 반환한다."""
        if not self.closed_trades:
            return pd.DataFrame()

        records = []
        for t in self.closed_trades:
            records.append({
                "trade_id": t.trade_id,
                "position_id": t.position_id,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "leverage": t.leverage,
                "position_size": t.position_size,
                "quantity": t.quantity,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "entry_step": t.entry_step,
                "entry_bbp": t.entry_bbp,
                "exit_bbp": t.exit_bbp,
                "entry_reason": t.entry_reason,
                "exit_reason": t.exit_reason,
            })
        return pd.DataFrame(records)
