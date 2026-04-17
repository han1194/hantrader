"""HanTrader - 자동매매 봇 시스템 메인 엔트리포인트."""

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys

from src.backtest import BacktestEngine, BacktestEvaluator, BacktestReport
from src.collector import DataCollector
from src.config import AppConfig
from src.exchange import create_exchange, create_authenticated_exchange
from src.simulator import LiveSimulator
from src.trader import LiveTrader
from src.storage import DatabaseStorage, CSVExporter
from src.strategy import BBStrategy
from src.strategy.registry import create_strategy
from src.utils.log_manager import LogManager


def _load_env(env_path: str = ".env"):
    """간단한 .env 파일 로더 (python-dotenv 의존 없이)."""
    path = Path(env_path)
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                os.environ.setdefault(key, value)


def _normalize_symbol(raw: str) -> str:
    """심볼 입력을 정규화한다. btc, BTC, btc/usdt, BTC/USDT → BTC/USDT"""
    s = raw.strip().upper().replace("_", "/")
    if "/" not in s:
        s = s + "/USDT"
    return s


def _normalize_symbols(raw: str) -> list[str]:
    """쉼표 구분 심볼 문자열을 정규화된 리스트로 반환한다."""
    return [_normalize_symbol(s) for s in raw.split(",")]


def _create_strategy(cfg: AppConfig, strategy_kwargs: dict):
    """설정의 전략 이름에 따라 전략 인스턴스를 생성한다."""
    return create_strategy(cfg.strategy.name, **strategy_kwargs)


def _prepare_mtf_data(strategy, df, db, exchange, symbol, cfg, start=None, end=None):
    """BBMTFStrategy에 필요한 인접 타임프레임 데이터를 준비한다.

    상위 TF: 기준 TF OHLCV에서 리샘플링
    하위 TF: 5m 데이터에서 리샘플링
    """
    if not hasattr(strategy, "prepare_mtf_data"):
        return

    from src.utils.timeframe import resample_ohlcv

    log = LogManager.instance().bind()
    df_lower = None
    df_upper = None

    # 상위 TF: 기준 TF OHLCV에서 리샘플링
    if strategy.upper_tf:
        try:
            df_upper = resample_ohlcv(df, strategy.upper_tf)
            log.info(f"MTF 상위 TF({strategy.upper_tf}) 데이터: {len(df_upper)}캔들")
        except Exception as e:
            log.warning(f"MTF 상위 TF 리샘��링 실패: {e}")

    # 하위 TF: 5m 데이터에서 리샘플링
    if strategy.lower_tf:
        base_tf = cfg.collector.base_timeframe
        df_5m = db.load_ohlcv(exchange, symbol, base_tf, start=start, end=end)
        if not df_5m.empty:
            try:
                if strategy.lower_tf == base_tf:
                    df_lower = df_5m
                else:
                    df_lower = resample_ohlcv(df_5m, strategy.lower_tf)
                log.info(f"MTF 하위 TF({strategy.lower_tf}) 데이터: {len(df_lower)}캔들")
            except Exception as e:
                log.warning(f"MTF 하위 TF 리샘플링 실패: {e}")
        else:
            log.warning(f"MTF 하위 TF용 {base_tf} 데이터 없음")

    strategy.prepare_mtf_data(df_lower=df_lower, df_upper=df_upper)


def cmd_collect(args, cfg: AppConfig):
    """데이터 수집 커맨드."""
    collector = DataCollector(args.config)

    symbols = None
    if args.symbols:
        symbols = _normalize_symbols(args.symbols)

    collector.collect(
        exchange_name=args.exchange,
        symbols=symbols,
        start=args.start,
        end=args.end,
    )


