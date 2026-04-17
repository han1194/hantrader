"""HanTrader 로그 관리자.

거래소/코인/날짜/모드/카테고리별 로그 파일을 자동 관리한다.

디렉토리 구조:
    data/logs/
    ├── system/                    # 시스템 로그 (시작/종료, 설정, 에러)
    │   └── 2026-04-10.log
    ├── binance_futures/           # 거래소별
    │   ├── BTC_USDT/             # 코인별
    │   │   └── 2026-04-10/       # 날짜별
    │   │       ├── trade/        # 실거래 모드
    │   │       │   ├── trade.log, asset.log, signal.log, market.log
    │   │       │   └── all.log
    │   │       ├── sim/          # 시뮬레이터 모드
    │   │       │   └── ...
    │   │       └── backtest/     # 백테스트 모드
    │   │           └── ...

모드:
    trade     실거래 트레이더
    sim       라이브 시뮬레이터 (페이퍼 트레이딩)
    backtest  백테스트

카테고리:
    SYSTEM  시스템 — 프로그램 시작/종료, 설정, 네트워크, 에러
    TRADE   매매 — 주문, 체결, 청산, 포지션 변경, 손절/익절, 비상 손절
    ASSET   자산 — 잔고, PnL, 수수료, 펀딩 수수료, 자산 스냅샷
    SIGNAL  시그널 — 전략 시그널 생성, 국면 판단, 진입/청산 판단 근거
    MARKET  시장 — 캔들 데이터, 가격, 동기화, 데이터 수집
"""

import logging
import sys
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path

KST = timezone(timedelta(hours=9))


class LogCategory(str, Enum):
    SYSTEM = "system"
    TRADE = "trade"
    ASSET = "asset"
    SIGNAL = "signal"
    MARKET = "market"


# 콘솔/파일 출력용 카테고리 라벨 (고정 폭 3자)
_CAT_LABELS = {
    LogCategory.SYSTEM: "SYS",
    LogCategory.TRADE:  "TRD",
    LogCategory.ASSET:  "AST",
    LogCategory.SIGNAL: "SIG",
    LogCategory.MARKET: "MKT",
}

# 콘솔 출력용 모드 라벨
_MODE_LABELS = {
    "trade": "TRADE",
    "sim": "SIM",
    "backtest": "BT",
}


class _KSTFormatter(logging.Formatter):
    """로그 타임스탬프를 KST로 출력하는 포맷터."""

    def formatTime(self, record, datefmt=None):
        ct = datetime.fromtimestamp(record.created, tz=KST)
        return ct.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


