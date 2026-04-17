"""라이브 엔진 베이스 클래스.

LiveSimulator와 LiveTrader의 공통 로직을 추상 베이스 클래스로 통합한다.
틱 루프, 시그널 생성, 상태 추적, 로깅, 콘솔 출력을 제공한다.
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime

import pandas as pd

from src.exchange import ExchangeWrapper
from src.strategy import BBStrategy
from src.strategy.registry import create_strategy
from src.strategy.base import Signal, SignalType
from src.utils.log_manager import LogManager, HanLogger
from src.utils.timeframe import KST, TIMEFRAME_MS, resample_ohlcv


class LiveEngineBase(ABC):
    """라이브 트레이딩 엔진 베이스.

    시뮬레이터와 트레이더의 공통 로직을 제공한다.
    서브클래스는 시그널 실행, 상태 조회 메서드를 구현해야 한다.
    """

    # 서브클래스에서 오버라이드: 헤더 타이틀, 로그 파일 접두사
    _title: str = "라이브 엔진"
    _log_prefix: str = "live"

    def __init__(
        self,
        exchange: ExchangeWrapper,
        exchange_name: str,
        symbol: str,
        timeframe: str = "1h",
        lookback_candles: int = 100,
        log_dir: str = "data/live",
        strategy_kwargs: dict | None = None,
        strategy_name: str = "bb",
        # 전략 기본 파라미터 (strategy_kwargs 없을 때 사용)
        leverage_max: int = 50,
        leverage_min: int = 25,
        sideways_leverage_max: int = 15,
    ):
        self.exchange = exchange
        self.exchange_name = exchange_name
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback_candles = lookback_candles
        self.sync_timeframe: str | None = None  # 중간 동기화 TF (서브클래스에서 설정)

        # 전략 (레지스트리 기반 생성)
        if strategy_kwargs:
            self.strategy = create_strategy(strategy_name, **strategy_kwargs)
        else:
            self.strategy = create_strategy(
                strategy_name,
                timeframe=timeframe,
                leverage_max=leverage_max,
                leverage_min=leverage_min,
                sideways_leverage_max=sideways_leverage_max,
            )

        # 상태 추적
        self._last_candle_time: pd.Timestamp | None = None
        self._last_sync_candle_time: pd.Timestamp | None = None  # 중간 동기화용
        self._running = False
        self._tick_count = 0

        # 전략 포지션 상태 (generate_signals 내부 상태를 직접 관리)
        self._long_step = 0
        self._short_step = 0
        self._entry_price = 0.0
        self._total_weight = 0.0

        # 시작 시각
        self._start_time = datetime.now(KST)

        # 카테고리 로거 (거래소/심볼 바인딩 — 콘솔 + 파일 동시 출력)
        # 카테고리 로거 (거래소/심볼/모드 바인딩 — 콘솔 + 파일 동시 출력)
        # _log_prefix: 서브클래스에서 정의 ("sim" 또는 "trade")
        self.log: HanLogger = LogManager.instance().bind(exchange_name, symbol, mode=self._log_prefix)

    # ------------------------------------------------------------------
    # 메인 루프
    # ------------------------------------------------------------------

    def run(self, poll_interval: int | None = None):
        """엔진을 실행한다."""
        tf_ms = TIMEFRAME_MS.get(self.timeframe, 3600000)
        if poll_interval is None:
            poll_interval = max(10, tf_ms // 12000)

        self._running = True
        self._print_header()

        self.log.system(
            f"{self._title} 시작 | 거래소={self.exchange_name} "
            f"심볼={self.symbol} 타임프레임={self.timeframe} "
            f"{self._format_margin_info()} 폴링간격={poll_interval}초"
        )

        # 서브클래스별 시작 처리 (거래소 설정, 잔고 동기화 등)
        self._on_start()

        # 초기 데이터 로드 및 워밍업
        self._initialize()

        self.log.system(f"폴링 시작: {poll_interval}초 간격")

        try:
            while self._running:
                try:
                    self._tick()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self.log.system(f"틱 처리 오류: {e}", level="ERROR", exc_info=True)

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self._running = False
            print("\n")
            self.log.system(f"{self._title} 중지 (Ctrl+C)")
            self._on_stop()
            self._print_summary()
            self._save_summary()

    def stop(self):
        """엔진을 중지한다."""
        self._running = False

    # ------------------------------------------------------------------
    # 초기화
    # ------------------------------------------------------------------

    def _initialize(self):
        """초기 데이터를 로드하고 과거 캔들로 전략 상태를 워밍업한다.

        시작 시 실시간 ticker 가격을 반영하여 즉시 매매 판단을 수행한다.
        1) 과거 캔들로 전략/지표를 워밍업
        2) 마지막 캔들의 close를 현재 ticker 가격으로 갱신
        3) 갱신된 데이터로 시그널 생성 → 즉시 실행
        이를 통해 프로그램 재시작/접속 오류 복귀 시 최신 가격 기준으로 판단한다.
        """
        self.log.market(f"초기 데이터 로드: 최근 {self.lookback_candles}개 캔들")

        df = self._fetch_candles()
        if df.empty:
            self.log.market("초기 데이터 없음", level="WARNING")
            return

        self._last_candle_time = df.index[-1]

        # MTF 전략인 경우 인접 타임프레임 데이터 준비
        self._prepare_mtf_if_needed(df)

        # 1단계: 과거 캔들로 워밍업 (전략 내부 상태 동기화)
        signals = self._generate_signals_with_state(df)

        if signals:
            self.log.signal(
                f"워밍업 완료: {len(df)}캔들, {len(signals)}시그널 감지, "
                f"데이터범위={df.index[0]} ~ {df.index[-1]}"
            )

        # 2단계: 현재 ticker 가격으로 마지막 캔들 갱신 후 재판단
        ticker_price = self._get_ticker_price()
        if ticker_price > 0:
            last_close = df.iloc[-1]["close"]
            df.iloc[-1, df.columns.get_loc("close")] = ticker_price
            # high/low도 ticker 반영
            if ticker_price > df.iloc[-1]["high"]:
                df.iloc[-1, df.columns.get_loc("high")] = ticker_price
            if ticker_price < df.iloc[-1]["low"]:
                df.iloc[-1, df.columns.get_loc("low")] = ticker_price

            self.log.market(
                f"시작 시 실시간 가격 반영 | 캔들close={last_close:,.2f} → "
                f"ticker={ticker_price:,.2f}"
            )

            # 갱신된 데이터로 시그널 재생성
            signals = self._generate_signals_with_state(df)

        # 3단계: 마지막 캔들의 시그널 즉시 실행
        last_ts = df.index[-1]
        init_signals = [s for s in signals if s.timestamp == last_ts]
        if init_signals:
            self.log.signal(
                f"시작 시 즉시 시그널 실행 | {len(init_signals)}건 | "
                f"캔들={last_ts} | ticker={ticker_price:,.2f}"
            )
            self._execute_new_signals(init_signals)

        self._on_initialized()

    # ------------------------------------------------------------------
    # 틱 처리
    # ------------------------------------------------------------------

    def _tick(self):
        """한 번의 폴링 사이클을 처리한다."""
        self._on_tick_start()

        df = self._fetch_candles()
        if df.empty:
            return

        latest_time = df.index[-1]

        # 새 캔들이 완성되었는지 확인
        if self._last_candle_time is not None and latest_time <= self._last_candle_time:
            # 메인 캔들 미갱신 → 중간 동기화 체크
            self._check_sync_tick()
            return

        self._last_candle_time = latest_time
        self._tick_count += 1

        row = df.iloc[-1]
        self.log.market(
            f"새 캔들 | {latest_time} | O={row['open']:,.2f} H={row['high']:,.2f} "
            f"L={row['low']:,.2f} C={row['close']:,.2f} V={row['volume']:,.2f}"
        )

        # MTF 데이터 갱신 (새 캔들마다)
        self._prepare_mtf_if_needed(df)

        # 전략으로 시그널 생성
        signals = self._generate_signals_with_state(df)

        if not signals:
            self.log.signal("시그널 없음 | 전략이 전체 기간에서 시그널 0건 생성", level="DEBUG")
            self._print_status(self._get_current_price(df), new_candle=True)
            self._log_status(self._get_current_price(df))
            return

        # 마지막 캔들에서 발생한 시그널만 처리
        last_ts = df.index[-1]
        new_signals = [s for s in signals if s.timestamp == last_ts]

        self.log.signal(
            f"시그널 현황 | 전체={len(signals)}건, 현재캔들={len(new_signals)}건 "
            f"(L{self._long_step}단계 S{self._short_step}단계 진입가={self._entry_price:,.2f})",
            level="DEBUG",
        )

        if not new_signals:
            self.log.signal(
                f"현재 캔들 시그널 없음 | 마지막 시그널: {signals[-1].reason}",
                level="DEBUG",
            )
            self._print_status(self._get_current_price(df), new_candle=True)
            self._log_status(self._get_current_price(df))
            return

        # 서브클래스에서 구현하는 시그널 실행
        self._execute_new_signals(new_signals)

        price = self._get_current_price(df)
        self._print_status(price, new_candle=True)
        self._log_status(price)

        self._on_tick_end()

    # ------------------------------------------------------------------
    # 중간 동기화
    # ------------------------------------------------------------------

    def _check_sync_tick(self):
        """sync_timeframe이 설정된 경우, 해당 TF 캔들 갱신 시 동기화 훅을 호출한다."""
        if not self.sync_timeframe:
            return

        try:
            df_sync = self.exchange.fetch_ohlcv(
                self.symbol, self.sync_timeframe, limit=2,
            )
        except Exception as e:
            self.log.market(f"동기화 캔들 조회 실패: {e}", level="DEBUG")
            return

        if df_sync.empty:
            return

        sync_time = df_sync.index[-1]
        if self._last_sync_candle_time is not None and sync_time <= self._last_sync_candle_time:
            return

        self._last_sync_candle_time = sync_time
        self.log.market(
            f"중간 동기화 | {self.sync_timeframe} 캔들 갱신 ({sync_time})"
        )
        self._on_sync_tick()

    # ------------------------------------------------------------------
    # 데이터 & 전략
    # ------------------------------------------------------------------

    def _prepare_mtf_if_needed(self, df: pd.DataFrame):
        """BBMTFStrategy인 경우 인접 타임프레임 데이터를 준비한다."""
        from src.strategy.bb_mtf_strategy import BBMTFStrategy
        if not isinstance(self.strategy, BBMTFStrategy):
            return

        df_lower = None
        df_upper = None

        # 상위 TF: 기준 TF 데이터에서 리샘플링
        if self.strategy.upper_tf:
            try:
                df_upper = resample_ohlcv(df, self.strategy.upper_tf)
                self.log.signal(f"MTF 상위 TF({self.strategy.upper_tf}): {len(df_upper)}캔들")
            except Exception as e:
                self.log.signal(f"MTF 상위 TF 준비 실패: {e}", level="WARNING")

        # 하위 TF: 거래소에서 직접 가져오기
        if self.strategy.lower_tf:
            try:
                df_lower = self.exchange.fetch_ohlcv(
                    self.symbol, self.strategy.lower_tf,
                    limit=self.lookback_candles * 2,
                )
                if not df_lower.empty:
                    self.log.signal(f"MTF 하위 TF({self.strategy.lower_tf}): {len(df_lower)}캔들")
            except Exception as e:
                self.log.signal(f"MTF 하위 TF 데이터 수신 실패: {e}", level="WARNING")

        self.strategy.prepare_mtf_data(df_lower=df_lower, df_upper=df_upper)

    def _fetch_candles(self) -> pd.DataFrame:
        """거래소에서 최근 캔들 데이터를 가져온다."""
        try:
            return self.exchange.fetch_ohlcv(
                self.symbol, self.timeframe, limit=self.lookback_candles,
            )
        except Exception as e:
            self.log.system(f"데이터 수신 실패: {e}", level="ERROR", exc_info=True)
            return pd.DataFrame()

    def _generate_signals_with_state(self, df: pd.DataFrame) -> list[Signal]:
        """전략의 내부 상태를 유지하면서 시그널을 생성한다."""
        signals = self.strategy.generate_signals(df)

        long_step = 0
        short_step = 0
        entry_price = 0.0
        total_weight = 0.0

        for sig in signals:
            long_step, short_step, entry_price, total_weight = (
                self.strategy._update_position(
                    sig, long_step, short_step, entry_price, total_weight,
                )
            )

        self._long_step = long_step
        self._short_step = short_step
        self._entry_price = entry_price
        self._total_weight = total_weight

        return signals

    # ------------------------------------------------------------------
    # 출력 (공통)
    # ------------------------------------------------------------------

    _SIGNAL_LABELS = {
        SignalType.LONG_ENTRY: "\033[32m▲ LONG 진입\033[0m",
        SignalType.SHORT_ENTRY: "\033[31m▼ SHORT 진입\033[0m",
        SignalType.LONG_EXIT: "\033[33m■ LONG 청산\033[0m",
        SignalType.SHORT_EXIT: "\033[33m■ SHORT 청산\033[0m",
        SignalType.STOP_LOSS: "\033[31m✖ 손절\033[0m",
        SignalType.TAKE_PROFIT: "\033[32m★ 익절\033[0m",
    }

    def _print_header(self):
        """헤더를 출력한다."""
        sep = "=" * 72
        print(sep)
        print(f"  HanTrader {self._title}")
        print(sep)
        print(f"  거래소:     {self.exchange_name}")
        print(f"  심볼:       {self.symbol}")
        print(f"  타임프레임: {self.timeframe}")
        self._print_header_extra()
        print(sep)
        self._print_header_footer()
        print(sep)
        print()

    def _print_signal(self, signal: Signal):
        """시그널 발생을 출력한다."""
        label = self._SIGNAL_LABELS.get(signal.signal_type, signal.signal_type.value)
        ts = signal.timestamp.strftime("%Y-%m-%d %H:%M")
        print(f"  [{ts}] {label}  가격: {signal.price:>12,.2f}  "
              f"레버: {signal.leverage}x")
        print(f"           사유: {signal.reason}")

    def _print_status(self, price: float, new_candle: bool = False):
        """현재 상태를 출력한다."""
        equity = self._get_equity(price)
        initial = self._get_initial_capital()
        pnl = equity - initial
        pnl_pct = pnl / initial if initial > 0 else 0

        pos_str = self._get_position_info(price)
        now = datetime.now(KST).strftime("%H:%M:%S")

        if new_candle:
            print(f"\n  ─── 새 캔들 ({self._last_candle_time.strftime('%Y-%m-%d %H:%M')}) "
                  f"{'─' * 40}")

        pnl_color = "\033[32m" if pnl >= 0 else "\033[31m"
        print(f"  [{now}] 가격: {price:>12,.2f} | "
              f"자본: {equity:>10,.2f} USDT | "
              f"PnL: {pnl_color}{pnl:+,.2f} ({pnl_pct:+.2%})\033[0m")
        print(f"           포지션: {pos_str}")
        self._print_status_extra()

    def _log_status(self, price: float):
        """현재 상태를 로그에 기록한다."""
        equity = self._get_equity(price)
        initial = self._get_initial_capital()
        pnl = equity - initial
        pnl_pct = pnl / initial if initial > 0 else 0
        pos_str = self._get_position_info(price)

        self.log.asset(
            f"상태 | 가격={price:,.2f} 자본={equity:,.2f} PnL={pnl:+,.2f}({pnl_pct:+.2%}) "
            f"포지션={pos_str} 거래={self._get_trade_count()}건"
        )

    def _print_summary(self):
        """종료 시 요약을 출력한다."""
        summary = self._get_pnl_summary()

        sep = "=" * 72
        print(sep)
        print(f"  {self._title} 종료 요약")
        print(sep)
        self._print_summary_body(summary)
        print(sep)

    def _save_summary(self):
        """종료 시 요약을 로그에 기록한다."""
        elapsed = datetime.now(KST) - self._start_time
        summary = self._get_pnl_summary()

        self.log.system(f"{self._title} 종료 요약 | 실행시간={elapsed} 캔들={self._tick_count}개")
        self._save_summary_body(summary)
        self._save_trades_csv()

    # ------------------------------------------------------------------
    # 추상/훅 메서드 — 서브클래스에서 구현
    # ------------------------------------------------------------------

    @abstractmethod
    def _execute_new_signals(self, signals: list[Signal]):
        """새 시그널을 실행한다. 시뮬레이터는 BacktestEngine, 트레이더는 거래소 API."""
        ...

    @abstractmethod
    def _get_current_price(self, df: pd.DataFrame) -> float:
        """현재 가격을 반환한다."""
        ...

    @abstractmethod
    def _get_equity(self, price: float) -> float:
        """현재 equity(총자산)를 계산한다."""
        ...

    @abstractmethod
    def _get_initial_capital(self) -> float:
        """초기 자본금을 반환한다."""
        ...

    @abstractmethod
    def _get_position_info(self, price: float) -> str:
        """현재 포지션 정보 문자열을 반환한다."""
        ...

    @abstractmethod
    def _get_trade_count(self) -> int:
        """완료된 거래 수를 반환한다."""
        ...

    @abstractmethod
    def _get_pnl_summary(self) -> dict:
        """종료 요약에 사용할 PnL 정보를 반환한다."""
        ...

    @abstractmethod
    def _format_margin_info(self) -> str:
        """마진 설정 정보 문자열을 반환한다."""
        ...

    def _get_ticker_price(self) -> float:
        """거래소 ticker에서 현재가를 가져온다."""
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            return float(ticker.get("last", 0))
        except Exception:
            return 0.0

    def _on_start(self):
        """run() 시작 직후 호출. 서브클래스에서 거래소 설정 등 수행."""
        pass

    def _on_stop(self):
        """종료 직전 호출. 서브클래스에서 정리 작업 수행."""
        pass

    def _on_initialized(self):
        """초기 워밍업 완료 후 호출."""
        pass

    def _on_tick_start(self):
        """매 틱 시작 시 호출. 트레이더: 일일 손실 리셋 등."""
        pass

    def _on_tick_end(self):
        """매 틱 종료 시 호출. 트레이더: 주기적 동기화 등."""
        pass

    def _on_sync_tick(self):
        """중간 동기화 틱. sync_timeframe 캔들 갱신 시 호출."""
        pass

    def _print_header_extra(self):
        """헤더에 추가 정보를 출력한다."""
        pass

    def _print_header_footer(self):
        """헤더 하단 메시지를 출력한다."""
        print(f"  Ctrl+C 로 중지")

    def _print_status_extra(self):
        """상태 출력에 추가 정보를 출력한다."""
        pass

    @abstractmethod
    def _print_summary_body(self, summary: dict):
        """종료 요약의 본문을 출력한다."""
        ...

    @abstractmethod
    def _save_summary_body(self, summary: dict):
        """종료 요약의 본문을 로그에 기록한다."""
        ...

    def _save_trades_csv(self):
        """거래 내역을 CSV로 저장한다. 서브클래스에서 구현."""
        pass
