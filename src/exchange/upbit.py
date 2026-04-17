"""업비트 거래소 래퍼.

업비트는 현물 KRW 거래소로 바이낸스 선물과 주요 차이점:
- 레버리지/마진 모드 없음 (leverage=1 고정)
- 포지션 개념 없음 (현물 잔고)
- 펀딩 수수료 없음
- STOP_MARKET 주문 없음
- 시장가 매수: KRW 금액 기준 (수량 아님)
- 시장가 매도: 코인 수량 기준
- 잔고: KRW free/total
- OHLCV 요청당 최대 200캔들 (바이낸스 1000과 다름)
"""

import time as _time
from datetime import datetime

import pandas as pd

from .base import ExchangeWrapper
from src.utils.logger import setup_logger
from src.utils.timeframe import KST, TIMEFRAME_MS

logger = setup_logger("hantrader.exchange.upbit")


class UpbitWrapper(ExchangeWrapper):
    """업비트 전용 거래소 래퍼.

    ExchangeWrapper를 상속하여 업비트의 현물 거래소 특성에 맞게
    선물 전용 메서드를 오버라이드한다.
    """

    def __init__(
        self,
        options: dict | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
    ):
        super().__init__(
            exchange_id="upbit",
            options=options,
            api_key=api_key,
            api_secret=api_secret,
            testnet=False,  # 업비트 testnet 미지원
        )

    # ------------------------------------------------------------------
    # 선물 전용 메서드 — 업비트에서 지원하지 않음
    # ------------------------------------------------------------------

    def set_leverage(self, symbol: str, leverage: int):
        """업비트는 현물 거래소로 레버리지 설정 불가. 무시."""
        logger.debug(f"set_leverage 무시 (업비트 현물): {symbol} {leverage}x")

    def set_margin_mode(self, symbol: str, mode: str = "isolated"):
        """업비트는 현물 거래소로 마진 모드 설정 불가. 무시."""
        logger.debug(f"set_margin_mode 무시 (업비트 현물): {symbol} {mode}")

    def get_max_leverage(self, symbol: str) -> int:
        """업비트는 현물 거래소. 항상 1 반환."""
        return 1

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict]:
        """업비트는 포지션 개념 없음. 빈 리스트 반환."""
        return []

    def fetch_funding_history(
        self,
        symbol: str,
        since: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """업비트는 펀딩 수수료 없음. 빈 리스트 반환."""
        return []

    def create_stop_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        params: dict | None = None,
    ) -> dict:
        """업비트는 STOP_MARKET 주문 미지원. 빈 dict 반환."""
        logger.warning(
            f"create_stop_market_order 무시 (업비트 미지원): {symbol} stop={stop_price:,.2f}")
        return {}

    # ------------------------------------------------------------------
    # 업비트 특화 오버라이드
    # ------------------------------------------------------------------

    def fetch_balance(self) -> dict:
        """계정 잔고를 조회한다.

        업비트는 KRW 기준 잔고를 반환한다.
        반환값의 'USDT' 키 대신 'KRW' 키를 사용하며,
        호환성을 위해 'USDT' 키도 동일 값으로 채운다.
        """
        self._require_auth()
        logger.debug("fetch_balance 요청 (업비트)")
        balance = self.exchange.fetch_balance()
        krw = balance.get("KRW", {})
        free = float(krw.get("free", 0) or 0)
        total = float(krw.get("total", 0) or 0)
        # 호환성: USDT 키에도 KRW 값 채움 (LiveTrader가 USDT 기준으로 읽음)
        balance["USDT"] = {"free": free, "total": total}
        logger.debug(f"fetch_balance 응답: KRW free={free:,.0f} total={total:,.0f}")
        return balance

    def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        params: dict | None = None,
    ) -> dict:
        """시장가 주문을 실행한다.

        업비트 시장가 매수는 수량(코인) 대신 금액(KRW)으로 주문해야 한다.
        ccxt의 createMarketBuyOrderRequiresPrice=False 설정 후
        매수는 cost(KRW) 기준, 매도는 amount(코인) 기준으로 처리한다.

        Args:
            symbol: 심볼 (예: BTC/KRW)
            side: "buy" 또는 "sell"
            amount: 매수 시 KRW 금액, 매도 시 코인 수량
        """
        self._require_auth()
        logger.info(
            f"create_market_order 요청: {side.upper()} {symbol} amount={amount:.2f}")

        extra_params = params or {}
        if side == "buy":
            # 업비트 시장가 매수: quoteOrderQty (KRW 금액) 기준
            order = self.exchange.create_market_buy_order(
                symbol, amount, params={**extra_params}
            )
        else:
            order = self.exchange.create_market_sell_order(
                symbol, amount, params={**extra_params}
            )

        avg_price = float(order.get("average") or order.get("price") or 0)
        filled = float(order.get("filled") or amount)
        logger.info(
            f"create_market_order 체결: {side.upper()} {symbol} "
            f"체결가={avg_price:,.2f} 수량={filled:.8f} 주문ID={order.get('id', '')}")
        return order

    def get_min_amount(self, symbol: str) -> float:
        """심볼의 최소 주문 수량을 반환한다.

        업비트는 Binance 필터가 없으므로 ccxt limits를 직접 사용한다.
        """
        logger.debug(f"get_min_amount: {symbol}")
        self.exchange.load_markets()
        market = self.exchange.market(symbol)
        val = market.get("limits", {}).get("amount", {}).get("min") or 0.0001
        logger.debug(f"get_min_amount 응답: {symbol} min_amount={val}")
        return float(val)

    def get_min_cost(self, symbol: str) -> float:
        """심볼의 최소 주문금액(KRW)을 반환한다.

        업비트 최소 주문금액은 5,000 KRW.
        ccxt limits.cost.min 이 없는 경우 기본값 5000을 반환한다.
        """
        logger.debug(f"get_min_cost: {symbol}")
        self.exchange.load_markets()
        market = self.exchange.market(symbol)
        val = market.get("limits", {}).get("cost", {}).get("min") or 5000.0
        logger.debug(f"get_min_cost 응답: {symbol} min_cost={val:,.0f} KRW")
        return float(val)

    def get_fee_rates(self, symbol: str) -> dict:
        """수수료율을 반환한다.

        업비트 기본 수수료: taker/maker 모두 0.05% (0.0005).
        """
        logger.debug(f"get_fee_rates: {symbol}")
        self.exchange.load_markets()
        market = self.exchange.market(symbol)
        taker = float(market.get("taker") or 0.0005)
        maker = float(market.get("maker") or 0.0005)
        result = {"taker": taker, "maker": maker}
        logger.debug(f"get_fee_rates 응답: {symbol} taker={taker:.4%} maker={maker:.4%}")
        return result

    # ------------------------------------------------------------------
    # OHLCV 수집 — 업비트 API 제한 대응
    # ------------------------------------------------------------------

    # 업비트 API는 요청당 최대 200캔들 반환
    _MAX_CANDLES = 200

    def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: str = "5m",
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        batch_size: int = 1000,
        rate_limit_ms: int = 100,
    ) -> pd.DataFrame:
        """업비트용 OHLCV 범위 수집. 요청당 최대 200캔들 제한을 처리한다."""
        tf_ms = TIMEFRAME_MS.get(timeframe, 5 * 60 * 1000)
        actual_batch = min(batch_size, self._MAX_CANDLES)

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

        logger.info(f"수집 시작: {symbol} {timeframe} (업비트, batch={actual_batch})")

        while True:
            df = self.fetch_ohlcv(symbol, timeframe, since=since, limit=actual_batch)

            if df.empty:
                break

            if end_ms:
                df = df[df.index <= pd.Timestamp(
                    end_ms, unit="ms", tz="UTC"
                ).tz_convert("Asia/Seoul").tz_localize(None)]

            all_data.append(df)

            if len(df) < actual_batch:
                break

            since = int(df.index[-1].tz_localize(KST).timestamp() * 1000) + tf_ms

            if end_ms and since >= end_ms:
                break

            # 업비트 rate limit: 초당 10회 제한, 안전 마진
            _time.sleep(max(rate_limit_ms / 1000, 0.15))

        if not all_data:
            logger.warning(f"수집된 데이터 없음: {symbol} {timeframe}")
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        result = pd.concat(all_data)
        result = result[~result.index.duplicated(keep="first")]
        result.sort_index(inplace=True)

        logger.info(f"수집 완료: {symbol} {timeframe} - {len(result)}건")
        return result
