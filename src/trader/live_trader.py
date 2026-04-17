"""실거래 트레이더.

실시간 거래소 데이터를 수신하고, 전략 시그널에 따라 실제 주문을 실행한다.
시뮬레이터(LiveSimulator)와 동일한 전략/시그널 파이프라인을 사용하되,
BacktestEngine 대신 거래소 API로 실제 주문을 전송한다.
"""

import csv
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.core.live_base import LiveEngineBase
from src.exchange import ExchangeWrapper
from src.storage.database import DatabaseStorage
from src.strategy.base import Signal, SignalType
from src.utils.timeframe import KST


@dataclass
class LivePosition:
    """실거래 포지션 상태."""
    side: str = ""              # "long" or "short"
    avg_price: float = 0.0
    total_margin: float = 0.0   # 투입 마진 합계 (USDT)
    quantity: float = 0.0       # 보유 수량 (코인)
    leverage: int = 1
    entry_steps: int = 0
    liquidation_price: float = 0.0  # 청산가
    total_entry_fee: float = 0.0    # 진입 시 누적 수수료


@dataclass
class TradeRecord:
    """실거래 기록."""
    timestamp: str
    side: str
    action: str                 # "entry", "add", "exit", "stop_loss"
    price: float
    quantity: float
    margin: float
    leverage: int
    order_id: str
    reason: str
    pnl: float = 0.0
    fee: float = 0.0            # 거래 수수료 (USDT)


