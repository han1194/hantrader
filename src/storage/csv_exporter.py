from pathlib import Path

import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger("hantrader.storage")


class CSVExporter:
    """OHLCV 데이터를 CSV 파일로 내보내는 클래스."""

    def __init__(self, output_dir: str = "data/csv"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self, df: pd.DataFrame, exchange: str, symbol: str, timeframe: str
    ) -> Path:
        """OHLCV DataFrame을 CSV로 저장한다.

        파일명: {exchange}_{symbol}_{timeframe}.csv
        """
        if df.empty:
            logger.warning(f"빈 DataFrame - CSV 저장 건너뜀: {exchange}/{symbol}/{timeframe}")
            return Path()

        safe_symbol = symbol.replace("/", "_")
        filename = f"{exchange}_{safe_symbol}_{timeframe}.csv"
        filepath = self.output_dir / filename

        df.to_csv(filepath)
        logger.info(f"CSV 저장: {filepath} ({len(df)}건)")
        return filepath
