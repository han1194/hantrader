import time
from datetime import datetime

import ccxt
import pandas as pd

from src.utils.logger import setup_logger
from src.utils.timeframe import KST

logger = setup_logger("hantrader.exchange")


class ExchangeWrapper:
    """ccxt 거래소 래퍼 클래스.

    API 키 없이 공개 데이터(OHLCV)를 수집할 수 있다.
    API 키가 제공되면 주문 실행, 포지션 조회 등 인증 API를 사용할 수 있다.
    """

    @staticmethod
    def list_exchanges() -> list[str]:
        """ccxt가 지원하는 거래소 ID 목록을 반환한다."""
        return sorted(ccxt.exchanges)

    def __init__(
        self,
        exchange_id: str,
        options: dict | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool = False,
    ):
        exchange_class = getattr(ccxt, exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"지원하지 않는 거래소: {exchange_id}")

        config = {"enableRateLimit": True}
        if options:
            config["options"] = options
        if api_key:
            config["apiKey"] = api_key
        if api_secret:
            config["secret"] = api_secret

        self._exchange_class = exchange_class
        self._config = config
        self._testnet = testnet
        self.exchange: ccxt.Exchange = exchange_class(config)
        self.exchange_id = exchange_id
        self._authenticated = bool(api_key and api_secret)

        if testnet:
            self.exchange.set_sandbox_mode(True)
            logger.info(f"거래소 초기화 (테스트넷): {exchange_id}")
        else:
            logger.info(f"거래소 초기화: {exchange_id}")

    def reconnect(self):
        """HTTP 세션을 재생성하여 절전 복귀 등 네트워크 단절 후 재접속한다."""
        try:
            self.exchange.session.close()
        except Exception:
            pass
        self.exchange = self._exchange_class(self._config)
        if self._testnet:
            self.exchange.set_sandbox_mode(True)
        logger.info(f"거래소 재접속 완료: {self.exchange_id}")

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def name(self) -> str:
        return self.exchange_id

    def load_markets(self) -> dict:
        return self.exchange.load_markets()

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        since: int | None = None,
        limit: int = 1000,
    ) -> pd.DataFrame:
        """OHLCV 데이터를 가져와 DataFrame으로 반환한다."""
        raw = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

        if not raw:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
        df.set_index("datetime", inplace=True)
        df.drop(columns=["timestamp"], inplace=True)
        return df

    def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: str = "5m",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        batch_size: int = 1000,
        rate_limit_ms: int = 100,
    ) -> pd.DataFrame:
        """지정 기간의 OHLCV 데이터를 페이지네이션하여 전체 수집한다."""
        from src.utils.timeframe import TIMEFRAME_MS

        tf_ms = TIMEFRAME_MS.get(timeframe, 5 * 60 * 1000)

        since = None
        if start:
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if start.tzinfo is None:
                start = start.replace(tzinfo=KST)
            since = int(start.timestamp() * 1000)

        end_ms = None
        if end:
            if isinstance(end, str):
                end = datetime.fromisoformat(end)
            if end.tzinfo is None:
                end = end.replace(tzinfo=KST)
            end_ms = int(end.timestamp() * 1000)

        all_data: list[pd.DataFrame] = []
        fetched = 0

        logger.info(f"수집 시작: {symbol} {timeframe} (거래소: {self.exchange_id})")

        while True:
            df = self.fetch_ohlcv(symbol, timeframe, since=since, limit=batch_size)

            if df.empty:
                break

            if end_ms:
                # end 이후 데이터 제거
                df = df[df.index <= pd.Timestamp(end_ms, unit="ms", tz="UTC").tz_convert("Asia/Seoul").tz_localize(None)]

            all_data.append(df)
            fetched += len(df)

            if len(df) < batch_size:
                break

            # 다음 페이지의 since 계산 (naive KST → KST aware → UTC ms)
            since = int(df.index[-1].tz_localize(KST).timestamp() * 1000) + tf_ms

            if end_ms and since >= end_ms:
                break

            time.sleep(rate_limit_ms / 1000)

        if not all_data:
            logger.warning(f"수집된 데이터 없음: {symbol} {timeframe}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        result = pd.concat(all_data)
        result = result[~result.index.duplicated(keep="first")]
        result.sort_index(inplace=True)

        logger.info(f"수집 완료: {symbol} {timeframe} - {len(result)}건")
        return result

    # ------------------------------------------------------------------
    # 인증 API (거래 실행)
    # ------------------------------------------------------------------

    def _require_auth(self):
        """인증 필요 메서드 호출 전 체크."""
        if not self._authenticated:
            raise RuntimeError("API 키가 설정되지 않았습니다. .env 파일을 확인하세요.")

    def set_leverage(self, symbol: str, leverage: int):
        """심볼의 레버리지를 설정한다."""
        self._require_auth()
        try:
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"레버리지 설정: {symbol} → {leverage}x")
        except ccxt.ExchangeError as e:
            logger.warning(f"레버리지 설정 실패 (무시 가능): {e}")

    def set_margin_mode(self, symbol: str, mode: str = "isolated"):
        """마진 모드를 설정한다 (isolated/cross)."""
        self._require_auth()
        try:
            self.exchange.set_margin_mode(mode, symbol)
            logger.info(f"마진 모드 설정: {symbol} → {mode}")
        except ccxt.ExchangeError as e:
            # 이미 설정된 경우 에러 무시
            logger.warning(f"마진 모드 설정 실패 (무시 가능): {e}")

    def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        params: dict | None = None,
    ) -> dict:
        """시장가 주문을 실행한다.

        Args:
            symbol: 심볼 (예: BTC/USDT)
            side: "buy" 또는 "sell"
            amount: 수량 (코인 단위)
            params: 추가 파라미터 (reduceOnly 등)

        Returns:
            ccxt 주문 결과 dict
        """
        self._require_auth()
        order = self.exchange.create_market_order(
            symbol, side, amount, params=params or {},
        )
        avg_price = order.get("average") or order.get("price") or 0
        logger.info(
            f"주문 체결: {side.upper()} {symbol} 수량={amount:.6f} "
            f"체결가={avg_price:,.2f} 주문ID={order['id']}"
        )
        return order

    def fetch_balance(self) -> dict:
        """계정 잔고를 조회한다."""
        self._require_auth()
        return self.exchange.fetch_balance()

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict]:
        """현재 보유 포지션을 조회한다."""
        self._require_auth()
        positions = self.exchange.fetch_positions(symbols)
        # 실제 포지션만 필터 (수량 > 0)
        return [p for p in positions if float(p.get("contracts", 0)) > 0]

    def fetch_ticker(self, symbol: str) -> dict:
        """현재 시세(ticker)를 조회한다."""
        return self.exchange.fetch_ticker(symbol)

    def get_min_amount(self, symbol: str) -> float:
        """심볼의 최소 주문 수량을 반환한다.

        Binance Futures는 market['limits']['amount']['min']이 부정확한 경우가 있어
        market['info']['filters'] 중 LOT_SIZE.minQty를 우선 사용한다.
        """
        self.exchange.load_markets()
        market = self.exchange.market(symbol)

        filters = market.get("info", {}).get("filters", [])
        for f in filters:
            if f.get("filterType") == "LOT_SIZE":
                lot_min = float(f.get("minQty", 0))
                if lot_min > 0:
                    logger.debug(f"get_min_amount(LOT_SIZE): {symbol} min={lot_min}")
                    return lot_min

        val = market.get("limits", {}).get("amount", {}).get("min", 0.001)
        logger.debug(f"get_min_amount(limits): {symbol} min={val}")
        return val

    def get_min_cost(self, symbol: str) -> float:
        """심볼의 최소 주문금액(notional)을 반환한다.

        Binance Futures는 MIN_NOTIONAL 필터의 notional 값을 우선 사용한다.
        """
        self.exchange.load_markets()
        market = self.exchange.market(symbol)

        filters = market.get("info", {}).get("filters", [])
        for f in filters:
            if f.get("filterType") in ("MIN_NOTIONAL", "NOTIONAL"):
                notional = float(f.get("notional") or f.get("minNotional") or 0)
                if notional > 0:
                    logger.debug(f"get_min_cost(MIN_NOTIONAL): {symbol} min={notional}")
                    return notional

        val = market.get("limits", {}).get("cost", {}).get("min", 0)
        logger.debug(f"get_min_cost(limits): {symbol} min={val}")
        return val

    def get_max_leverage(self, symbol: str) -> int:
        """심볼의 최대 허용 레버리지를 반환한다.

        1) market 정보의 limits.leverage.max 시도
        2) 없으면 fetch_leverage_tiers로 티어별 최대값 추출 (Binance Futures 등)
        3) 둘 다 실패하면 0 반환
        """
        self.exchange.load_markets()
        market = self.exchange.market(symbol)
        max_lev = market.get("limits", {}).get("leverage", {}).get("max")
        if max_lev:
            return int(max_lev)

        try:
            tiers = self.exchange.fetch_leverage_tiers([symbol])
            symbol_tiers = tiers.get(symbol, [])
            if symbol_tiers:
                result = int(max(
                    t.get("maxLeverage") or t.get("max_leverage") or 0
                    for t in symbol_tiers
                ))
                logger.info(f"get_max_leverage(tiers): {symbol} max={result}x")
                return result
        except Exception as e:
            logger.warning(f"fetch_leverage_tiers 실패: {e}")

        logger.warning(f"get_max_leverage 조회 실패: {symbol} → 0 반환")
        return 0

    def get_fee_rates(self, symbol: str) -> dict:
        """심볼의 taker/maker 수수료율을 반환한다.

        Returns:
            {"taker": float, "maker": float} (예: {"taker": 0.0004, "maker": 0.0002})
        """
        self.exchange.load_markets()
        market = self.exchange.market(symbol)
        return {
            "taker": market.get("taker", 0),
            "maker": market.get("maker", 0),
        }

    def amount_to_precision(self, symbol: str, amount: float) -> float:
        """수량을 거래소 정밀도에 맞게 변환한다."""
        self.exchange.load_markets()
        return float(self.exchange.amount_to_precision(symbol, amount))

    def create_stop_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        params: dict | None = None,
    ) -> dict:
        """스톱 마켓 주문을 실행한다 (서버사이드 손절).

        Args:
            symbol: 심볼 (예: BTC/USDT)
            side: "buy" 또는 "sell" (포지션 반대 방향)
            amount: 수량 (코인 단위)
            stop_price: 트리거 가격

        Returns:
            ccxt 주문 결과 dict
        """
        self._require_auth()
        order_params = {"stopPrice": stop_price, "reduceOnly": True}
        if params:
            order_params.update(params)
        order = self.exchange.create_order(
            symbol, "STOP_MARKET", side, amount, None, order_params,
        )
        logger.info(
            f"스톱 주문 등록: {side.upper()} {symbol} 수량={amount:.6f} "
            f"트리거={stop_price:,.2f} 주문ID={order['id']}"
        )
        return order

    def cancel_order(self, order_id: str, symbol: str):
        """주문을 취소한다."""
        self._require_auth()
        try:
            self.exchange.cancel_order(order_id, symbol)
            logger.info(f"주문 취소: {order_id} ({symbol})")
        except ccxt.OrderNotFound:
            logger.warning(f"주문 미발견 (이미 체결/취소): {order_id}")
        except Exception as e:
            logger.warning(f"주문 취소 실패: {order_id} — {e}")

    def fetch_open_orders(self, symbol: str) -> list[dict]:
        """미체결 주문 목록을 조회한다."""
        self._require_auth()
        return self.exchange.fetch_open_orders(symbol)

    def price_to_precision(self, symbol: str, price: float) -> float:
        """가격을 거래소 정밀도에 맞게 변환한다."""
        self.exchange.load_markets()
        return float(self.exchange.price_to_precision(symbol, price))

    def fetch_funding_history(
        self,
        symbol: str,
        since: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """펀딩 수수료 내역을 조회한다.

        Returns:
            list[dict]: 각 항목은 {timestamp, amount, ...} 형태
        """
        self._require_auth()
        try:
            return self.exchange.fetch_funding_history(symbol, since=since, limit=limit)
        except Exception as e:
            logger.warning(f"펀딩 수수료 조회 실패: {e}")
            return []