class LiveTrader(LiveEngineBase):
    """실거래 트레이더.

    전략 시그널을 실제 거래소 주문으로 변환한다.

    안전장치:
    - 1회 진입 마진 상한 (max_margin_per_entry)
    - 일일 최대 손실 제한 (daily_loss_limit)
    - 최대 동시 진입 횟수 제한 (max_entry_steps = 3)
    - 거래소 포지션과 내부 상태 주기적 동기화
    - Ctrl+C 시 안전 종료 (포지션 유지, 로그 저장)
    """

    _title = "실거래 트레이더"
    _log_prefix = "trade"

    def __init__(
        self,
        exchange: ExchangeWrapper,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        initial_capital: float = 1000.0,
        max_margin_per_entry: float = 50.0,
        margin_pct: float = 0.0,
        leverage_max: int = 50,
        leverage_min: int = 25,
        sideways_leverage_max: int = 15,
        margin_mode: str = "isolated",
        capital_mode: str = "total",
        daily_loss_limit: float = 0.0,
        lookback_candles: int = 100,
        log_dir: str = "data/trader",
        strategy_kwargs: dict | None = None,
        strategy_name: str = "bb",
        restore_state: bool = True,
        db: DatabaseStorage | None = None,
        trade_quantity: float | None = None,
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

        self.max_margin_per_entry = max_margin_per_entry
        self.margin_pct = margin_pct
        self.margin_mode = margin_mode
        self.capital_mode = capital_mode      # "total" 또는 "virtual"
        self.daily_loss_limit = daily_loss_limit

        # 상태
        self.position = LivePosition()
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.trade_records: list[TradeRecord] = []
        self._daily_pnl = 0.0
        self._daily_reset_date = ""
        self._min_amount = 0.0
        self._min_cost = 0.0                # 최소 주문금액 (notional, USDT)
        self._taker_fee = 0.0               # taker 수수료율 (거래소 조회)
        self._maker_fee = 0.0               # maker 수수료율 (거래소 조회)
        self._total_fees = 0.0              # 누적 거래 수수료
        self._total_funding_fees = 0.0      # 누적 펀딩 수수료
        self._last_funding_ts: int = 0      # 마지막 펀딩 조회 시각 (ms)
        self._restore_state = restore_state # 상태 복원 여부
        self._emergency_order_id: str = ""  # 거래소 서버사이드 비상 손절 주문 ID
        self._db = db                       # DB 저장소 (매매/자산 이력)
        self._trade_quantity = trade_quantity  # 코인별 고정 거래수량 (코인 단위)

    # ------------------------------------------------------------------
    # 라이프사이클 훅
    # ------------------------------------------------------------------

    def _on_start(self):
        self._setup_exchange()
        if self._restore_state:
            self._load_state()
        self._sync_balance()
        self._sync_position()
        # 재시작 시 기존 스톱 주문 정리 후 필요하면 재등록
        self._cleanup_existing_stop_orders()
        if self.position.side:
            self._place_emergency_stop()
        price = self._get_ticker_price()
        self._save_asset_snapshot("start", price, "트레이더 시작")

    def _on_stop(self):
        # 종료 전 거래소와 최종 동기화
        self._sync_balance()
        self._sync_position()
        self._sync_funding_fees()
        self._save_state()
        price = self._get_ticker_price()
        self._save_asset_snapshot("stop", price, "트레이더 중지")
        self.log.system("트레이더 중지 (Ctrl+C) — 포지션 유지")

    def _on_initialized(self):
        self._reconcile_strategy_state()
        self._print_status(self._get_ticker_price())

    def _reconcile_strategy_state(self):
        """워밍업 후 전략 내부 상태와 실제 거래소 포지션을 대조하여 불일치를 수정한다.

        워밍업(generate_signals 재현)은 과거 캔들을 기준으로 내부 step 상태를 계산하므로
        실제 거래소 포지션과 다를 수 있다. 여기서는 거래소 포지션을 정답으로 삼아 보정한다.
        """
        pos_side = self.position.side
        long_step = self._long_step
        short_step = self._short_step

        if not pos_side and (long_step > 0 or short_step > 0):
            self.log.trade(
                f"[상태 보정] 워밍업 내부 상태(L{long_step}/S{short_step})와 "
                f"실제 포지션(없음) 불일치 → 전략 상태 초기화",
                level="WARNING",
            )
            self._long_step = 0
            self._short_step = 0
            self._entry_price = 0.0
            self._total_weight = 0.0
        elif pos_side == "long" and long_step == 0:
            self.log.trade(
                f"[상태 보정] 실제 거래소 Long 포지션이 있으나 전략 내부 상태 0 "
                f"→ step=1 / 진입가={self.position.avg_price:,.2f} 로 복원",
                level="WARNING",
            )
            self._long_step = 1
            self._short_step = 0
            self._entry_price = self.position.avg_price
            self._total_weight = 1.0
        elif pos_side == "short" and short_step == 0:
            self.log.trade(
                f"[상태 보정] 실제 거래소 Short 포지션이 있으나 전략 내부 상태 0 "
                f"→ step=1 / 진입가={self.position.avg_price:,.2f} 로 복원",
                level="WARNING",
            )
            self._short_step = 1
            self._long_step = 0
            self._entry_price = self.position.avg_price
            self._total_weight = 1.0
        else:
            self.log.trade(
                f"[상태 확인] 거래소 포지션({pos_side or '없음'})과 "
                f"전략 상태(L{long_step}/S{short_step}) 일치",
                level="DEBUG",
            )

    def _on_tick_start(self):
        # 일일 손실 리셋
        today = datetime.now(KST).strftime("%Y-%m-%d")
        if today != self._daily_reset_date:
            self._daily_pnl = 0.0
            self._daily_reset_date = today

    def _on_tick_end(self):
        # 주기적 동기화 (10틱마다)
        if self._tick_count % 10 == 0:
            self._sync_balance()
            self._sync_position()
            self._sync_funding_fees()
            self._save_state()
            price = self._get_ticker_price()
            self._save_asset_snapshot("sync", price, f"tick={self._tick_count}")

    def _on_sync_tick(self):
        """중간 동기화: sync_timeframe 캔들 갱신 시 거래소와 동기화.

        메인 TF 캔들 사이에 발생한 포지션 변화(liquidation, 외부 청산 등)를 감지한다.
        """
        had_position = bool(self.position.side)
        old_side = self.position.side
        old_quantity = self.position.quantity

        self._sync_balance()
        self._sync_position()

        # 포지션이 사라진 경우 (liquidation / 외부 청산)
        if had_position and not self.position.side:
            price = self._get_ticker_price()
            self.log.trade(
                f"중간 동기화 포지션 소멸 | 이전={old_side.upper()} 수량={old_quantity:.6f} "
                f"| 현재가={price:,.2f} — liquidation 또는 외부 청산 가능성",
                level="WARNING",
            )
            # 전략 내부 상태 초기화
            self._long_step = 0
            self._short_step = 0
            self._entry_price = 0.0
            self._total_weight = 0.0
            self._cancel_emergency_stop()
            self._save_state()
            self._save_asset_snapshot("sync", price, "중간동기화: 포지션 소멸 감지")
        elif had_position and self.position.quantity != old_quantity:
            # 수량이 변경된 경우 (부분 청산 등)
            price = self._get_ticker_price()
            self.log.trade(
                f"중간 동기화 수량 변경 | {old_side.upper()} "
                f"{old_quantity:.6f} → {self.position.quantity:.6f} | 현재가={price:,.2f}"
            )
            self._save_state()
            self._save_asset_snapshot("sync", price, "중간동기화: 수량 변경 감지")

    # ------------------------------------------------------------------
    # 상태 저장/복원
    # ------------------------------------------------------------------

    def _get_state_path(self) -> Path:
        """상태 파일 경로를 반환한다."""
        safe_symbol = self.symbol.replace("/", "_")
        state_dir = Path("data") / "trader" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{safe_symbol}.json"

    def _save_state(self):
        """현재 상태를 JSON 파일에 저장한다."""
        try:
            state = {
                "initial_capital": self.initial_capital,
                "capital_mode": self.capital_mode,
                "virtual_capital": self.capital if self.capital_mode == "virtual" else None,
                "daily_pnl": self._daily_pnl,
                "daily_reset_date": self._daily_reset_date,
                "total_fees": self._total_fees,
                "total_funding_fees": self._total_funding_fees,
                "last_funding_ts": self._last_funding_ts,
                "trade_records": [asdict(r) for r in self.trade_records],
                "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            }
            path = self._get_state_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self.log.system(f"상태 저장: {path}", level="DEBUG")
        except Exception as e:
            self.log.system(f"상태 저장 실패: {e}", level="ERROR", exc_info=True)

    def _load_state(self):
        """저장된 상태 파일에서 복원한다."""
        path = self._get_state_path()
        if not path.exists():
            self.log.system("상태 파일 없음 — 새로 시작")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)

            self.initial_capital = state.get("initial_capital", self.initial_capital)
            # virtual 모드: 저장된 가상 자본 복원
            if self.capital_mode == "virtual":
                saved_vc = state.get("virtual_capital")
                if saved_vc is not None:
                    self.capital = saved_vc
                    self.log.system(f"가상 자본 복원: {self.capital:,.2f} USDT")
            self._daily_pnl = state.get("daily_pnl", 0.0)
            self._daily_reset_date = state.get("daily_reset_date", "")
            self._total_fees = state.get("total_fees", 0.0)
            self._total_funding_fees = state.get("total_funding_fees", 0.0)
            self._last_funding_ts = state.get("last_funding_ts", 0)

            # 거래 기록 복원
            records_raw = state.get("trade_records", [])
            self.trade_records = []
            for r in records_raw:
                self.trade_records.append(TradeRecord(
                    timestamp=r["timestamp"],
                    side=r["side"],
                    action=r["action"],
                    price=r["price"],
                    quantity=r["quantity"],
                    margin=r["margin"],
                    leverage=r["leverage"],
                    order_id=r["order_id"],
                    reason=r["reason"],
                    pnl=r.get("pnl", 0.0),
                    fee=r.get("fee", 0.0),
                ))

            updated = state.get("updated_at", "?")
            mode_info = f" virtual_capital={self.capital:,.2f}" if self.capital_mode == "virtual" else ""
            self.log.system(
                f"상태 복원 | initial_capital={self.initial_capital:,.2f}{mode_info} "
                f"daily_pnl={self._daily_pnl:+,.2f} 거래={len(self.trade_records)}건 "
                f"수수료={self._total_fees:,.4f} 펀딩={self._total_funding_fees:,.4f} "
                f"(저장시각: {updated})"
            )
        except Exception as e:
            self.log.system(f"상태 복원 실패: {e}", level="ERROR", exc_info=True)

    # ------------------------------------------------------------------
    # 거래소 설정
    # ------------------------------------------------------------------

    def _setup_exchange(self):
        """거래소 레버리지, 마진 모드를 설정한다.

        거래소에서 심볼별 제약조건(최대 레버리지, 수수료율, 최소 주문 등)을
        조회하여 config 값을 검증하고 필요 시 보정한다.
        """
        self.log.system(f"거래소 설정: {self.symbol}")

        try:
            self.exchange.load_markets()
        except Exception as e:
            self.log.system(f"마켓 로드 실패: {e}", level="ERROR")
            raise

        # --- 거래소에서 심볼 제약조건 조회 ---
        self._min_amount = self.exchange.get_min_amount(self.symbol)
        self._min_cost = self.exchange.get_min_cost(self.symbol)
        fee_rates = self.exchange.get_fee_rates(self.symbol)
        self._taker_fee = fee_rates["taker"]
        self._maker_fee = fee_rates["maker"]
        exchange_max_leverage = self.exchange.get_max_leverage(self.symbol)
        max_lev_display = (
            f"{exchange_max_leverage}x" if exchange_max_leverage > 0
            else "조회실패(config값 사용)"
        )

        self.log.system(
            f"거래소 제약조건 | 최소수량={self._min_amount} "
            f"최소금액={self._min_cost} USDT | "
            f"수수료: taker={self._taker_fee:.4%} maker={self._maker_fee:.4%} | "
            f"최대레버리지={max_lev_display}"
        )
        if exchange_max_leverage == 0:
            self.log.system(
                "최대 레버리지 조회 실패 — config 값 그대로 사용, 클램핑 없음",
                level="WARNING",
            )

        # --- 레버리지 검증: config 값이 거래소 한도 초과 시 클램핑 ---
        if exchange_max_leverage > 0:
            clamped = False
            if self.strategy.leverage_max > exchange_max_leverage:
                old = self.strategy.leverage_max
                self.strategy.leverage_max = exchange_max_leverage
                self.log.system(
                    f"leverage_max 클램핑: config={old}x → 거래소={exchange_max_leverage}x",
                    level="WARNING",
                )
                clamped = True
            if self.strategy.leverage_min > exchange_max_leverage:
                old = self.strategy.leverage_min
                self.strategy.leverage_min = exchange_max_leverage
                self.log.system(
                    f"leverage_min 클램핑: config={old}x → 거래소={exchange_max_leverage}x",
                    level="WARNING",
                )
                clamped = True
            if self.strategy.sideways_leverage_max > exchange_max_leverage:
                old = self.strategy.sideways_leverage_max
                self.strategy.sideways_leverage_max = exchange_max_leverage
                self.log.system(
                    f"sideways_leverage_max 클램핑: config={old}x → 거래소={exchange_max_leverage}x",
                    level="WARNING",
                )
                clamped = True
            if not clamped:
                self.log.system(
                    f"레버리지 검증 통과: max={self.strategy.leverage_max}x "
                    f"(거래소 한도={exchange_max_leverage}x)"
                )

        self.exchange.set_margin_mode(self.symbol, self.margin_mode)
        self.exchange.set_leverage(self.symbol, self.strategy.leverage_max)

    def _sync_balance(self):
        """거래소 잔고를 동기화한다.

        total 모드: 거래소 가용 잔고를 capital에 반영
        virtual 모드: 거래소 잔고는 로깅만, capital은 가상 자본 유지
        """
        try:
            balance = self.exchange.fetch_balance()
            usdt_free = float(balance.get("USDT", {}).get("free", 0))
            usdt_total = float(balance.get("USDT", {}).get("total", 0))

            if self.capital_mode == "virtual":
                self.log.asset(
                    f"잔고 동기화 [virtual]: 가상자본={self.capital:,.2f} USDT | "
                    f"실잔고: 가용={usdt_free:,.2f} 총={usdt_total:,.2f} USDT"
                )
            else:
                self.capital = usdt_free
                self.log.asset(f"잔고 동기화: 가용={usdt_free:,.2f} USDT, 총={usdt_total:,.2f} USDT")
        except Exception as e:
            self.log.asset(f"잔고 조회 실패: {e}", level="ERROR", exc_info=True)

    def _sync_position(self):
        """거래소 포지션을 동기화한다.

        거래소에 포지션이 없는데 내부 상태(self.position)에 포지션이 남아 있으면
        emergency stop 트리거 또는 강제청산(liquidation)으로 판단하고 내부 상태를
        초기화한다. (그렇지 않으면 다음 청산 시그널에서 -2022 reduceOnly 거절 발생)
        """
        try:
            positions = self.exchange.fetch_positions([self.symbol])
            pos_found = False
            if positions:
                pos = positions[0]
                side = pos.get("side", "")
                contracts = float(pos.get("contracts", 0))
                entry_price = float(pos.get("entryPrice", 0))
                leverage = int(pos.get("leverage") or 1)
                margin = float(pos.get("initialMargin", 0) or pos.get("collateral", 0))
                liq_price = float(pos.get("liquidationPrice", 0) or 0)

                if contracts > 0 and side:
                    pos_found = True
                    self.position.side = side
                    self.position.avg_price = entry_price
                    self.position.total_margin = margin
                    self.position.quantity = contracts
                    self.position.leverage = leverage
                    self.position.liquidation_price = liq_price
                    self.log.trade(
                        f"기존 포지션 감지: {side.upper()} 수량={contracts:.6f} "
                        f"평단={entry_price:,.2f} 마진={margin:,.2f} 레버={leverage}x "
                        f"청산가={liq_price:,.2f}"
                    )

            if not pos_found:
                if self.position.side:
                    prev_side = self.position.side
                    self.log.trade(
                        f"[포지션 불일치] 내부={prev_side.upper()} / 거래소=없음 "
                        f"→ 긴급손절(emergency stop) 또는 강제청산 감지. 내부 상태 초기화",
                        level="WARNING",
                    )
                    self._emergency_order_id = ""
                    self._long_step = 0
                    self._short_step = 0
                    self._entry_price = 0.0
                    self._total_weight = 0.0
                    self.position = LivePosition()
                    self._save_state()
                else:
                    self.log.trade("기존 포지션 없음")
        except Exception as e:
            self.log.trade(f"포지션 조회 실패: {e}", level="WARNING", exc_info=True)

    def _sync_funding_fees(self):
        """펀딩 수수료 내역을 조회하여 누적한다."""
        try:
            since = self._last_funding_ts + 1 if self._last_funding_ts else None
            history = self.exchange.fetch_funding_history(self.symbol, since=since)
            if not history:
                return

            new_funding = 0.0
            latest_ts = self._last_funding_ts
            for entry in history:
                amount = float(entry.get("amount", 0))
                ts = int(entry.get("timestamp", 0))
                new_funding += amount
                if ts > latest_ts:
                    latest_ts = ts

            if new_funding != 0:
                self._total_funding_fees += new_funding
                self._last_funding_ts = latest_ts
                self.log.asset(
                    f"펀딩 수수료 | 신규={new_funding:+,.4f} 누적={self._total_funding_fees:+,.4f}"
                )
        except Exception as e:
            self.log.asset(f"펀딩 수수료 조회 실패: {e}", level="WARNING", exc_info=True)

    # ------------------------------------------------------------------
    # Emergency Stop Order (서버사이드 비상 손절)
    # ------------------------------------------------------------------

    def _place_emergency_stop(self):
        """현재 포지션에 대한 비상 손절 주문을 거래소에 등록한다.

        포지션 진입/추매 시마다 호출하여 갱신한다.
        프로그램이 중단되어도 거래소 서버에서 손절이 실행된다.
        """
        if not self.position.side:
            return

        # 기존 emergency order가 있으면 취소
        self._cancel_emergency_stop()

        pos = self.position
        stoploss_pct = self.strategy.stoploss_pct

        # 손절가 계산
        if pos.side == "long":
            stop_price = pos.avg_price * (1 - stoploss_pct)
            order_side = "sell"
        else:
            stop_price = pos.avg_price * (1 + stoploss_pct)
            order_side = "buy"

        stop_price = self.exchange.price_to_precision(self.symbol, stop_price)
        quantity = self.exchange.amount_to_precision(self.symbol, pos.quantity)
        quantity = float(quantity)

        if quantity <= 0:
            return

        try:
            order = self.exchange.create_stop_market_order(
                self.symbol, order_side, quantity, float(stop_price),
            )
            self._emergency_order_id = order["id"]
            self.log.trade(
                f"비상 손절 등록 | {pos.side.upper()} | "
                f"평단={pos.avg_price:,.2f} 손절가={stop_price} "
                f"(-{stoploss_pct:.2%}) 수량={quantity:.6f} | 주문ID={order['id']}"
            )
        except Exception as e:
            self.log.trade(f"비상 손절 등록 실패: {e}", level="ERROR", exc_info=True)

    def _cancel_emergency_stop(self):
        """기존 비상 손절 주문을 취소한다."""
        if not self._emergency_order_id:
            return
        try:
            self.exchange.cancel_order(self._emergency_order_id, self.symbol)
            self.log.trade(f"비상 손절 취소: 주문ID={self._emergency_order_id}")
        except Exception as e:
            self.log.trade(f"비상 손절 취소 실패: {e}", level="WARNING")
        self._emergency_order_id = ""

    def _cleanup_existing_stop_orders(self):
        """재시작 시 기존에 걸려있는 STOP_MARKET 주문을 정리한다."""
        try:
            open_orders = self.exchange.fetch_open_orders(self.symbol)
            for order in open_orders:
                if order.get("type", "").upper() in ("STOP_MARKET", "STOP"):
                    order_id = order["id"]
                    self.exchange.cancel_order(order_id, self.symbol)
                    self.log.trade(f"기존 스톱 주문 정리: {order_id}")
        except Exception as e:
            self.log.trade(f"기존 스톱 주문 정리 실패: {e}", level="WARNING", exc_info=True)

    # ------------------------------------------------------------------
    # 추상 메서드 구현
    # ------------------------------------------------------------------

    def _execute_new_signals(self, signals: list[Signal]):
        for signal in signals:
            self.log.signal(f"시그널 실행 시도 | {signal.signal_type.value} | {signal.reason}", level="DEBUG")
            self._execute_signal(signal)

    def _get_current_price(self, df: pd.DataFrame) -> float:
        return df.iloc[-1]["close"]

    def _get_equity(self, price: float) -> float:
        unrealized = 0.0
        if self.position.side and price > 0:
            pos = self.position
            if pos.side == "long":
                pnl_pct = (price - pos.avg_price) / pos.avg_price
            else:
                pnl_pct = (pos.avg_price - price) / pos.avg_price
            unrealized = pos.total_margin * pnl_pct * pos.leverage
        return self.capital + self.position.total_margin + unrealized

    def _get_initial_capital(self) -> float:
        return self.initial_capital

    def _get_position_info(self, price: float) -> str:
        if not self.position.side:
            return "없음"
        pos = self.position
        if pos.side == "long":
            u_pct = (price - pos.avg_price) / pos.avg_price
        else:
            u_pct = (pos.avg_price - price) / pos.avg_price
        u_pnl = pos.total_margin * u_pct * pos.leverage

        info = (
            f"{pos.side.upper()} | 마진: {pos.total_margin:,.2f} USDT | "
            f"평단: {pos.avg_price:,.2f} | 수량: {pos.quantity:.6f} | "
            f"미실현: {u_pnl:+,.2f} USDT ({u_pct:+.2%})"
        )
        if pos.liquidation_price > 0:
            if pos.side == "long":
                liq_dist = (price - pos.liquidation_price) / price
            else:
                liq_dist = (pos.liquidation_price - price) / price
            info += f" | 청산가: {pos.liquidation_price:,.2f} ({liq_dist:+.2%})"
        return info

    def _get_trade_count(self) -> int:
        return len(self.trade_records)

    def _get_pnl_summary(self) -> dict:
        total_pnl = sum(r.pnl for r in self.trade_records)
        entries = sum(1 for r in self.trade_records if r.action in ("entry", "add"))
        exits = sum(1 for r in self.trade_records if r.action == "exit")
        return {
            "total_pnl": total_pnl,
            "entries": entries,
            "exits": exits,
            "trade_count": len(self.trade_records),
            "total_fees": self._total_fees,
            "total_funding_fees": self._total_funding_fees,
        }

    def _format_margin_info(self) -> str:
        mode_tag = " [가상자본]" if self.capital_mode == "virtual" else ""
        if self.margin_pct > 0:
            return f"마진=자본의 {self.margin_pct:.1%}{mode_tag}"
        return f"마진={self.max_margin_per_entry:,.2f} USDT/회 마진모드={self.margin_mode}{mode_tag}"

    # ------------------------------------------------------------------
    # 출력 커스터마이징
    # ------------------------------------------------------------------

    def _print_header_extra(self):
        if self._trade_quantity:
            print(f"  거래수량:   {self._trade_quantity} (코인단위, 고정)")
        if self.margin_pct > 0:
            print(f"  마진:       자본의 {self.margin_pct:.1%}")
        else:
            print(f"  마진상한:   {self.max_margin_per_entry:,.2f} USDT/회")
        print(f"  마진모드:   {self.margin_mode}")
        if self.capital_mode == "virtual":
            print(f"  자본모드:   가상자본 (실잔고 무시, 가상 {self.initial_capital:,.2f} USDT 기준)")
        if self.daily_loss_limit > 0:
            print(f"  일일손실제한: {self.daily_loss_limit:,.2f} USDT")

    def _print_header_footer(self):
        print(f"  ⚠ 실제 자금이 사용됩니다!")
        print(f"  Ctrl+C 로 중지 (포지션은 유지)")

    def _print_status_extra(self):
        fee_str = f"수수료: {self._total_fees:,.4f}" if self._total_fees else ""
        funding_str = f"펀딩: {self._total_funding_fees:+,.4f}" if self._total_funding_fees else ""
        extra = " | ".join(filter(None, [fee_str, funding_str]))
        extra_line = f" | {extra}" if extra else ""
        print(f"           거래: {len(self.trade_records)}건 | 일일PnL: {self._daily_pnl:+,.2f}{extra_line}")

    def _print_summary_body(self, summary: dict):
        print(f"  실현 손익:    {summary['total_pnl']:>+12,.2f} USDT")
        print(f"  거래 수수료:  {summary['total_fees']:>12,.4f} USDT")
        print(f"  펀딩 수수료:  {summary['total_funding_fees']:>+12,.4f} USDT")
        print(f"  진입 주문:    {summary['entries']:>12d}건")
        print(f"  청산 주문:    {summary['exits']:>12d}건")

        if self.position.side:
            pos = self.position
            print(f"\n  [미청산 포지션 — 거래소에 유지됨]")
            print(f"    방향: {pos.side.upper()}")
            print(f"    수량: {pos.quantity:.6f}")
            print(f"    평단: {pos.avg_price:,.2f}")
            print(f"    마진: {pos.total_margin:,.2f} USDT")
            if pos.liquidation_price > 0:
                print(f"    청산가: {pos.liquidation_price:,.2f}")

    def _save_summary_body(self, summary: dict):
        self.log.trade(f"총 거래: {summary['trade_count']}건")
        self.log.asset(f"실현 손익: {summary['total_pnl']:+,.2f} USDT")
        self.log.asset(f"거래 수수료: {summary['total_fees']:,.4f} USDT")
        self.log.asset(f"펀딩 수수료: {summary['total_funding_fees']:+,.4f} USDT")

        if self.position.side:
            pos = self.position
            self.log.trade(
                f"미청산 포지션: {pos.side.upper()} 수량={pos.quantity:.6f} "
                f"평단={pos.avg_price:,.2f} 마진={pos.total_margin:,.2f} "
                f"청산가={pos.liquidation_price:,.2f}"
            )

    def _save_trades_csv(self):
        if not self.trade_records:
            return
        ts = self._start_time.strftime("%H%M%S")
        safe_symbol = self.symbol.replace("/", "_")
        csv_dir = Path("data/trader") / safe_symbol
        csv_dir.mkdir(parents=True, exist_ok=True)
        csv_path = csv_dir / f"trades_{self.timeframe}_{ts}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "side", "action", "price", "quantity",
                "margin", "leverage", "order_id", "reason", "pnl", "fee",
            ])
            for r in self.trade_records:
                writer.writerow([
                    r.timestamp, r.side, r.action, r.price, r.quantity,
                    r.margin, r.leverage, r.order_id, r.reason, r.pnl, r.fee,
                ])

        self.log.trade(f"거래 내역 CSV: {csv_path}")

    # ------------------------------------------------------------------
    # 시그널 실행
    # ------------------------------------------------------------------

    def _execute_signal(self, signal: Signal):
        """시그널을 실제 주문으로 변환하여 실행한다."""
        # 일일 손실 제한 체크
        if self.daily_loss_limit > 0 and self._daily_pnl <= -self.daily_loss_limit:
            self.log.trade(
                f"일일 손실 제한으로 시그널 무시: {signal.signal_type.value} | "
                f"일일PnL={self._daily_pnl:+,.2f} (제한: -{self.daily_loss_limit:,.2f})",
                level="WARNING",
            )
            return

        sig_type = signal.signal_type

        if sig_type == SignalType.LONG_ENTRY:
            self._execute_entry("long", signal)
        elif sig_type == SignalType.SHORT_ENTRY:
            self._execute_entry("short", signal)
        elif sig_type == SignalType.LONG_EXIT:
            if self.position.side == "long":
                self._execute_exit(signal)
        elif sig_type == SignalType.SHORT_EXIT:
            if self.position.side == "short":
                self._execute_exit(signal)
        elif sig_type == SignalType.STOP_LOSS:
            if self.position.side:
                self._execute_exit(signal, is_stop=True)
        elif sig_type == SignalType.TAKE_PROFIT:
            if self.position.side:
                self._execute_exit(signal)

    def _execute_entry(self, side: str, signal: Signal):
        """포지션 진입/물타기 주문을 실행한다."""
        if self.capital <= 0:
            self.log.trade(f"진입 불가: 잔고 부족 (capital={self.capital:,.2f} USDT)", level="WARNING")
            return

        # 반대 포지션이면 먼저 청산
        if self.position.side and self.position.side != side:
            self.log.trade(f"반대 포지션 전환: {self.position.side} → {side}")
            self._execute_close(f"반대 포지션 전환 ({self.position.side} → {side})")

        # 마진 계산: margin_pct > 0이면 자본 대비 %, 아니면 고정 USDT
        margin = self.capital * signal.position_ratio
        if self.margin_pct > 0:
            max_margin = self.capital * self.margin_pct
        else:
            max_margin = self.max_margin_per_entry
        margin = min(margin, self.capital, max_margin)

        if margin <= 0:
            self.log.trade(
                f"진입 불가: 마진=0 (capital={self.capital:,.2f}, "
                f"ratio={signal.position_ratio}, max={max_margin:,.2f})",
                level="DEBUG",
            )
            return

        # 레버리지 설정 (시그널의 레버리지)
        self.exchange.set_leverage(self.symbol, signal.leverage)

        # 수량 계산: trade_quantity 지정 시 고정 수량, 아니면 마진 기반 계산
        if self._trade_quantity:
            quantity = self._trade_quantity
        else:
            quantity = (margin * signal.leverage) / signal.price
        quantity = self.exchange.amount_to_precision(self.symbol, quantity)
        quantity = float(quantity)

        if quantity < self._min_amount:
            self.log.trade(
                f"진입 불가: 수량={quantity:.6f} < 최소={self._min_amount} "
                f"(마진={margin:,.2f}, 레버={signal.leverage}x, 가격={signal.price:,.2f})",
                level="WARNING",
            )
            return

        # 최소 주문금액(notional) 검증
        notional = quantity * signal.price
        if self._min_cost > 0 and notional < self._min_cost:
            self.log.trade(
                f"진입 불가: notional={notional:,.2f} < 최소={self._min_cost:,.2f} USDT "
                f"(수량={quantity:.6f}, 가격={signal.price:,.2f})",
                level="WARNING",
            )
            return

        # 주문 실행
        order_side = "buy" if side == "long" else "sell"
        try:
            order = self.exchange.create_market_order(
                self.symbol, order_side, quantity,
            )
        except Exception as e:
            self.log.trade(f"진입 주문 실패: {e}", level="ERROR", exc_info=True)
            return

        fill_price = float(order.get("average") or order.get("price") or signal.price)
        fill_qty = float(order.get("filled", quantity))
        actual_margin = (fill_qty * fill_price) / signal.leverage

        # 수수료 추출
        fee_info = order.get("fee") or {}
        fee_cost = float(fee_info.get("cost", 0) or 0)
        self._total_fees += fee_cost

        # 포지션 상태 업데이트
        if not self.position.side:
            self.position = LivePosition(
                side=side,
                avg_price=fill_price,
                total_margin=actual_margin,
                quantity=fill_qty,
                leverage=signal.leverage,
                entry_steps=signal.entry_step,
                total_entry_fee=fee_cost,
            )
        else:
            # 물타기: 평균 단가 갱신
            old_notional = self.position.avg_price * self.position.quantity
            new_notional = fill_price * fill_qty
            total_qty = self.position.quantity + fill_qty
            self.position.avg_price = (old_notional + new_notional) / total_qty
            self.position.total_margin += actual_margin
            self.position.quantity = total_qty
            self.position.leverage = signal.leverage
            self.position.entry_steps = signal.entry_step
            self.position.total_entry_fee += fee_cost

        self.capital -= actual_margin + fee_cost

        action = "entry" if signal.entry_step <= 1 else "add"
        record = TradeRecord(
            timestamp=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            side=side,
            action=action,
            price=fill_price,
            quantity=fill_qty,
            margin=actual_margin,
            leverage=signal.leverage,
            order_id=order["id"],
            reason=signal.reason,
            fee=fee_cost,
        )
        self.trade_records.append(record)

        self._print_entry_signal(signal, order)
        self.log.trade(
            f"진입 체결 | {side.upper()} {action} {signal.entry_step}차 | "
            f"체결가={fill_price:,.2f} 수량={fill_qty:.6f} 마진={actual_margin:,.2f} "
            f"레버={signal.leverage}x 수수료={fee_cost:,.4f} | 주문ID={order['id']} | {signal.reason}"
        )
        self.log.asset(
            f"진입 후 자본: {self.capital:,.2f} USDT (마진={actual_margin:,.2f} 수수료={fee_cost:,.4f} 차감)"
        )
        self._save_trade_to_db(record, entry_step=signal.entry_step)
        self._save_asset_snapshot("entry", fill_price, f"{action} {signal.entry_step}차")
        self._place_emergency_stop()
        self._save_state()

    def _execute_exit(self, signal: Signal, is_stop: bool = False):
        """포지션 청산 주문을 실행한다."""
        if not self.position.side:
            return
        self._execute_close(signal.reason, signal)

    def _execute_close(self, reason: str, signal: Signal | None = None):
        """현재 포지션을 전량 청산한다."""
        if not self.position.side:
            return

        pos = self.position
        order_side = "sell" if pos.side == "long" else "buy"
        quantity = self.exchange.amount_to_precision(self.symbol, pos.quantity)
        quantity = float(quantity)

        if quantity <= 0:
            return

        try:
            order = self.exchange.create_market_order(
                self.symbol, order_side, quantity,
                params={"reduceOnly": True},
            )
        except Exception as e:
            err_str = str(e)
            if "-2022" in err_str or "ReduceOnly Order is rejected" in err_str:
                # 포지션이 이미 없는 경우 (emergency stop 트리거, 강제청산 등)
                self.log.trade(
                    "청산 주문 거절(-2022): 포지션이 이미 없을 가능성 있음. 거래소 동기화 실행",
                    level="WARNING",
                )
                self._sync_position()
                if not self.position.side:
                    # _sync_position에서 이미 내부 상태 초기화됨 → 조용히 종료
                    self.log.trade("포지션 없음 확인. 청산 주문 취소 (이미 청산됨)", level="WARNING")
                    return
            self.log.trade(f"청산 주문 실패: {e}", level="ERROR", exc_info=True)
            return

        fill_price = float(order.get("average") or order.get("price") or 0)

        # 수수료 추출
        fee_info = order.get("fee") or {}
        exit_fee = float(fee_info.get("cost", 0) or 0)
        self._total_fees += exit_fee
        total_fee = pos.total_entry_fee + exit_fee

        # PnL 계산 (수수료 포함)
        if pos.side == "long":
            pnl_pct = (fill_price - pos.avg_price) / pos.avg_price
        else:
            pnl_pct = (pos.avg_price - fill_price) / pos.avg_price
        gross_pnl = pos.total_margin * pnl_pct * pos.leverage
        pnl = gross_pnl - total_fee

        self.capital += pos.total_margin + gross_pnl - exit_fee
        self._daily_pnl += pnl

        record = TradeRecord(
            timestamp=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
            side=pos.side,
            action="exit",
            price=fill_price,
            quantity=float(quantity),
            margin=pos.total_margin,
            leverage=pos.leverage,
            order_id=order["id"],
            reason=reason,
            pnl=pnl,
            fee=exit_fee,
        )
        self.trade_records.append(record)

        pnl_color = "\033[32m" if pnl >= 0 else "\033[31m"
        print(
            f"  ■ 청산 {pos.side.upper()} | 체결가: {fill_price:>12,.2f} | "
            f"PnL: {pnl_color}{pnl:+,.2f} USDT ({pnl_pct:+.2%})\033[0m | "
            f"수수료: {total_fee:,.4f}"
        )
        print(f"           사유: {reason}")

        self.log.trade(
            f"청산 체결 | {pos.side.upper()} | 체결가={fill_price:,.2f} "
            f"수량={quantity} PnL={pnl:+,.2f}({pnl_pct:+.2%}) "
            f"수수료={total_fee:,.4f}(진입={pos.total_entry_fee:,.4f}+청산={exit_fee:,.4f}) | "
            f"주문ID={order['id']} | {reason}"
        )
        self.log.asset(
            f"청산 후 자본: {self.capital:,.2f} USDT | PnL={pnl:+,.2f} 일일PnL={self._daily_pnl:+,.2f}"
        )

        self._save_trade_to_db(
            record, pnl_pct=pnl_pct,
            funding_fee=self._total_funding_fees,
        )
        self._save_asset_snapshot("exit", fill_price, reason)

        self._cancel_emergency_stop()
        self.position = LivePosition()
        self._save_state()

    # ------------------------------------------------------------------
    # DB 저장
    # ------------------------------------------------------------------

    def _save_trade_to_db(self, record: TradeRecord, pnl_pct: float = 0.0,
                          unrealized_pnl: float = 0.0, unrealized_pnl_pct: float = 0.0,
                          funding_fee: float = 0.0, entry_step: int = 1):
        """매매 기록을 DB에 저장한다."""
        if not self._db:
            return
        try:
            self._db.save_trade(
                exchange=self.exchange_name,
                symbol=self.symbol,
                timeframe=self.timeframe,
                datetime_str=record.timestamp,
                side=record.side,
                action=record.action,
                price=record.price,
                quantity=record.quantity,
                amount=record.price * record.quantity,
                fee=record.fee,
                funding_fee=funding_fee,
                leverage=record.leverage,
                margin=record.margin,
                pnl=record.pnl,
                pnl_pct=pnl_pct,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_pct=unrealized_pnl_pct,
                order_id=record.order_id,
                reason=record.reason,
                entry_step=entry_step,
            )
        except Exception as e:
            self.log.system(f"DB 매매 기록 저장 실패: {e}", level="WARNING")

    def _save_asset_snapshot(self, event: str, price: float = 0.0, memo: str = ""):
        """자산 스냅샷을 DB에 저장한다."""
        if not self._db:
            return
        try:
            equity = self._get_equity(price) if price > 0 else self.capital
            u_pnl = 0.0
            realized = sum(r.pnl for r in self.trade_records)
            pos = self.position

            if pos.side and price > 0:
                if pos.side == "long":
                    u_pct = (price - pos.avg_price) / pos.avg_price
                else:
                    u_pct = (pos.avg_price - price) / pos.avg_price
                u_pnl = pos.total_margin * u_pct * pos.leverage

            self._db.save_asset_snapshot(
                exchange=self.exchange_name,
                symbol=self.symbol,
                datetime_str=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                event=event,
                balance=self.capital,
                equity=equity,
                position_side=pos.side,
                position_qty=pos.quantity,
                position_avg_price=pos.avg_price,
                position_margin=pos.total_margin,
                position_leverage=pos.leverage,
                unrealized_pnl=u_pnl,
                realized_pnl=realized,
                total_fees=self._total_fees,
                total_funding_fees=self._total_funding_fees,
                daily_pnl=self._daily_pnl,
                liquidation_price=pos.liquidation_price,
                memo=memo,
            )
        except Exception as e:
            self.log.system(f"DB 자산 스냅샷 저장 실패: {e}", level="WARNING")

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _print_entry_signal(self, signal: Signal, order: dict):
        """진입 시그널 체결을 출력한다."""
        label = self._SIGNAL_LABELS.get(signal.signal_type, signal.signal_type.value)
        fill_price = order.get("average") or order.get("price") or signal.price
        print(
            f"  {label}  체결가: {float(fill_price):>12,.2f}  "
            f"레버: {signal.leverage}x  주문ID: {order['id']}"
        )
        print(f"           사유: {signal.reason}")