class LogManager:
    """중앙 로그 관리자 (싱글톤).

    init()으로 초기화 후, bind(exchange, symbol, mode)로 HanLogger를 얻어 사용한다.
    """

    _instance: "LogManager | None" = None

    @classmethod
    def instance(cls) -> "LogManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._base_dir = Path("data/logs")
        self._level = logging.DEBUG
        self._file_handlers: dict[str, logging.FileHandler] = {}
        self._console_handler: logging.StreamHandler | None = None
        self._initialized = False

        self._fmt = _KSTFormatter(
            "[%(asctime)s KST] %(levelname)-7s [%(cat_label)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._fmt_with_mode = _KSTFormatter(
            "[%(asctime)s KST] %(levelname)-7s [%(mode_label)s|%(cat_label)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def init(self, base_dir: str = "data/logs", level: str = "DEBUG"):
        """초기화. main()에서 한 번 호출한다."""
        self._base_dir = Path(base_dir)
        self._level = getattr(logging, level.upper(), logging.DEBUG)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        if self._initialized:
            # 재초기화: 레벨만 변경
            if self._console_handler:
                self._console_handler.setLevel(self._level)
            return

        self._console_handler = logging.StreamHandler(sys.stderr)
        self._console_handler.setLevel(self._level)
        self._console_handler.setFormatter(self._fmt_with_mode)
        self._initialized = True

    def bind(self, exchange: str = "", symbol: str = "", mode: str = "") -> "HanLogger":
        """거래소/심볼/모드에 바인딩된 로거를 반환한다.

        Args:
            exchange: 거래소 이름 (예: "binance_futures")
            symbol: 심볼 (예: "BTC/USDT")
            mode: 실행 모드 — "trade", "sim", "backtest" (빈 문자열이면 모드 없음)
        """
        return HanLogger(self, exchange, symbol, mode)

    def log(
        self,
        category: LogCategory,
        message: str,
        level: int = logging.INFO,
        exchange: str = "",
        symbol: str = "",
        mode: str = "",
        exc_info: bool = False,
    ):
        """로그를 기록한다. 콘솔 + 모드/카테고리 파일 + all 파일 + 시스템 파일."""
        if not self._initialized:
            self.init()

        cat_label = _CAT_LABELS.get(category, category.value.upper())
        mode_label = _MODE_LABELS.get(mode, mode.upper() if mode else "---")

        # LogRecord 생성
        record = logging.LogRecord(
            name="hantrader",
            level=level,
            pathname="",
            lineno=0,
            msg=message,
            args=(),
            exc_info=sys.exc_info() if exc_info else None,
        )
        record.cat_label = cat_label      # type: ignore[attr-defined]
        record.mode_label = mode_label    # type: ignore[attr-defined]

        # 1. 콘솔 출력
        if self._console_handler and level >= self._level:
            self._console_handler.emit(record)

        # 2. 거래소/심볼/모드별 파일
        today = datetime.now(KST).strftime("%Y-%m-%d")

        if exchange and symbol:
            safe_symbol = symbol.replace("/", "_")

            if mode:
                # 모드 있으면: {exchange}/{symbol}/{날짜}/{mode}/
                cat_dir = self._base_dir / exchange / safe_symbol / today / mode
                key_prefix = f"{exchange}/{safe_symbol}/{today}/{mode}"
            else:
                # 모드 없으면: {exchange}/{symbol}/{날짜}/
                cat_dir = self._base_dir / exchange / safe_symbol / today
                key_prefix = f"{exchange}/{safe_symbol}/{today}"

            # 카테고리 파일 (INFO 이상)
            if level >= logging.INFO:
                cat_key = f"{key_prefix}/{category.value}"
                self._emit(cat_key, cat_dir / f"{category.value}.log", record)

            # all.log (DEBUG 이상)
            all_key = f"{key_prefix}/all"
            self._emit(all_key, cat_dir / "all.log", record)

        # 3. 시스템 파일 (SYSTEM 카테고리이거나 exchange 미지정 시)
        if category == LogCategory.SYSTEM or not exchange:
            sys_dir = self._base_dir / "system"
            sys_key = f"system/{today}"
            self._emit(sys_key, sys_dir / f"{today}.log", record)

    def _emit(self, key: str, path: Path, record: logging.LogRecord):
        """파일 핸들러로 레코드를 출력한다."""
        handler = self._file_handlers.get(key)
        if handler is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(self._fmt)
            self._file_handlers[key] = handler
        handler.emit(record)

    def close(self):
        """모든 파일 핸들러를 닫는다."""
        for handler in self._file_handlers.values():
            handler.close()
        self._file_handlers.clear()


class HanLogger:
    """거래소/심볼/모드에 바인딩된 카테고리 로거.

    사용법:
        log = LogManager.instance().bind("binance_futures", "BTC/USDT", "trade")
        log.trade("진입 체결 | LONG 1차 | 체결가=83000")
        log.asset("잔고 동기화: 가용=150.00 USDT")
        log.signal("시그널 생성: LONG_ENTRY | BB 하단 터치")
        log.market("새 캔들 | O=83000 H=83100 L=82900 C=83050")
        log.system("거래소 설정 완료")
    """

    def __init__(self, manager: LogManager, exchange: str, symbol: str, mode: str = ""):
        self._mgr = manager
        self._exchange = exchange
        self._symbol = symbol
        self._mode = mode

    def _log(self, cat: LogCategory, msg: str, level: int, exc_info: bool):
        self._mgr.log(cat, msg, level, self._exchange, self._symbol, self._mode, exc_info)

    # --- 카테고리 메서드 ---

    def trade(self, msg: str, level: str = "INFO", exc_info: bool = False):
        """매매 로그 — 주문, 체결, 청산, 포지션 변경, 손절/익절."""
        self._log(LogCategory.TRADE, msg, getattr(logging, level), exc_info)

    def asset(self, msg: str, level: str = "INFO", exc_info: bool = False):
        """자산 로그 — 잔고, PnL, 수수료, 펀딩 수수료."""
        self._log(LogCategory.ASSET, msg, getattr(logging, level), exc_info)

    def signal(self, msg: str, level: str = "INFO", exc_info: bool = False):
        """시그널 로그 — 전략 시그널, 국면 판단, 진입/청산 근거."""
        self._log(LogCategory.SIGNAL, msg, getattr(logging, level), exc_info)

    def market(self, msg: str, level: str = "INFO", exc_info: bool = False):
        """시장 로그 — 캔들 데이터, 가격, 동기화."""
        self._log(LogCategory.MARKET, msg, getattr(logging, level), exc_info)

    def system(self, msg: str, level: str = "INFO", exc_info: bool = False):
        """시스템 로그 — 시작/종료, 설정, 네트워크, 에러."""
        self._log(LogCategory.SYSTEM, msg, getattr(logging, level), exc_info)

    # --- 표준 레벨 메서드 (기본 카테고리: SYSTEM) ---

    def debug(self, msg: str, cat: LogCategory = LogCategory.SYSTEM, exc_info: bool = False):
        self._log(cat, msg, logging.DEBUG, exc_info)

    def info(self, msg: str, cat: LogCategory = LogCategory.SYSTEM, exc_info: bool = False):
        self._log(cat, msg, logging.INFO, exc_info)

    def warning(self, msg: str, cat: LogCategory = LogCategory.SYSTEM, exc_info: bool = False):
        self._log(cat, msg, logging.WARNING, exc_info)

    def error(self, msg: str, cat: LogCategory = LogCategory.SYSTEM, exc_info: bool = False):
        self._log(cat, msg, logging.ERROR, exc_info)