def cmd_strategy(args, cfg: AppConfig):
    """전략 시그널 생성 커맨드."""
    bt = cfg.backtest
    db = DatabaseStorage(cfg.storage.db_path)

    timeframe = args.timeframe or bt.timeframe
    leverage_max = args.leverage_max or bt.leverage_max
    leverage_min = args.leverage_min or bt.leverage_min

    strategy_kwargs = cfg.strategy.to_strategy_kwargs(
        timeframe=timeframe,
        leverage_max=leverage_max,
        leverage_min=leverage_min,
        sideways_leverage_max=bt.sideways_leverage_max,
    )
    strategy = _create_strategy(cfg, strategy_kwargs)

    exchange = args.exchange
    symbol = _normalize_symbol(args.symbol)

    log = LogManager.instance().bind()
    log.info(f"전략 실행: {exchange}/{symbol} ({strategy.timeframe})")

    df = db.load_ohlcv(exchange, symbol, strategy.timeframe)
    if df.empty:
        log.warning(f"데이터 없음: {exchange}/{symbol}/{strategy.timeframe}")
        log.info("먼저 'collect' 명령으로 데이터를 수집하세요.")
        return

    _prepare_mtf_data(strategy, df, db, exchange, symbol, cfg)
    signals = strategy.generate_signals(df)
    signals_df = strategy.signals_to_dataframe(signals)

    if signals_df.empty:
        log.info("생성된 시그널이 없습니다.")
        return

    print(f"\n{'='*80}")
    print(f"전략: {strategy.name} | {exchange}/{symbol} | {strategy.timeframe}")
    print(f"기간: {df.index[0]} ~ {df.index[-1]}")
    print(f"시그널 수: {len(signals_df)}")
    print(f"{'='*80}")
    print(signals_df.to_string())

    if cfg.storage.csv_enabled:
        exporter = CSVExporter(cfg.storage.csv_output_dir)
        safe_symbol = symbol.replace("/", "_")
        filepath = exporter.output_dir / f"signals_{exchange}_{safe_symbol}_{strategy.timeframe}.csv"
        signals_df.to_csv(filepath)
        log.info(f"시그널 CSV 저장: {filepath}")


