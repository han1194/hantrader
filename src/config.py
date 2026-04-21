"""HanTrader 설정 관리.

config.yaml을 타입 안전한 dataclass로 로드한다.
모든 설정값에 기본값이 있어 config 파일에 빠진 항목이 있어도 동작한다.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ExchangeConfig:
    """거래소 설정."""
    enabled: bool = True
    type: str = ""
    options: dict = field(default_factory=dict)
    api_key_env: str = ""
    api_secret_env: str = ""
    testnet_env: str = ""


@dataclass
class CollectorConfig:
    """데이터 수집 설정."""
    base_timeframe: str = "5m"
    derived_timeframes: list[str] = field(default_factory=lambda: ["15m", "1h", "1d", "1w", "1M"])
    start_date: str | None = None
    end_date: str | None = None
    batch_size: int = 1000
    rate_limit_ms: int = 100


@dataclass
class StorageConfig:
    """저장 설정."""
    db_path: str = "data/db/hantrader.db"
    csv_enabled: bool = True
    csv_output_dir: str = "data/csv"


@dataclass
class StrategyConfig:
    """전략 파라미터 설정."""
    name: str = "bb"
    bb_period: int = 20
    bb_std: float = 2.0
    regime_window: int = 20
    regime_threshold: float = 0.15
    stoploss_pct: float = 0.02
    takeprofit_pct: float = 0.03
    trailing_start_pct: float = 0.02
    trailing_stop_pct: float = 0.01
    adx_entry_block: float = 20.0
    adx_rise_lookback: int = 3

    # BB% 진입/손절 레벨 (None이면 전략 내부 기본값 사용)
    short_entry_levels: list[dict] | None = None
    long_entry_levels: list[dict] | None = None
    short_stop_levels: list[dict] | None = None
    long_stop_levels: list[dict] | None = None

    # MTF (Multi-Timeframe) 전략 파라미터 (name="bb_mtf" 또는 "bb_v2_mtf" 일 때 사용)
    mtf_weight_upper: float = 1.0       # 상위 TF 국면 가중치
    mtf_weight_lower: float = 0.5       # 하위 TF 국면 가중치
    mtf_trend_threshold: float = 2.5    # 추세 판정 임계값

    # V2 전략 파라미터 (name="bb_v2" 또는 "bb_v2_mtf" 일 때 사용)
    min_bbw_for_sideways: float = 1.0   # 횡보 반전매매 최소 BBW
    min_entry_interval: int = 3         # 추세 물타기 최소 간격 (캔들 수)

    # V3 전략 파라미터 (name="bb_v3")
    # BB% 극단 돌파 필터 (신규진입 한정) — 돌파는 추세 시작 신호로 간주하여 역추세 진입 차단
    bbp_breakout_upper: float = 1.05    # BB% 상단 돌파 기준
    bbp_breakout_lower: float = -0.05   # BB% 하단 돌파 기준

    # V4 전략 파라미터 (name="bb_v4")
    # 국면 전환 쿨다운 — trend→sideways 전환 직후 N캔들 횡보 신규진입 차단
    cooldown_candles: int = 5

    def to_strategy_kwargs(
        self,
        *,
        timeframe: str,
        leverage_max: int,
        leverage_min: int,
        sideways_leverage_max: int,
    ) -> dict:
        """전략 생성자에 전달할 kwargs를 생성한다."""
        kwargs = {
            "timeframe": timeframe,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "leverage_max": leverage_max,
            "leverage_min": leverage_min,
            "sideways_leverage_max": sideways_leverage_max,
            "regime_window": self.regime_window,
            "regime_threshold": self.regime_threshold,
            "stoploss_pct": self.stoploss_pct,
            "takeprofit_pct": self.takeprofit_pct,
            "adx_entry_block": self.adx_entry_block,
            "adx_rise_lookback": self.adx_rise_lookback,
            "trailing_start_pct": self.trailing_start_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
        }
        if self.short_entry_levels is not None:
            kwargs["short_entry_levels"] = self.short_entry_levels
        if self.long_entry_levels is not None:
            kwargs["long_entry_levels"] = self.long_entry_levels
        if self.short_stop_levels is not None:
            kwargs["short_stop_levels"] = self.short_stop_levels
        if self.long_stop_levels is not None:
            kwargs["long_stop_levels"] = self.long_stop_levels

        # MTF 전략 파라미터 (bb_mtf, bb_v2_mtf)
        if self.name in ("bb_mtf", "bb_v2_mtf"):
            kwargs["mtf_weight_upper"] = self.mtf_weight_upper
            kwargs["mtf_weight_lower"] = self.mtf_weight_lower
            kwargs["mtf_trend_threshold"] = self.mtf_trend_threshold

        # V2 전략 파라미터 (bb_v2, bb_v2_mtf, bb_v3, bb_v4는 V2 상속)
        if self.name in ("bb_v2", "bb_v2_mtf", "bb_v3", "bb_v4"):
            kwargs["min_bbw_for_sideways"] = self.min_bbw_for_sideways
            kwargs["min_entry_interval"] = self.min_entry_interval

        # V3 전용 파라미터 (BB% 돌파 필터)
        if self.name == "bb_v3":
            kwargs["bbp_breakout_upper"] = self.bbp_breakout_upper
            kwargs["bbp_breakout_lower"] = self.bbp_breakout_lower

        # V4 전용 파라미터 (국면 전환 쿨다운)
        if self.name == "bb_v4":
            kwargs["cooldown_candles"] = self.cooldown_candles

        return kwargs


@dataclass
class BacktestConfig:
    """백테스트 설정."""
    default_period_years: int = 2
    timeframe: str = "1h"
    initial_capital: float = 100
    min_investment: float = 0.002
    margin_pct: float = 0.05
    max_margin_per_entry: float = 5
    leverage_max: int = 50
    leverage_min: int = 50
    sideways_leverage_max: int = 15
    warmup_candles: int = 100
    output_dir: str = "data/backtest"


@dataclass
class SimulatorConfig:
    """시뮬레이터 설정."""
    timeframe: str = "1h"
    initial_capital: float | None = None
    min_investment: float | None = None
    margin_pct: float | None = None
    max_margin_per_entry: float | None = None
    leverage_max: int | None = None
    leverage_min: int | None = None
    sideways_leverage_max: int | None = None
    lookback_candles: int = 100
    log_dir: str = "data/simulator"

    def resolve(self, bt: "BacktestConfig") -> dict:
        """None 필드를 BacktestConfig 값으로 폴백하여 완성된 설정 dict를 반환한다."""
        return {
            "timeframe": self.timeframe,
            "initial_capital": self.initial_capital if self.initial_capital is not None else bt.initial_capital,
            "min_investment": self.min_investment if self.min_investment is not None else bt.min_investment,
            "margin_pct": self.margin_pct if self.margin_pct is not None else bt.margin_pct,
            "max_margin_per_entry": self.max_margin_per_entry if self.max_margin_per_entry is not None else bt.max_margin_per_entry,
            "leverage_max": self.leverage_max if self.leverage_max is not None else bt.leverage_max,
            "leverage_min": self.leverage_min if self.leverage_min is not None else bt.leverage_min,
            "sideways_leverage_max": self.sideways_leverage_max if self.sideways_leverage_max is not None else bt.sideways_leverage_max,
            "lookback_candles": self.lookback_candles,
            "log_dir": self.log_dir,
        }


@dataclass
class SymbolOverrideConfig:
    """코인별 개별 설정. None인 필드는 TraderConfig 기본값으로 폴백."""
    timeframe: str | None = None
    leverage_max: int | None = None
    leverage_min: int | None = None
    sideways_leverage_max: int | None = None
    trade_quantity: float | None = None       # 1회 진입 수량 (코인 단위)
    margin_pct: float | None = None
    max_margin_per_entry: float | None = None


@dataclass
class TraderConfig:
    """실거래 트레이더 설정."""
    timeframe: str = "1h"
    initial_capital: float = 100
    margin_pct: float = 0.05
    max_margin_per_entry: float = 5
    leverage_max: int = 50
    leverage_min: int = 50
    sideways_leverage_max: int = 15
    margin_mode: str = "cross"
    capital_mode: str = "total"          # "total" (실잔고 기준) 또는 "virtual" (가상 자본 기준)
    daily_loss_limit: float = 100
    sync_timeframe: str | None = "15m"   # 중간 동기화 타임프레임 (None이면 비활성화)
    lookback_candles: int = 100
    log_dir: str = "data/trader"
    symbol_overrides: dict[str, SymbolOverrideConfig] = field(default_factory=dict)

    def resolve(self, bt: "BacktestConfig") -> dict:
        """BacktestConfig 폴백이 적용된 완성 설정 dict를 반환한다."""
        return {
            "timeframe": self.timeframe,
            "initial_capital": self.initial_capital,
            "margin_pct": self.margin_pct,
            "max_margin_per_entry": self.max_margin_per_entry,
            "leverage_max": self.leverage_max,
            "leverage_min": self.leverage_min,
            "sideways_leverage_max": self.sideways_leverage_max,
            "margin_mode": self.margin_mode,
            "capital_mode": self.capital_mode,
            "daily_loss_limit": self.daily_loss_limit,
            "sync_timeframe": self.sync_timeframe,
            "lookback_candles": self.lookback_candles,
            "log_dir": self.log_dir,
        }

    def resolve_for_symbol(self, bt: "BacktestConfig", symbol: str) -> dict:
        """심볼별 오버라이드가 적용된 완성 설정 dict를 반환한다.

        symbol_overrides에 해당 심볼이 있으면 오버라이드, 없으면 기본값 사용.
        """
        base = self.resolve(bt)
        override = self.symbol_overrides.get(symbol)
        if override is None:
            return base

        if override.timeframe is not None:
            base["timeframe"] = override.timeframe
        if override.leverage_max is not None:
            base["leverage_max"] = override.leverage_max
        if override.leverage_min is not None:
            base["leverage_min"] = override.leverage_min
        if override.sideways_leverage_max is not None:
            base["sideways_leverage_max"] = override.sideways_leverage_max
        if override.trade_quantity is not None:
            base["trade_quantity"] = override.trade_quantity
        if override.margin_pct is not None:
            base["margin_pct"] = override.margin_pct
        if override.max_margin_per_entry is not None:
            base["max_margin_per_entry"] = override.max_margin_per_entry

        return base


@dataclass
class LoggingConfig:
    """로깅 설정."""
    level: str = "INFO"
    base_dir: str = "data/logs"


@dataclass
class AppConfig:
    """전체 애플리케이션 설정.

    config.yaml의 모든 섹션을 포함한다.
    """
    exchanges: dict[str, ExchangeConfig] = field(default_factory=dict)
    symbols: dict[str, list[str]] = field(default_factory=dict)
    collector: CollectorConfig = field(default_factory=CollectorConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    simulator: SimulatorConfig = field(default_factory=SimulatorConfig)
    trader: TraderConfig = field(default_factory=TraderConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "AppConfig":
        """YAML 파일에서 설정을 로드한다."""
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # exchanges
        exchanges = {}
        for name, exc_raw in raw.get("exchanges", {}).items():
            if exc_raw is None:
                continue
            auth_raw = exc_raw.get("auth", {}) or {}
            exchanges[name] = ExchangeConfig(
                enabled=exc_raw.get("enabled", True),
                type=exc_raw.get("type", ""),
                options=exc_raw.get("options", {}),
                api_key_env=auth_raw.get("api_key_env", ""),
                api_secret_env=auth_raw.get("api_secret_env", ""),
                testnet_env=auth_raw.get("testnet_env", ""),
            )

        # storage (nested)
        st_raw = raw.get("storage", {})
        storage = StorageConfig(
            db_path=st_raw.get("database", {}).get("path", "data/db/hantrader.db"),
            csv_enabled=st_raw.get("csv", {}).get("enabled", True),
            csv_output_dir=st_raw.get("csv", {}).get("output_dir", "data/csv"),
        )

        # strategy
        strat_raw = raw.get("strategy", {})
        strategy = StrategyConfig(
            name=strat_raw.get("name", "bb"),
            bb_period=strat_raw.get("bb_period", 20),
            bb_std=strat_raw.get("bb_std", 2.0),
            regime_window=strat_raw.get("regime_window", 20),
            regime_threshold=strat_raw.get("regime_threshold", 0.15),
            stoploss_pct=strat_raw.get("stoploss_pct", 0.02),
            takeprofit_pct=strat_raw.get("takeprofit_pct", 0.03),
            trailing_start_pct=strat_raw.get("trailing_start_pct", 0.02),
            trailing_stop_pct=strat_raw.get("trailing_stop_pct", 0.01),
            adx_entry_block=strat_raw.get("adx_entry_block", 20.0),
            adx_rise_lookback=strat_raw.get("adx_rise_lookback", 3),
            short_entry_levels=strat_raw.get("short_entry_levels"),
            long_entry_levels=strat_raw.get("long_entry_levels"),
            short_stop_levels=strat_raw.get("short_stop_levels"),
            long_stop_levels=strat_raw.get("long_stop_levels"),
            mtf_weight_upper=strat_raw.get("mtf_weight_upper", 1.0),
            mtf_weight_lower=strat_raw.get("mtf_weight_lower", 0.5),
            mtf_trend_threshold=strat_raw.get("mtf_trend_threshold", 2.5),
            min_bbw_for_sideways=strat_raw.get("min_bbw_for_sideways", 1.0),
            min_entry_interval=strat_raw.get("min_entry_interval", 3),
            bbp_breakout_upper=strat_raw.get("bbp_breakout_upper", 1.05),
            bbp_breakout_lower=strat_raw.get("bbp_breakout_lower", -0.05),
            cooldown_candles=strat_raw.get("cooldown_candles", 5),
        )

        # simple sections
        def _build(dc_cls, section_name):
            s = raw.get(section_name, {})
            if s is None:
                s = {}
            valid_fields = {f.name for f in dc_cls.__dataclass_fields__.values()}
            return dc_cls(**{k: v for k, v in s.items() if k in valid_fields})

        bt = _build(BacktestConfig, "backtest")
        sim = _build(SimulatorConfig, "simulator")
        tr = _build(TraderConfig, "trader")

        # 코인별 개별 설정 파싱
        trader_raw = raw.get("trader", {}) or {}
        overrides_raw = trader_raw.get("symbol_overrides", {}) or {}
        symbol_overrides = {}
        for sym, ov in overrides_raw.items():
            if ov is None:
                continue
            valid_fields = {f.name for f in SymbolOverrideConfig.__dataclass_fields__.values()}
            symbol_overrides[sym] = SymbolOverrideConfig(
                **{k: v for k, v in ov.items() if k in valid_fields}
            )
        tr.symbol_overrides = symbol_overrides

        log_cfg = _build(LoggingConfig, "logging")
        collector = _build(CollectorConfig, "collector")

        return cls(
            exchanges=exchanges,
            symbols=raw.get("symbols", {}),
            collector=collector,
            storage=storage,
            strategy=strategy,
            backtest=bt,
            simulator=sim,
            trader=tr,
            logging=log_cfg,
        )

    def get_simulator_value(self, field_name: str):
        """시뮬레이터 설정값을 반환한다. None이면 backtest 설정으로 폴백."""
        val = getattr(self.simulator, field_name, None)
        if val is not None:
            return val
        return getattr(self.backtest, field_name, None)
