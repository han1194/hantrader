"""라이브 시뮬레이터.

실시간 거래소 데이터를 수신하고, 백테스트 엔진으로 가상 매매를 실행한다.
실제 주문은 발생하지 않는 페이퍼 트레이딩 시스템이다.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.backtest.engine import BacktestEngine
from src.core.live_base import LiveEngineBase
from src.exchange import ExchangeWrapper
from src.strategy.base import Signal
from src.utils.timeframe import KST


class LiveSimulator(LiveEngineBase):
    """실시간 데이터 기반 페이퍼 트레이딩 시뮬레이터.

    거래소에서 실시간 OHLCV를 폴링하고, 새 캔들이 완성될 때마다
    전략 시그널을 생성하여 백테스트 엔진으로 가상 매매를 실행한다.
    """

    _title = "라이브 시뮬레이터 (페이퍼 트레이딩)"
    _log_prefix = "sim"

    def __init__(
        self,
        exchange: ExchangeWrapper,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        initial_capital: float = 1000.0,
        min_investment: float = 0.001,
        max_margin_per_entry: float = 50.0,
        margin_pct: float = 0.0,
        leverage_max: int = 50,
        leverage_min: int = 25,
        sideways_leverage_max: int = 15,
        lookback_candles: int = 100,
        log_dir: str = "data/simulator",
        strategy_kwargs: dict | None = None,
        strategy_name: str = "bb",
    ):
        super().__init__(
            exchange=exchange,
            exchange_name=exchange_name,
            symbol=symbol,
            timeframe=timeframe,
            lookback_candles=lookback_candles,
            log_dir=log_dir,
            strategy_kwargs=strategy_kwargs,
            strategy_name=strategy_name,
            leverage_max=leverage_max,
            leverage_min=leverage_min,
            sideways_leverage_max=sideways_leverage_max,
        )

        # 백테스트 엔진 (가상 매매용)
        self.engine = BacktestEngine(
            initial_capital=initial_capital,
            min_investment=min_investment,
            max_margin_per_entry=max_margin_per_entry,
            margin_pct=margin_pct,
        )
        self.engine.capital = initial_capital
        self.engine.initial_capital = initial_capital

        # CSV 저장 경로
        self._csv_dir = Path(log_dir)

    # ------------------------------------------------------------------
    # 추상 메서드 구현
    # ------------------------------------------------------------------

    def _execute_new_signals(self, signals: list[Signal]):
        for signal in signals:
            self.engine._process_signal(signal)
            self.engine._record_equity(signal.timestamp, signal.price)
            self._print_signal(signal)
            self.log.trade(
                f"시그널 실행 | {signal.signal_type.value} | "
                f"가격={signal.price:,.2f} 레버={signal.leverage}x | "
                f"사유: {signal.reason}"
            )

    def _get_current_price(self, df: pd.DataFrame) -> float:
        return df.iloc[-1]["close"]

    def _get_equity(self, price: float) -> float:
        return self.engine._get_equity(price)

    def _get_initial_capital(self) -> float:
        return self.engine.initial_capital

    def _get_position_info(self, price: float) -> str:
        pos = self.engine.position
        if not pos.side:
            return "없음"
        if pos.side == "long":
            unrealized_pct = (price - pos.avg_price) / pos.avg_price
        else:
            unrealized_pct = (pos.avg_price - price) / pos.avg_price
        unrealized = pos.total_margin * unrealized_pct * pos.leverage
        return (f"{pos.side.upper()} | 마진: {pos.total_margin:,.2f} USDT | "
                f"평단: {pos.avg_price:,.2f} | "
                f"미실현: {unrealized:+,.2f} USDT ({unrealized_pct:+.2%})")

    def _get_trade_count(self) -> int:
        return len(self.engine.closed_trades)

    def _get_pnl_summary(self) -> dict:
        trades = self.engine.closed_trades
        total_pnl = sum(t.pnl for t in trades)
        wins = sum(1 for t in trades if t.pnl > 0)
        losses = sum(1 for t in trades if t.pnl <= 0)
        return {
            "total_pnl": total_pnl,
            "trade_count": len(trades),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(trades) if trades else 0,
        }

    def _format_margin_info(self) -> str:
        if self.engine.margin_pct > 0:
            return f"마진=자본의 {self.engine.margin_pct:.1%}"
        return f"마진={self.engine.max_margin_per_entry:,.2f} USDT/회"

    # ------------------------------------------------------------------
    # 출력 커스터마이징
    # ------------------------------------------------------------------

    def _print_header_extra(self):
        print(f"  초기자본:   {self.engine.initial_capital:,.2f} USDT")
        if self.engine.margin_pct > 0:
            print(f"  마진:       자본의 {self.engine.margin_pct:.1%}")
        else:
            print(f"  마진상한:   {self.engine.max_margin_per_entry:,.2f} USDT/회")

    def _on_initialized(self):
        self._print_status(self._get_current_price_from_engine())

    def _print_status_extra(self):
        print(f"           거래: {self._get_trade_count()}건 완료")

    def _print_summary_body(self, summary: dict):
        print(f"  초기 자본:    {self.engine.initial_capital:>12,.2f} USDT")
        print(f"  현재 잔고:    {self.engine.capital:>12,.2f} USDT")
        print(f"  실현 손익:    {summary['total_pnl']:>+12,.2f} USDT")
        print(f"  총 거래:      {summary['trade_count']:>12d}건 "
              f"(승: {summary['wins']} / 패: {summary['losses']})")

        if self.engine.position.side:
            pos = self.engine.position
            print(f"\n  [미청산 포지션]")
            print(f"    방향: {pos.side.upper()}")
            print(f"    마진: {pos.total_margin:,.2f} USDT")
            print(f"    평단: {pos.avg_price:,.2f}")
            print(f"    진입: {len(pos.trades)}회")

        if summary['trade_count'] > 0:
            print(f"\n  승률: {summary['win_rate']:.1%}")

    def _save_summary_body(self, summary: dict):
        self.log.asset(f"초기 자본: {self.engine.initial_capital:,.2f} USDT")
        self.log.asset(f"현재 잔고: {self.engine.capital:,.2f} USDT")
        self.log.asset(f"실현 손익: {summary['total_pnl']:+,.2f} USDT")
        self.log.trade(
            f"총 거래: {summary['trade_count']}건 "
            f"(승: {summary['wins']} / 패: {summary['losses']})"
        )

        if self.engine.position.side:
            pos = self.engine.position
            self.log.trade(
                f"미청산 포지션: {pos.side.upper()} 마진={pos.total_margin:,.2f} "
                f"평단={pos.avg_price:,.2f} 진입={len(pos.trades)}회"
            )

        if summary['trade_count'] > 0:
            self.log.trade(f"승률: {summary['win_rate']:.1%}")

    def _save_trades_csv(self):
        trades_df = self.engine.get_trades_df()
        if not trades_df.empty:
            ts = self._start_time.strftime("%H%M%S")
            safe_symbol = self.symbol.replace("/", "_")
            csv_dir = self._csv_dir / safe_symbol
            csv_dir.mkdir(parents=True, exist_ok=True)
            csv_path = csv_dir / f"trades_{self.timeframe}_{ts}.csv"
            trades_df.to_csv(csv_path, index=False)
            self.log.trade(f"거래 내역 CSV 저장: {csv_path}")

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _get_current_price_from_engine(self) -> float:
        """초기화 시점에서 df 없이 가격을 가져온다."""
        try:
            df = self._fetch_candles()
            if not df.empty:
                return df.iloc[-1]["close"]
        except Exception:
            pass
        return 0.0