def cmd_backtest(args, cfg: AppConfig):
    """백테스트 실행 커맨드."""
    bt = cfg.backtest
    db = DatabaseStorage(cfg.storage.db_path)

    exchange = args.exchange
    symbols = _normalize_symbols(args.symbol)
    timeframe = args.timeframe or bt.timeframe
    initial_capital = args.capital or bt.initial_capital
    min_investment = args.min_investment or bt.min_investment
    leverage_max = args.leverage_max or bt.leverage_max
    leverage_min = args.leverage_min or bt.leverage_min

    log = LogManager.instance().bind()

    for symbol in symbols:
        log.info(
            f"백테스트 시작: {exchange}/{symbol} ({timeframe}) "
            f"레버리지: {leverage_min}~{leverage_max} (횡보장≤{bt.sideways_leverage_max})"
        )

        # 1. 데이터 로드 (지표 워밍업용 추가 데이터 포함)
        warmup_start = None
        if args.start:
            from src.utils.timeframe import TIMEFRAME_MS
            tf_ms = TIMEFRAME_MS.get(timeframe, 3600000)
            warmup_ms = bt.warmup_candles * tf_ms
            start_dt = datetime.fromisoformat(args.start)
            warmup_dt = start_dt - timedelta(milliseconds=warmup_ms)
            warmup_start = warmup_dt.strftime("%Y-%m-%d")
            log.info(f"지표 워밍업: {warmup_start} ~ {args.start} ({bt.warmup_candles}캔들)")

        load_start = warmup_start if warmup_start else args.start

        df = db.load_ohlcv(exchange, symbol, timeframe, start=load_start, end=args.end)
        if df.empty:
            base_tf = cfg.collector.base_timeframe
            log.info(f"{timeframe} 데이터 없음, {base_tf}에서 리샘플링 시도")
            from src.utils.timeframe import resample_ohlcv
            df_base = db.load_ohlcv(exchange, symbol, base_tf, start=load_start, end=args.end)
            if not df_base.empty:
                df = resample_ohlcv(df_base, timeframe)
            if df.empty:
                log.warning(f"데이터 없음: {exchange}/{symbol}/{timeframe}")
                log.info("먼저 'collect' 명령으로 데이터를 수집하세요.")
                continue

        # 2. 시그널 생성
        strategy_kwargs = cfg.strategy.to_strategy_kwargs(
            timeframe=timeframe,
            leverage_max=leverage_max,
            leverage_min=leverage_min,
            sideways_leverage_max=bt.sideways_leverage_max,
        )
        strategy = _create_strategy(cfg, strategy_kwargs)
        _prepare_mtf_data(
            strategy, df, db, exchange, symbol, cfg,
            start=load_start, end=args.end,
        )
        signals = strategy.generate_signals(df)

        # 3. 워밍업 구간 제거
        if args.start:
            import pandas as pd
            bt_start = pd.Timestamp(args.start)
            signals = [s for s in signals if s.timestamp >= bt_start]
            df = df[df.index >= bt_start]

        if not signals:
            log.info(f"{symbol}: 생성된 시그널이 없습니다.")
            continue

        # 4. 백테스트 실행
        engine = BacktestEngine(
            initial_capital=initial_capital,
            min_investment=min_investment,
            max_margin_per_entry=bt.max_margin_per_entry,
            margin_pct=bt.margin_pct,
            exchange=exchange,
            symbol=symbol,
        )
        trades = engine.run(signals, df)
        equity_df = engine.get_equity_df()
        trades_df = engine.get_trades_df()

        # 5. 평가
        evaluator = BacktestEvaluator()
        metrics = evaluator.evaluate(trades, equity_df, initial_capital)

        # 6. 리포트 생성
        report = BacktestReport(output_dir=bt.output_dir)

        text = report.generate_text(
            metrics, trades, exchange, symbol, timeframe,
            strategy_config=cfg.strategy, backtest_config=bt,
        )
        print(text)
        report.save_text(text, exchange, symbol, timeframe)

        if not trades_df.empty:
            report.save_trades_csv(trades_df, exchange, symbol, timeframe)

        if not equity_df.empty:
            dashboard_path = report.generate_dashboard(
                metrics, trades, equity_df, exchange, symbol, timeframe,
                strategy_config=cfg.strategy, backtest_config=bt,
            )
            log.info(f"대시보드: file:///{dashboard_path.resolve()}")

        if len(symbols) > 1:
            print(f"\n{'='*80}\n")


def cmd_simulate(args, cfg: AppConfig):
    """라이브 시뮬레이터 실행 커맨드."""
    exc_name = args.exchange
    exc_config = cfg.exchanges.get(exc_name)
    if not exc_config:
        print(f"거래소를 찾을 수 없음: {exc_name}")
        return

    exchange = create_exchange(exc_config.type, exc_config.options or None)

    # 설정 해석: simulator → backtest 폴백
    resolved = cfg.simulator.resolve(cfg.backtest)

    timeframe = args.timeframe or resolved["timeframe"]
    initial_capital = args.capital or resolved["initial_capital"]
    leverage_max = args.leverage_max or resolved["leverage_max"]
    leverage_min = args.leverage_min or resolved["leverage_min"]

    strategy_kwargs = cfg.strategy.to_strategy_kwargs(
        timeframe=timeframe,
        leverage_max=leverage_max,
        leverage_min=leverage_min,
        sideways_leverage_max=resolved["sideways_leverage_max"],
    )

    simulator = LiveSimulator(
        exchange=exchange,
        exchange_name=exc_name,
        symbol=_normalize_symbol(args.symbol),
        timeframe=timeframe,
        initial_capital=initial_capital,
        min_investment=resolved["min_investment"],
        max_margin_per_entry=resolved["max_margin_per_entry"],
        margin_pct=resolved["margin_pct"],
        lookback_candles=resolved["lookback_candles"],
        log_dir=resolved["log_dir"],
        strategy_kwargs=strategy_kwargs,
        strategy_name=cfg.strategy.name,
    )

    simulator.run(poll_interval=args.interval)


