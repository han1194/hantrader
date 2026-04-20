from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from src.utils.logger import setup_logger

logger = setup_logger("hantrader.storage")


class DatabaseStorage:
    """SQLite 기반 OHLCV 데이터 저장소."""

    # 매매 기록 mode → 테이블 이름 매핑
    # trader: 실거래, backtest: 백테스트, simulator: 페이퍼 트레이딩
    TRADE_TABLES = {
        "trader": "trades",
        "backtest": "backtest_trades",
        "simulator": "simulator_trades",
    }

    def __init__(self, db_path: str = "data/db/hantrader.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{db_path}")
        self._init_tables()
        logger.info(f"DB 초기화: {db_path}")

    def _resolve_trade_table(self, mode: str) -> str:
        """mode → 테이블 이름. 알 수 없는 값이면 ValueError."""
        tbl = self.TRADE_TABLES.get(mode)
        if tbl is None:
            raise ValueError(
                f"알 수 없는 mode='{mode}'. "
                f"{list(self.TRADE_TABLES.keys())} 중 하나여야 함"
            )
        return tbl

    def _init_tables(self):
        trade_schema = """
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            exchange TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            datetime TEXT NOT NULL,
            side TEXT NOT NULL,
            action TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL,
            amount REAL NOT NULL,
            fee REAL DEFAULT 0,
            funding_fee REAL DEFAULT 0,
            leverage INTEGER DEFAULT 1,
            margin REAL DEFAULT 0,
            pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            unrealized_pnl REAL DEFAULT 0,
            unrealized_pnl_pct REAL DEFAULT 0,
            order_id TEXT,
            reason TEXT,
            entry_step INTEGER DEFAULT 1
        """
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    datetime TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    PRIMARY KEY (exchange, symbol, timeframe, datetime)
                )
            """))
            # trades(trader) / backtest_trades / simulator_trades — 동일 스키마
            for tbl in self.TRADE_TABLES.values():
                conn.execute(text(
                    f"CREATE TABLE IF NOT EXISTS {tbl} ({trade_schema})"
                ))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS asset_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    exchange TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    datetime TEXT NOT NULL,
                    event TEXT NOT NULL,
                    balance REAL DEFAULT 0,
                    equity REAL DEFAULT 0,
                    position_side TEXT,
                    position_qty REAL DEFAULT 0,
                    position_avg_price REAL DEFAULT 0,
                    position_margin REAL DEFAULT 0,
                    position_leverage INTEGER DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    realized_pnl REAL DEFAULT 0,
                    total_fees REAL DEFAULT 0,
                    total_funding_fees REAL DEFAULT 0,
                    daily_pnl REAL DEFAULT 0,
                    liquidation_price REAL DEFAULT 0,
                    memo TEXT
                )
            """))
            conn.commit()

    def save_ohlcv(
        self, df: pd.DataFrame, exchange: str, symbol: str, timeframe: str
    ) -> int:
        """OHLCV DataFrame을 DB에 저장한다. 중복은 무시."""
        if df.empty:
            return 0

        records = df.copy()
        records["exchange"] = exchange
        records["symbol"] = symbol
        records["timeframe"] = timeframe
        # naive KST datetime → "+09:00" 오프셋 포함 문자열로 저장 (기존 데이터와 일관성)
        idx = records.index
        if idx.tz is None:
            records["datetime"] = idx.strftime("%Y-%m-%d %H:%M:%S+09:00")
        else:
            records["datetime"] = idx.astype(str)
        records.reset_index(drop=True, inplace=True)

        cols = ["exchange", "symbol", "timeframe", "datetime", "open", "high", "low", "close", "volume"]
        records = records[cols]

        with self.engine.connect() as conn:
            for _, row in records.iterrows():
                conn.execute(
                    text("""
                        INSERT OR IGNORE INTO ohlcv
                        (exchange, symbol, timeframe, datetime, open, high, low, close, volume)
                        VALUES (:exchange, :symbol, :timeframe, :datetime, :open, :high, :low, :close, :volume)
                    """),
                    dict(row),
                )
            conn.commit()

        logger.info(f"DB 저장: {exchange}/{symbol}/{timeframe} - {len(records)}건")
        return len(records)

    def load_ohlcv(
        self, exchange: str, symbol: str, timeframe: str,
        start: str | None = None, end: str | None = None,
    ) -> pd.DataFrame:
        """DB에서 OHLCV 데이터를 로드한다."""
        query = "SELECT * FROM ohlcv WHERE exchange = :exchange AND symbol = :symbol AND timeframe = :timeframe"
        params: dict = {"exchange": exchange, "symbol": symbol, "timeframe": timeframe}

        if start:
            query += " AND datetime >= :start"
            params["start"] = start
        if end:
            query += " AND datetime <= :end"
            params["end"] = end

        query += " ORDER BY datetime"

        df = pd.read_sql(text(query), self.engine, params=params)
        if df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        # DB에 "+09:00" 포함/미포함 문자열이 혼재할 수 있음 (모두 KST)
        # 오프셋 문자열 제거 후 naive KST로 파싱
        dt_str = df["datetime"].str.replace(r"\+\d{2}:\d{2}$", "", regex=True)
        df["datetime"] = pd.to_datetime(dt_str)
        df.set_index("datetime", inplace=True)
        df.drop(columns=["exchange", "symbol", "timeframe"], inplace=True)
        return df

    # ------------------------------------------------------------------
    # 매매 기록 (trades)
    # ------------------------------------------------------------------

    def save_trade(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        datetime_str: str,
        side: str,
        action: str,
        price: float,
        quantity: float,
        amount: float,
        fee: float = 0.0,
        funding_fee: float = 0.0,
        leverage: int = 1,
        margin: float = 0.0,
        pnl: float = 0.0,
        pnl_pct: float = 0.0,
        unrealized_pnl: float = 0.0,
        unrealized_pnl_pct: float = 0.0,
        order_id: str = "",
        reason: str = "",
        entry_step: int = 1,
        mode: str = "trader",
    ) -> int:
        """매매 기록을 DB에 저장한다. 삽입된 row ID를 반환.

        mode: "trader" → trades, "backtest" → backtest_trades,
              "simulator" → simulator_trades
        """
        table = self._resolve_trade_table(mode)
        with self.engine.connect() as conn:
            result = conn.execute(
                text(f"""
                    INSERT INTO {table}
                    (exchange, symbol, timeframe, datetime, side, action,
                     price, quantity, amount, fee, funding_fee,
                     leverage, margin, pnl, pnl_pct,
                     unrealized_pnl, unrealized_pnl_pct,
                     order_id, reason, entry_step)
                    VALUES
                    (:exchange, :symbol, :timeframe, :datetime, :side, :action,
                     :price, :quantity, :amount, :fee, :funding_fee,
                     :leverage, :margin, :pnl, :pnl_pct,
                     :unrealized_pnl, :unrealized_pnl_pct,
                     :order_id, :reason, :entry_step)
                """),
                {
                    "exchange": exchange, "symbol": symbol, "timeframe": timeframe,
                    "datetime": datetime_str, "side": side, "action": action,
                    "price": price, "quantity": quantity, "amount": amount,
                    "fee": fee, "funding_fee": funding_fee,
                    "leverage": leverage, "margin": margin,
                    "pnl": pnl, "pnl_pct": pnl_pct,
                    "unrealized_pnl": unrealized_pnl, "unrealized_pnl_pct": unrealized_pnl_pct,
                    "order_id": order_id, "reason": reason, "entry_step": entry_step,
                },
            )
            conn.commit()
            return result.lastrowid

    def load_trades(
        self,
        exchange: str,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        mode: str = "trader",
        timeframe: str | None = None,
    ) -> pd.DataFrame:
        """매매 기록을 DB에서 로드한다.

        mode: "trader" / "backtest" / "simulator"
        timeframe: 지정 시 해당 TF만 로드 (백테스트/시뮬 재실행 시 유용)
        """
        table = self._resolve_trade_table(mode)
        query = f"SELECT * FROM {table} WHERE exchange = :exchange AND symbol = :symbol"
        params: dict = {"exchange": exchange, "symbol": symbol}
        if timeframe:
            query += " AND timeframe = :timeframe"
            params["timeframe"] = timeframe
        if start:
            query += " AND datetime >= :start"
            params["start"] = start
        if end:
            query += " AND datetime <= :end"
            params["end"] = end
        query += " ORDER BY datetime, id"
        return pd.read_sql(text(query), self.engine, params=params)

    def clear_trades(
        self,
        exchange: str,
        symbol: str,
        mode: str,
        timeframe: str | None = None,
    ) -> int:
        """mode 테이블에서 특정 exchange/symbol(/timeframe) 매매기록을 삭제한다.

        백테스트 재실행 시 이전 결과를 정리하는 용도.
        실거래(trader) 테이블은 데이터 보호를 위해 삭제하지 않는다.
        """
        if mode == "trader":
            raise ValueError(
                "trader(실거래) 테이블은 clear_trades로 삭제할 수 없습니다."
            )
        table = self._resolve_trade_table(mode)
        query = f"DELETE FROM {table} WHERE exchange = :exchange AND symbol = :symbol"
        params: dict = {"exchange": exchange, "symbol": symbol}
        if timeframe:
            query += " AND timeframe = :timeframe"
            params["timeframe"] = timeframe
        with self.engine.connect() as conn:
            result = conn.execute(text(query), params)
            conn.commit()
            return result.rowcount

    # ------------------------------------------------------------------
    # 자산 이력 (asset_history)
    # ------------------------------------------------------------------

    def save_asset_snapshot(
        self,
        exchange: str,
        symbol: str,
        datetime_str: str,
        event: str,
        balance: float = 0.0,
        equity: float = 0.0,
        position_side: str = "",
        position_qty: float = 0.0,
        position_avg_price: float = 0.0,
        position_margin: float = 0.0,
        position_leverage: int = 0,
        unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0,
        total_fees: float = 0.0,
        total_funding_fees: float = 0.0,
        daily_pnl: float = 0.0,
        liquidation_price: float = 0.0,
        memo: str = "",
    ) -> int:
        """자산 스냅샷을 DB에 저장한다. 삽입된 row ID를 반환."""
        with self.engine.connect() as conn:
            result = conn.execute(
                text("""
                    INSERT INTO asset_history
                    (exchange, symbol, datetime, event,
                     balance, equity,
                     position_side, position_qty, position_avg_price,
                     position_margin, position_leverage,
                     unrealized_pnl, realized_pnl,
                     total_fees, total_funding_fees, daily_pnl,
                     liquidation_price, memo)
                    VALUES
                    (:exchange, :symbol, :datetime, :event,
                     :balance, :equity,
                     :position_side, :position_qty, :position_avg_price,
                     :position_margin, :position_leverage,
                     :unrealized_pnl, :realized_pnl,
                     :total_fees, :total_funding_fees, :daily_pnl,
                     :liquidation_price, :memo)
                """),
                {
                    "exchange": exchange, "symbol": symbol,
                    "datetime": datetime_str, "event": event,
                    "balance": balance, "equity": equity,
                    "position_side": position_side, "position_qty": position_qty,
                    "position_avg_price": position_avg_price,
                    "position_margin": position_margin,
                    "position_leverage": position_leverage,
                    "unrealized_pnl": unrealized_pnl, "realized_pnl": realized_pnl,
                    "total_fees": total_fees, "total_funding_fees": total_funding_fees,
                    "daily_pnl": daily_pnl,
                    "liquidation_price": liquidation_price, "memo": memo,
                },
            )
            conn.commit()
            return result.lastrowid

    def load_asset_history(
        self,
        exchange: str,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """자산 이력을 DB에서 로드한다."""
        query = "SELECT * FROM asset_history WHERE exchange = :exchange AND symbol = :symbol"
        params: dict = {"exchange": exchange, "symbol": symbol}
        if start:
            query += " AND datetime >= :start"
            params["start"] = start
        if end:
            query += " AND datetime <= :end"
            params["end"] = end
        query += " ORDER BY datetime, id"
        return pd.read_sql(text(query), self.engine, params=params)

    # ------------------------------------------------------------------
    # OHLCV 유틸
    # ------------------------------------------------------------------

    def get_last_datetime(
        self, exchange: str, symbol: str, timeframe: str,
    ) -> str | None:
        """DB에 저장된 마지막 datetime을 반환한다. 데이터 없으면 None."""
        query = text("""
            SELECT MAX(datetime) as last_dt FROM ohlcv
            WHERE exchange = :exchange AND symbol = :symbol AND timeframe = :timeframe
        """)
        with self.engine.connect() as conn:
            result = conn.execute(query, {
                "exchange": exchange, "symbol": symbol, "timeframe": timeframe,
            }).fetchone()
        if result and result[0]:
            return result[0]
        return None
