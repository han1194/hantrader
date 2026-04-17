from datetime import datetime

import yaml

from src.exchange import ExchangeWrapper, create_exchange
from src.storage import DatabaseStorage, CSVExporter
from src.utils.timeframe import resample_ohlcv
from src.utils.logger import setup_logger

logger = setup_logger("hantrader.collector")


class DataCollector:
    """시장 데이터 수집기.

    5m 데이터를 수집하고, 상위 타임프레임을 리샘플링하여 저장한다.
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.db = DatabaseStorage(self.config["storage"]["database"]["path"])

        self.csv_exporter = None
        if self.config["storage"]["csv"]["enabled"]:
            self.csv_exporter = CSVExporter(self.config["storage"]["csv"]["output_dir"])

        self.exchanges: dict[str, ExchangeWrapper] = {}
        self._init_exchanges()

    def _init_exchanges(self):
        for name, exc_config in self.config["exchanges"].items():
            if not exc_config.get("enabled", False):
                continue
            self.exchanges[name] = create_exchange(
                exc_config["type"],
                exc_config.get("options"),
            )

    def collect(
        self,
        exchange_name: str | None = None,
        symbols: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ):
        """데이터를 수집한다.

        Args:
            exchange_name: 특정 거래소만 수집 (None이면 전체)
            symbols: 특정 심볼만 수집 (None이면 config의 심볼)
            start: 시작일 (ISO format, 예: "2024-01-01")
            end: 종료일 (ISO format)
        """
        collector_cfg = self.config["collector"]
        base_tf = collector_cfg["base_timeframe"]
        derived_tfs = collector_cfg["derived_timeframes"]
        batch_size = collector_cfg.get("batch_size", 1000)
        rate_limit = collector_cfg.get("rate_limit_ms", 100)

        start = start or collector_cfg.get("start_date")
        end = end or collector_cfg.get("end_date")

        targets = {}
        if exchange_name:
            if exchange_name not in self.exchanges:
                raise ValueError(f"거래소를 찾을 수 없음: {exchange_name}")
            targets[exchange_name] = self.exchanges[exchange_name]
        else:
            targets = self.exchanges

        for exc_name, exchange in targets.items():
            exc_symbols = symbols or self.config["symbols"].get(exc_name, [])
            logger.info(f"=== {exc_name} 수집 시작 ({len(exc_symbols)}개 심볼) ===")

            for symbol in exc_symbols:
                self._collect_symbol(
                    exchange, exc_name, symbol,
                    base_tf, derived_tfs,
                    start, end, batch_size, rate_limit,
                )

        logger.info("전체 수집 완료")

    def _collect_symbol(
        self,
        exchange: ExchangeWrapper,
        exc_name: str,
        symbol: str,
        base_tf: str,
        derived_tfs: list[str],
        start: str | None,
        end: str | None,
        batch_size: int,
        rate_limit: int,
    ):
        # start 미지정 시 DB 마지막 시점부터 이어서 수집
        effective_start = start
        if not effective_start:
            last_dt = self.db.get_last_datetime(exc_name, symbol, base_tf)
            if last_dt:
                logger.info(f"기존 데이터 발견: {exc_name}/{symbol}/{base_tf} 마지막={last_dt}, 이어서 수집")
                effective_start = last_dt

        # 1. 5m 데이터 수집
        df_base = exchange.fetch_ohlcv_range(
            symbol, base_tf,
            start=effective_start, end=end,
            batch_size=batch_size,
            rate_limit_ms=rate_limit,
        )

        if df_base.empty:
            logger.warning(f"데이터 없음: {exc_name}/{symbol}")
            return

        # 2. DB 저장 (INSERT OR IGNORE로 중복 무시)
        self.db.save_ohlcv(df_base, exc_name, symbol, base_tf)

        # 3. CSV 저장 (DB 전체 데이터를 내보내기)
        if self.csv_exporter:
            df_all = self.db.load_ohlcv(exc_name, symbol, base_tf)
            self.csv_exporter.export(df_all, exc_name, symbol, base_tf)

        # 4. 파생 타임프레임 생성 및 저장
        #    DB 전체 base 데이터로 리샘플링하여 정확한 파생 데이터 생성
        df_all_base = self.db.load_ohlcv(exc_name, symbol, base_tf)
        for tf in derived_tfs:
            df_resampled = resample_ohlcv(df_all_base, tf)
            if df_resampled.empty:
                continue
            self.db.save_ohlcv(df_resampled, exc_name, symbol, tf)
            if self.csv_exporter:
                self.csv_exporter.export(df_resampled, exc_name, symbol, tf)

        logger.info(f"완료: {exc_name}/{symbol} (base + {len(derived_tfs)} derived)")