def cmd_trade(args, cfg: AppConfig):
    """실거래 트레이더 실행 커맨드."""
    exc_name = args.exchange
    exc_config = cfg.exchanges.get(exc_name)
    if not exc_config:
        print(f"거래소를 찾을 수 없음: {exc_name}")
        return

    # 인증 거래소 생성 (ExchangeConfig.auth 환경변수에서 API 키 로드)
    try:
        exchange = create_authenticated_exchange(exc_config)
    except ValueError as e:
        print("=" * 60)
        print(f"  오류: {e}")
        print()
        print("  1. .env.example 파일을 .env로 복사하세요:")
        print("     cp .env.example .env")
        print()
        print("  2. .env 파일에 API 키를 입력하세요.")
        print("=" * 60)
        return

    testnet = (
        os.environ.get(exc_config.testnet_env, "false").lower() == "true"
        if exc_config.testnet_env
        else False
    )

    # 설정 해석 (코인별 오버라이드 적용)
    symbol = _normalize_symbol(args.symbol)
    resolved = cfg.trader.resolve_for_symbol(cfg.backtest, symbol)

    timeframe = args.timeframe or resolved["timeframe"]
    # --capital 명시 여부로 상태 복원 판단
    capital_explicit = args.capital is not None
    initial_capital = args.capital or resolved["initial_capital"]
    leverage_max = args.leverage_max or resolved["leverage_max"]
    leverage_min = args.leverage_min or resolved["leverage_min"]
    margin_pct = resolved["margin_pct"]
    max_margin = resolved["max_margin_per_entry"]
    trade_quantity = resolved.get("trade_quantity")
    sync_timeframe = resolved.get("sync_timeframe")
    capital_mode = getattr(args, "capital_mode", None) or resolved.get("capital_mode", "total")

    strategy_kwargs = cfg.strategy.to_strategy_kwargs(
        timeframe=timeframe,
        leverage_max=leverage_max,
        leverage_min=leverage_min,
        sideways_leverage_max=resolved["sideways_leverage_max"],
    )

    # 코인별 오버라이드 여부 확인
    has_override = symbol in cfg.trader.symbol_overrides

    if testnet:
        print("\n  [테스트넷 모드]")
    else:
        print("\n" + "!" * 60)
        print(f"  ⚠  실거래 모드 — 실제 자금이 사용됩니다!")
        print(f"  거래소: {exc_name}")
        print(f"  심볼:   {symbol}" + (" (코인별 설정 적용)" if has_override else ""))
        print(f"  타임프레임: {timeframe}" + (f" (동기화: {sync_timeframe})" if sync_timeframe else ""))
        print(f"  레버리지: {leverage_min}~{leverage_max}")
        if trade_quantity:
            print(f"  거래수량: {trade_quantity} (코인단위)")
        if margin_pct > 0:
            print(f"  마진: 자본의 {margin_pct:.1%}")
        else:
            print(f"  마진상한: {max_margin} USDT/회")
        if capital_mode == "virtual":
            print(f"  자본모드: 가상자본 (실잔고 무시, 가상 자본 기준 마진 계산)")
        if capital_explicit:
            print(f"  초기자본: {initial_capital} USDT (명시 — 상태 초기화)")
        else:
            print(f"  초기자본: {initial_capital} USDT (상태 파일에서 복원 시도)")
        print("!" * 60)
        confirm = input("\n  계속하시겠습니까? (yes를 입력): ").strip()
        if confirm != "yes":
            print("  취소되었습니다.")
            return

    db = DatabaseStorage(cfg.storage.db_path)

    trader_kwargs = dict(
        exchange=exchange,
        exchange_name=exc_name,
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=initial_capital,
        max_margin_per_entry=max_margin,
        margin_pct=margin_pct,
        margin_mode=resolved["margin_mode"],
        capital_mode=capital_mode,
        daily_loss_limit=args.daily_loss_limit or resolved["daily_loss_limit"],
        lookback_candles=resolved["lookback_candles"],
        log_dir=resolved["log_dir"],
        strategy_kwargs=strategy_kwargs,
        strategy_name=cfg.strategy.name,
        restore_state=not capital_explicit,
        db=db,
    )
    if trade_quantity:
        trader_kwargs["trade_quantity"] = trade_quantity

    trader = LiveTrader(**trader_kwargs)
    if sync_timeframe:
        trader.sync_timeframe = sync_timeframe

    trader.run(poll_interval=args.interval)


def cmd_export(args, cfg: AppConfig):
    """DB 데이터를 CSV로 내보내기 커맨드."""
    db = DatabaseStorage(cfg.storage.db_path)

    exchange = args.exchange
    symbol = _normalize_symbol(args.symbol)
    timeframe = args.timeframe or "1h"
    output_dir = args.output or cfg.storage.csv_output_dir

    log = LogManager.instance().bind()

    df = db.load_ohlcv(exchange, symbol, timeframe, start=args.start, end=args.end)

    if df.empty:
        base_tf = cfg.collector.base_timeframe
        log.info(f"{timeframe} 데이터 없음, {base_tf}에서 리샘플링 시도")
        df_base = db.load_ohlcv(exchange, symbol, base_tf, start=args.start, end=args.end)
        if df_base.empty:
            log.warning(f"데이터 없음: {exchange}/{symbol}/{base_tf}")
            log.info("먼저 'collect' 명령으로 데이터를 수집하세요.")
            return
        from src.utils.timeframe import resample_ohlcv
        df = resample_ohlcv(df_base, timeframe)
        if df.empty:
            log.warning(f"리샘플링 결과 없음: {timeframe}")
            return

    exporter = CSVExporter(output_dir)
    filepath = exporter.export(df, exchange, symbol, timeframe)
    log.info(f"CSV 내보내기 완료: {filepath} ({len(df)}건)")
    print(f"\nCSV 저장: {filepath} ({len(df)}건)")
    print(f"기간: {df.index[0]} ~ {df.index[-1]}")


def cmd_list_exchanges(args, cfg: AppConfig):
    """지원 거래소 목록 출력."""
    from src.exchange import ExchangeWrapper
    print("지원 거래소 목록:")
    for exc in ExchangeWrapper.list_exchanges():
        print(f"  - {exc}")


def main():
    parser = argparse.ArgumentParser(
        prog="hantrader",
        description="HanTrader - 자동매매 봇 시스템",
    )
    parser.add_argument("--config", default="config/config.yaml", help="설정 파일 경로")
    parser.add_argument("--log-level", default=None, help="로그 레벨 (DEBUG, INFO, WARNING, ERROR)")

    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # collect 명령어
    collect_parser = subparsers.add_parser("collect", help="시장 데이터 수집")
    collect_parser.add_argument("--exchange", "-e", help="거래소 이름 (config에 정의된 이름)")
    collect_parser.add_argument("--symbols", "-s", help="심볼 목록 (쉼표 구분, 예: BTC/USDT,ETH/USDT)")
    collect_parser.add_argument("--start", help="시작일 (ISO format, 예: 2024-01-01)")
    collect_parser.add_argument("--end", help="종료일 (ISO format)")

    # strategy 명령어
    strategy_parser = subparsers.add_parser("strategy", help="전략 시그널 생성")
    strategy_parser.add_argument("--exchange", "-e", required=True, help="거래소 이름")
    strategy_parser.add_argument("--symbol", "-s", required=True, help="심볼 (예: BTC/USDT)")
    strategy_parser.add_argument("--timeframe", "-t", default=None, help="타임프레임 (기본: config값)")
    strategy_parser.add_argument("--leverage-max", type=int, default=None, help="최대 레버리지")
    strategy_parser.add_argument("--leverage-min", type=int, default=None, help="최소 레버리지")

    # backtest 명령어
    bt_parser = subparsers.add_parser("backtest", help="백테스트 실행")
    bt_parser.add_argument("--exchange", "-e", required=True, help="거래소 이름")
    bt_parser.add_argument("--symbol", "-s", required=True, help="심볼 (쉼표 구분)")
    bt_parser.add_argument("--timeframe", "-t", default=None, help="타임프레임")
    bt_parser.add_argument("--start", help="백테스트 시작일 (ISO format)")
    bt_parser.add_argument("--end", help="백테스트 종료일 (ISO format)")
    bt_parser.add_argument("--capital", type=float, default=None, help="초기 자본금 (USDT)")
    bt_parser.add_argument("--min-investment", type=float, default=None, help="최소 투자 수량 (코인)")
    bt_parser.add_argument("--leverage-max", type=int, default=None, help="최대 레버리지")
    bt_parser.add_argument("--leverage-min", type=int, default=None, help="최소 레버리지")

    # simulate 명령어
    sim_parser = subparsers.add_parser("simulate", help="라이브 시뮬레이터 (페이퍼 트레이딩)")
    sim_parser.add_argument("--exchange", "-e", required=True, help="거래소 이름")
    sim_parser.add_argument("--symbol", "-s", required=True, help="심볼")
    sim_parser.add_argument("--timeframe", "-t", default=None, help="타임프레임")
    sim_parser.add_argument("--capital", type=float, default=None, help="초기 자본금 (USDT)")
    sim_parser.add_argument("--interval", type=int, default=None, help="폴링 간격 (초)")
    sim_parser.add_argument("--leverage-max", type=int, default=None, help="최대 레버리지")
    sim_parser.add_argument("--leverage-min", type=int, default=None, help="최소 레버리지")

    # trade 명령어
    trade_parser = subparsers.add_parser("trade", help="실거래 트레이더 (실제 주문 실행)")
    trade_parser.add_argument("--exchange", "-e", required=True, help="거래소 이름")
    trade_parser.add_argument("--symbol", "-s", required=True, help="심볼")
    trade_parser.add_argument("--timeframe", "-t", default=None, help="타임프레임")
    trade_parser.add_argument("--capital", type=float, default=None, help="초기 자본금 참조값 (USDT)")
    trade_parser.add_argument("--interval", type=int, default=None, help="폴링 간격 (초)")
    trade_parser.add_argument("--leverage-max", type=int, default=None, help="최대 레버리지")
    trade_parser.add_argument("--leverage-min", type=int, default=None, help="최소 레버리지")
    trade_parser.add_argument("--daily-loss-limit", type=float, default=None, help="일일 최대 손실 (USDT)")
    trade_parser.add_argument("--capital-mode", choices=["total", "virtual"], default=None,
                              help="자본 모드: total(실잔고 기준) / virtual(가상자본 기준)")

    # export 명령어
    export_parser = subparsers.add_parser("export", help="DB 데이터를 CSV로 내보내기")
    export_parser.add_argument("--exchange", "-e", required=True, help="거래소 이름")
    export_parser.add_argument("--symbol", "-s", required=True, help="심볼")
    export_parser.add_argument("--timeframe", "-t", default=None, help="타임프레임")
    export_parser.add_argument("--start", help="시작일 (ISO format)")
    export_parser.add_argument("--end", help="종료일 (ISO format)")
    export_parser.add_argument("--output", "-o", default=None, help="출력 디렉토리")

    # list-exchanges 명령어
    subparsers.add_parser("list-exchanges", help="지원 거래소 목록")

    args = parser.parse_args()

    # .env 로드 (API 키 등 환경변수)
    _load_env()

    # 설정 로드
    cfg = AppConfig.from_yaml(args.config)

    # 로그 초기화: LogManager (거래소/코인/날짜/카테고리별 파일 로그)
    log_level = args.log_level or cfg.logging.level
    log_base_dir = cfg.logging.base_dir
    LogManager.instance().init(base_dir=log_base_dir, level=log_level)

    commands = {
        "collect": cmd_collect,
        "strategy": cmd_strategy,
        "backtest": cmd_backtest,
        "simulate": cmd_simulate,
        "trade": cmd_trade,
        "export": cmd_export,
        "list-exchanges": cmd_list_exchanges,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args, cfg)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
