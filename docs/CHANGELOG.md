# HanTrader 변경 이력

## 2026-04-15 실거래 트레이더 가상자본(virtual capital) 모드 추가

### 자본 모드 (capital_mode)

실거래 트레이더에 2가지 자본 모드를 지원한다.

| 모드 | 설명 |
|------|------|
| `total` (기본) | 거래소 실잔고를 capital로 사용. 기존 동작 그대로 |
| `virtual` | `--capital`로 지정한 금액을 가상 자본으로 사용. 실잔고 무시, PnL만 반영하여 가상 자본 추적. 마진 계산도 가상 자본 기준 |

**virtual 모드 동작:**

- `--capital 100`이면 100 USDT에서 시작
- 수익 발생 시 가상 자본 증가 (예: 100 → 150), 마진 5%도 150의 5%로 계산
- `_sync_balance()`에서 실잔고를 capital에 덮어쓰지 않음 (로깅만)
- 상태 저장 시 `virtual_capital` 필드에 현재 가상 자본 저장/복원

**사용법:**

```bash
# config.yaml에서 설정
trader:
  capital_mode: "virtual"

# 또는 CLI에서 지정
python -m src.main trade -e binance_futures -s btc --capital 100 --capital-mode virtual
```

### 변경 파일

- `src/config.py`: `TraderConfig`에 `capital_mode` 필드 추가, `resolve()`에 포함
- `src/trader/live_trader.py`: `capital_mode` 파라미터, `_sync_balance()` virtual 분기, 상태 저장/복원에 `virtual_capital`, 헤더/마진정보 표시
- `src/main.py`: `--capital-mode` CLI 옵션, `trader_kwargs`에 전달
- `config/config.yaml`: `capital_mode` 설정 추가 (기본값 `"total"`)

## 2026-04-14 백테스트 리포트 국면별 분석 통계 추가

### 국면별/방향별 분석

백테스트 리포트에 거래를 국면(횡보/추세)×방향(Long/Short)으로 분류한 통계를 추가했다.
각 조합별 거래수, 승률, 총 손익, 평균 손익, 평균 수익률을 표시한다.

| 구분 | 표시 항목 |
|------|-----------|
| 횡보장 (전체/Long/Short) | 거래수, 승률, 손익, 평균 수익률 |
| 추세장 (전체/Long/Short) | 거래수, 승률, 손익, 평균 수익률 |
| 방향별 (Long/Short) | 거래수, 승률, 손익, 평균 수익률 |

텍스트 리포트에 `[ 국면별 분석 ]`, `[ 방향별 분석 ]` 섹션 추가.
HTML 대시보드에 국면별/방향별 분석 테이블 추가.

### 변경 파일

- `src/backtest/report.py`: `_analyze_regime_stats()` 헬퍼 추가, `generate_text()`에 국면별/방향별 분석 섹션, `_generate_regime_html()` + 대시보드 삽입

## 2026-04-14 BB V2 전략 추가 + 전략 설정 개선

### BB V2 전략 (bb_v2, bb_v2_mtf)

기존 BB 전략의 백테스트 분석 결과를 반영하여 2가지를 개선한 V2 전략을 추가했다.
기존 bb/bb_mtf 전략은 그대로 유지한다.

| 개선 항목 | 파라미터 | 기본값 | 설명 |
|-----------|---------|--------|------|
| BBW 최소 기준 | `min_bbw_for_sideways` | 1.0 | 밴드가 좁으면 횡보 반전매매 신규진입 차단 |
| 물타기 간격 제한 | `min_entry_interval` | 3 | 추세 물타기 최소 캔들 간격 (연속 진입 방지) |

### config 개선 (기존 설정 백업: `config_backup_20260414.yaml`)

- 횡보 Short 진입 BB% 상향: `short_entry_levels` 1차 85% → 115% (premature 진입 차단)
- 트레일링 스톱 강화: `trailing_start_pct` 2%→1%, `trailing_stop_pct` 1%→0.5%

### 변경 파일

- `src/strategy/bb_v2_strategy.py` (신규): `BBV2Strategy` — BBW 필터 + 물타기 간격 제한
- `src/strategy/bb_v2_mtf_strategy.py` (신규): `BBV2MTFStrategy` — V2 + MTF 국면 판단
- `src/strategy/__init__.py`: V2 전략 import/export 추가
- `src/config.py`: `StrategyConfig`에 `min_bbw_for_sideways`, `min_entry_interval` 추가, `to_strategy_kwargs()`에서 v2/v2_mtf 파라미터 전달
- `src/main.py`: `_prepare_mtf_data()` MTF 체크를 `hasattr` 방식으로 변경 (v2_mtf 지원)
- `config/config.yaml`: `short_entry_levels` 오버라이드, 트레일링 조정, v2 파라미터 추가

## 2026-04-14 백테스트 리포트에 전략 설정 표시

백테스트 리포트(텍스트/HTML)에 사용된 전략과 백테스트 설정을 명시하도록 개선했다.
어떤 전략/파라미터로 돌린 결과인지 리포트만 보고 알 수 있다.

### 표시 항목

- 전략 이름 (bb / bb_mtf)
- BB 파라미터 (period, std)
- 국면 판단 (regime_window, regime_threshold)
- ADX 진입차단 기준
- 추세 손절/익절, 트레일링 설정
- MTF 가중치 (bb_mtf 전략일 때만)
- 레버리지 범위, 마진 방식

### 변경 파일

- `src/backtest/report.py`: `generate_text()`, `generate_dashboard()`에 `strategy_config`, `backtest_config` 파라미터 추가, HTML 전략 설정 카드 생성 메서드 추가
- `src/main.py`: 리포트 생성 시 `cfg.strategy`, `cfg.backtest` 전달

## 2026-04-10 로그 체계 전면 리팩토링 + 모드별 분리

기존 `setup_logger` + `self._file_logger` 이중 로깅 구조를 `LogManager` 싱글톤 기반
카테고리별 로깅 체계로 전면 교체했다. 거래소/코인/날짜/모드/카테고리별 로그 파일이 자동 생성된다.

### 로그 카테고리 (5종)

| 카테고리 | 라벨 | 내용 |
|---------|------|------|
| SYSTEM  | SYS  | 프로그램 시작/종료, 설정, 네트워크, 에러 |
| TRADE   | TRD  | 주문, 체결, 청산, 포지션 변경, 비상 손절 |
| ASSET   | AST  | 잔고, PnL, 수수료, 펀딩 수수료 |
| SIGNAL  | SIG  | 전략 시그널 생성, 국면 판단 |
| MARKET  | MKT  | 캔들 데이터, 가격, 동기화 |

### 모드별 분리

`bind(exchange, symbol, mode)` 호출 시 mode 파라미터로 로그 디렉토리를 분리한다.
콘솔에는 `[TRADE|TRD]`, `[SIM|SIG]`, `[BT|SYS]` 형식으로 모드와 카테고리를 동시에 표시한다.

| 모드 | 콘솔 라벨 | 설명 |
|------|----------|------|
| trade | TRADE | 실거래 트레이더 |
| sim | SIM | 라이브 시뮬레이터 (페이퍼 트레이딩) |
| backtest | BT | 백테스트 |

### 로그 디렉토리 구조

```
data/logs/
├── system/2026-04-10.log                             # 시스템 로그
├── binance_futures/BTC_USDT/2026-04-10/
│   ├── trade/                                        # 실거래 모드
│   │   ├── trade.log  asset.log  signal.log  market.log
│   │   └── all.log
│   ├── sim/                                          # 시뮬레이터 모드
│   │   └── ...
│   └── backtest/                                     # 백테스트 모드
│       └── ...
```

### 변경 파일

- `src/utils/log_manager.py` (신규): `LogManager` 싱글톤, `HanLogger` 카테고리 로거, `LogCategory` enum
- `src/utils/logger.py`: `setup_logger()`를 `LogManager` 기반 하위 호환 래퍼로 교체
- `src/core/live_base.py`: `logger` + `self._file_logger` 이중 호출 → `self.log` (HanLogger) 단일 호출로 통합, 파일 핸들러 직접 생성 코드 제거
- `src/trader/live_trader.py`: 모듈 레벨 `logger` 제거, 모든 로그를 `self.log.trade()`, `self.log.asset()`, `self.log.system()` 등 카테고리별로 분류
- `src/simulator/live_simulator.py`: 동일하게 `self.log` 카테고리 로깅으로 전환
- `src/main.py`: `setup_logger` → `LogManager.instance().init()` + `bind()`로 교체
- `src/config.py`: `LoggingConfig.file` → `LoggingConfig.base_dir`로 변경
- `config/config.yaml`: `logging.file` → `logging.base_dir`, 카테고리별 파일 구조 설명 추가

## 2026-04-09 인증 리팩토링

거래소 API 인증 로직을 `main.py`에서 분리하여 설정 기반으로 리팩토링했다.
기존에 `BINANCE_` 환경변수가 하드코딩되어 있던 구조를 `config.yaml`의 `auth` 섹션으로 일반화하여
다중 거래소 인증을 유연하게 지원한다.

- `src/config.py`: `ExchangeConfig`에 `api_key_env`, `api_secret_env`, `testnet_env` 필드 추가
- `src/exchange/factory.py`: `create_authenticated_exchange(exc_config)` 함수 추가 — ExchangeConfig의 auth 환경변수에서 API 키를 로드하여 인증된 거래소 생성
- `src/exchange/__init__.py`: `create_authenticated_exchange` 내보내기 추가
- `src/main.py`:
  - `_load_env()`를 `main()` 시작 시점으로 이동 (모든 커맨드에서 .env 로드)
  - `cmd_trade`에서 `BINANCE_` 하드코딩 제거, `create_authenticated_exchange()` 사용
- `config/config.yaml`: `exchanges.*.auth` 섹션 추가 (거래소별 환경변수 이름 설정)

## 2026-04-06 중간 동기화 + 코인별 개별 설정 + 클라우드 운영 가이드

### 중간 동기화 (sync_timeframe)

메인 타임프레임(예: 1h) 사이에 발생하는 거래소 포지션 변화(liquidation, 외부 청산 등)를 감지하기 위해
설정 가능한 중간 동기화 주기를 도입했다.

- `config/config.yaml`: `trader.sync_timeframe: "15m"` 추가 (null이면 비활성화)
- `src/config.py`: `TraderConfig.sync_timeframe` 필드 추가, `resolve()`에 포함
- `src/core/live_base.py`:
  - `sync_timeframe` 속성 및 `_last_sync_candle_time` 상태 추가
  - `_check_sync_tick()`: 메인 캔들 미갱신 시 sync TF 캔들 확인하여 `_on_sync_tick()` 호출
  - `_on_sync_tick()` 훅 추가 (서브클래스에서 구현)
- `src/trader/live_trader.py`:
  - `_on_sync_tick()` 구현: 잔고/포지션 동기화, 포지션 소멸(liquidation) 감지 시 전략 상태 초기화 + 로그
  - `_on_stop()`: 종료 전 거래소와 최종 동기화 (잔고, 포지션, 펀딩 수수료) 추가
- `src/main.py`: `sync_timeframe` 전달 및 시작 시 표시

### 코인별 개별 설정 (symbol_overrides)

- `config/config.yaml`: `trader.symbol_overrides` 섹션 추가 (BTC, ETH, XRP, SOL)
  - 코인별 레버리지(max/min), 횡보장 레버리지, 거래수량(코인단위), 타임프레임, 마진 설정 오버라이드
  - 미지정 항목은 `trader` 섹션 기본값 자동 적용
- `src/config.py`: `SymbolOverrideConfig` 데이터클래스 추가
  - `TraderConfig.resolve_for_symbol()`: 심볼별 오버라이드가 적용된 설정 반환
  - `from_yaml()`에서 `symbol_overrides` 파싱 로직 추가
- `src/main.py`: `cmd_trade`에서 `resolve()` → `resolve_for_symbol()` 전환
  - 실거래 시작 시 코인별 설정 적용 여부 및 거래수량 표시
- `src/trader/live_trader.py`: `trade_quantity` 파라미터 추가
  - `_trade_quantity` 지정 시 마진 기반 계산 대신 고정 수량으로 주문
  - 헤더에 거래수량(코인단위) 표시

### 클라우드 운영 가이드

- `docs/cloud_deploy.md`: 24시간 클라우드 운영 가이드 문서 추가
  - 클라우드 업체 비교 (Oracle Free Tier, AWS Lightsail, Vultr/DigitalOcean)
  - 권장 스펙, systemd 서비스 등록, 보안 설정
  - Git 기반 배포 워크플로우, 모니터링, 백업 방법

## 2026-04-03 실거래 매매결과 DB 저장

### 신규 DB 테이블: trades + asset_history

- `src/storage/database.py`: 두 개의 신규 테이블 및 저장/조회 메서드 추가
  - **trades** 테이블: 매매 기록 (시간, 코인, 방향, 액션, 가격, 수량, 총금액, 수수료, 펀딩비, 레버리지, 마진, 수익/수익률, 미실현수익/수익률, 주문ID, 사유, 진입단계)
  - **asset_history** 테이블: 자산 이력 스냅샷 (잔고, 평가금, 포지션 상태, 누적 수수료/펀딩비, 일일PnL, 청산가, 메모)
  - `save_trade()`, `load_trades()`: 매매 기록 저장/조회
  - `save_asset_snapshot()`, `load_asset_history()`: 자산 스냅샷 저장/조회

### LiveTrader DB 통합

- `src/trader/live_trader.py`:
  - `db` 파라미터 추가 (DatabaseStorage 인스턴스)
  - `_save_trade_to_db()`: 진입/청산 체결 시 trades 테이블에 자동 저장
  - `_save_asset_snapshot()`: 이벤트별(start/entry/exit/sync/stop) 자산 상태 스냅샷 저장
  - 저장 시점: 트레이더 시작, 진입 체결, 청산 체결, 10틱 동기화, 트레이더 중지
- `src/main.py`: `cmd_trade`에서 DB 인스턴스 생성하여 LiveTrader에 전달

---

## 2026-04-03 BB MTF 전략 추가 (다중 타임프레임 국면 판단)

### 새 전략: bb_mtf — 기존 BB전략에 다중 타임프레임 국면 판단 보강

- `src/strategy/bb_mtf_strategy.py`: `BBMTFStrategy` 클래스 신규
  - `BBStrategy` 상속, `detect_regime`만 MTF로 오버라이드
  - 기준 TF 국면(±2점) + 상위 TF(±1.0) + 하위 TF(±0.5) 가중 투표
  - 기본 임계값 2.5 → 기준 TF가 추세여도 인접 TF 최소 1개 확인 필요
  - 인접 TF 자동 결정 (1h → 30m/2h, 4h → 2h/8h 등)
  - `prepare_mtf_data(df_lower, df_upper)` → generate_signals 전에 호출
- `src/strategy/registry.py`: `@register_strategy("bb_mtf")` 등록
- `src/strategy/__init__.py`: `BBMTFStrategy` export 추가

### 전략 레지스트리 기반 생성으로 전환

- `src/main.py`: `BBStrategy()` 직접 생성 → `create_strategy(name, **kwargs)` 레지스트리 사용
  - `_create_strategy()`, `_prepare_mtf_data()` 헬퍼 함수 추가
  - `cmd_strategy`, `cmd_backtest`: MTF 데이터 자동 로딩 (상위TF=리샘플링, 하위TF=5m에서 리샘플링)
  - `cmd_simulate`, `cmd_trade`: `strategy_name` 파라미터 전달
- `src/core/live_base.py`: `BBStrategy` 하드코딩 → `create_strategy()` 레지스트리 사용
  - `strategy_name` 파라미터 추가
  - `_prepare_mtf_if_needed()`: MTF 전략 시 워밍업/틱마다 인접 TF 데이터 자동 준비
- `src/simulator/live_simulator.py`: `strategy_name` 파라미터 전달 지원
- `src/trader/live_trader.py`: `strategy_name` 파라미터 전달 지원

### 설정 변경

- `src/config.py`: `StrategyConfig`에 MTF 파라미터 추가
  - `mtf_weight_upper` (기본 1.0), `mtf_weight_lower` (기본 0.5), `mtf_trend_threshold` (기본 2.5)
  - `to_strategy_kwargs()`: name="bb_mtf"일 때 MTF 파라미터 포함
- `config/config.yaml`: `strategy.name` 필드 추가 ("bb" 또는 "bb_mtf"), MTF 설정 예시

### 사용법

```bash
# 기존 BB전략으로 백테스트 (기본값)
python -m src.main backtest -e binance_futures -s btc -t 1h

# BB MTF전략으로 백테스트 (config.yaml에서 name: "bb_mtf" 설정)
# 또는 config.yaml strategy.name을 "bb_mtf"로 변경 후 동일 명령어
python -m src.main backtest -e binance_futures -s btc -t 1h
```

### DB datetime 형식 불일치 수정

- `src/storage/database.py`:
  - `load_ohlcv`: `+09:00` 포함/미포함 문자열 혼재 시 파싱 오류 수정 (오프셋 제거 후 naive 파싱)
  - `save_ohlcv`: naive KST datetime을 `+09:00` 오프셋 포함 문자열로 저장 (기존 데이터와 일관성)

## 2026-04-01 리팩토링 / 실거래 개선

### ccxt 직접 사용 제거 — exchange 래퍼로 통일

- `src/exchange/base.py`: `ExchangeWrapper.list_exchanges()` 정적 메서드 추가
- `src/main.py`: `cmd_list_exchanges()`에서 `import ccxt` 직접 사용을 `ExchangeWrapper.list_exchanges()` 호출로 변경

### 실거래 트레이더 — 거래소 조회값 활용 (config 고정값 대체)

- `src/exchange/base.py`: 거래소 제약조건 조회 메서드 추가
  - `get_min_cost(symbol)`: 최소 주문금액(notional) 조회
  - `get_max_leverage(symbol)`: 심볼별 최대 허용 레버리지 조회
  - `get_fee_rates(symbol)`: taker/maker 수수료율 조회
- `src/trader/live_trader.py`: `_setup_exchange()`에서 거래소 API로 제약조건 조회
  - 레버리지 검증: config의 leverage_max/min/sideways가 거래소 한도 초과 시 자동 클램핑
  - 수수료율: 거래소에서 taker/maker fee rate 조회 → 시작 시 로그 출력
  - 최소 주문금액: `_execute_entry()`에서 notional(수량×가격) < 거래소 최소금액 시 진입 차단

## 2026-03-31 실거래 개선

### 상태 저장/복원 (재시작 시 데이터 보존)

- `src/trader/live_trader.py`: `_save_state()`, `_load_state()` 메서드 추가
  - 상태 파일: `data/trader/state/{SYMBOL}.json`
  - 저장 시점: 매 거래 체결 후, 10틱마다, 종료 시
  - 저장 내용: initial_capital, daily_pnl, total_fees, total_funding_fees, trade_records
  - `--capital` CLI 옵션 명시 시 상태 초기화 (새로 시작), 미지정 시 기존 상태 복원
- `src/main.py`: `cmd_trade()`에서 `--capital` 명시 여부로 `restore_state` 플래그 전달

### 수수료(Fee) 추적 및 수익 반영

- `TradeRecord`에 `fee` 필드 추가 (거래별 수수료)
- `LivePosition`에 `total_entry_fee` 필드 추가 (진입 누적 수수료)
- 진입/청산 시 ccxt 주문 응답에서 fee 추출, capital 차감 및 PnL 계산에 반영
- 청산 시 PnL = gross_pnl - (진입fee + 청산fee)
- CSV에 fee 컬럼 추가
- 종료 요약에 누적 거래 수수료 표시

### 펀딩 수수료(Funding Fee) 추적

- `src/exchange/base.py`: `fetch_funding_history()` 메서드 추가
- `src/trader/live_trader.py`: `_sync_funding_fees()` 메서드 추가 (10틱마다 조회)
- 누적 펀딩 수수료 추적 (`_total_funding_fees`), 상태 파일에 저장
- 로그 및 종료 요약에 펀딩 수수료 표시

### Liquidation Price 추적

- `LivePosition`에 `liquidation_price` 필드 추가
- `_sync_position()`에서 거래소 포지션의 `liquidationPrice` 추출
- 포지션 정보 표시에 청산가 및 현재가 대비 근접도(%) 표시
- 종료 요약에 미청산 포지션 청산가 표시

### 최소 거래금액

- `_min_amount` 기본값 `0.001` → `0.0`으로 변경 (거래소 조회 값 필수 사용)

### 시작 시 실시간 가격으로 즉시 매매 판단

- `src/core/live_base.py`: `_initialize()`에서 실시간 ticker 가격을 반영하여 즉시 매매 판단
  - 과거 캔들로 전략/지표 워밍업 → 마지막 캔들의 close를 현재 ticker로 갱신 → 시그널 재생성
  - 프로그램 시작/재시작, 접속 오류 후 복귀 시 최신 가격 기준으로 즉시 매매 판단
  - 이후에는 기존대로 캔들 완성 시점에만 매매 판단
- `_get_ticker_price()`를 `LiveEngineBase` 공통 메서드로 이동 (LiveTrader 중복 제거)

### Emergency Stop Order (서버사이드 비상 손절)

- `src/exchange/base.py`: `create_stop_market_order()`, `cancel_order()`, `fetch_open_orders()`, `price_to_precision()` 추가
- `src/trader/live_trader.py`: emergency stop 관리 로직 추가
  - `_place_emergency_stop()`: 포지션 진입/추매 시마다 거래소에 STOP_MARKET 주문 등록
    - 손절가 = 평단 ± stoploss_pct (전략 설정값 사용)
    - 추매/물타기 시 기존 주문 취소 → 새 평단 기준으로 재등록
  - `_cancel_emergency_stop()`: 청산 시 비상 손절 주문 취소
  - `_cleanup_existing_stop_orders()`: 재시작 시 기존 STOP_MARKET 주문 전부 정리 후 재등록
  - 프로그램이 중단되어도 거래소 서버에서 손절이 실행됨 (마진 콜 방지)

## 2026-03-30 리팩토링

### 시뮬레이터/트레이더 공통 베이스 클래스 추출

- `src/core/live_base.py`: `LiveEngineBase` 추상 베이스 클래스 신규 생성
  - 틱 루프, 시그널 생성/상태 추적, 파일 로깅, 콘솔 출력을 공통화
  - 추상 메서드로 시그널 실행, 포지션 조회, PnL 계산 등 서브클래스별 구현 분리
  - 라이프사이클 훅: `_on_start()`, `_on_stop()`, `_on_tick_start()`, `_on_tick_end()`
- `src/simulator/live_simulator.py`: `LiveEngineBase` 상속으로 리팩토링 (452줄 → 195줄)
  - BacktestEngine을 통한 가상 매매 실행 로직만 유지
- `src/trader/live_trader.py`: `LiveEngineBase` 상속으로 리팩토링 (769줄 → 430줄)
  - 거래소 API 주문, 잔고/포지션 동기화, 일일 손실 제한 로직만 유지

### 설정 관리 통합

- `src/config.py`: `SimulatorConfig.resolve(bt)`, `TraderConfig.resolve(bt)` 메서드 추가
  - None 필드를 BacktestConfig 값으로 폴백하는 로직을 메서드로 캡슐화
- `src/main.py`: `AppConfig.from_yaml()` 데이터클래스 기반으로 전면 전환
  - `_build_strategy_kwargs()` 제거 → `StrategyConfig.to_strategy_kwargs()` 사용
  - raw dict 파싱 + fallback chain 제거 → `resolve()` 메서드 사용
  - 명령 핸들러 시그니처 통일: `cmd_*(args, cfg: AppConfig)`
  - 명령 디스패치를 dict 매핑으로 간소화

## 2026-03-30 수정

### DEBUG 로그로 시그널 생성/미진입 사유 상세 출력

- `config.yaml`의 `logging.level`을 `DEBUG`로 변경
- CLI `--log-level`이 없으면 config.yaml의 레벨을 따르도록 수정
- BB전략 `_sideways_signals`: 매 캔들마다 국면/BB%/ADX/포지션 상태 출력, 물타기 억제/조건미달/관망 사유
- BB전략 `_trend_signals`: 추세방향/확인여부/BB위치/포지션 상태 출력, 미진입 사유 (반대 포지션, 최대단계, 추세미확인)
- BB전략 `_confirm_trend`: MACD/RSI/Vol 각 항목의 통과/실패 여부와 값 출력
- 트레이더/시뮬레이터 `_tick`: 시그널 전체/현재캔들 건수, 포지션 상태, 시그널 없는 경우 사유
- 트레이더 `_execute_entry`: 잔고부족/마진부족/수량부족 미진입 사유

### 심볼 입력 정규화 (btc → BTC/USDT)

- CLI에서 `btc`, `BTC`, `btc/usdt`, `BTC_USDT` 등 다양한 형태를 모두 `BTC/USDT`로 정규화
- `_normalize_symbol()` / `_normalize_symbols()` 함수 추가 (main.py)
- collect, strategy, backtest, simulate, trade, export 모든 커맨드에 적용

### datetime 출력에서 +09:00 타임존 오프셋 제거

- 모든 내부 처리 및 출력은 KST 기준이므로 `+09:00` 표시가 불필요
- `src/exchange/base.py`: 거래소 데이터 UTC→KST 변환 후 `tz_localize(None)`으로 타임존 제거
- `src/storage/database.py`: DB 로드 시 동일하게 타임존 제거
- `src/main.py`: 불필요한 tz_localize 분기 코드 제거
- CSV 출력: `2024-01-01 12:00:00+09:00` → `2024-01-01 12:00:00`

### BB전략 진입/손절 레벨 상수 미정의 버그 수정

- **치명적 버그**: `LONG_ENTRY_LEVELS`, `SHORT_ENTRY_LEVELS`, `LONG_STOP_LEVELS`, `SHORT_STOP_LEVELS` 상수가 `bb_strategy.py`에서 참조되지만 정의되지 않아 `NameError` 발생
- 실거래/시뮬레이터/백테스트 모두 매 틱마다 시그널 생성 실패 → 매매가 전혀 발생하지 않는 문제
- 트레이더의 `except Exception` 에러 핸들링으로 에러가 조용히 무시되어 원인 파악이 어려웠음
- 수정: 모듈 레벨에 기본 진입/손절 레벨 상수 정의, `__init__`에서 config 오버라이드 지원

## 2026-03-27 수정

### data/ 출력 폴더 구조 정리 및 리포트 개선

- 출력 폴더를 `data/{type}/{날짜}/{코인명}/` 하위 구조로 변경
  - 백테스트: `data/backtest/20260327/BTC_USDT/report_1h_143000.txt`
  - 시뮬레이터: `data/simulator/20260327/BTC_USDT/sim_1h_143000.log`
  - 트레이더: `data/trader/20260327/BTC_USDT/trade_1h_143000.log`
- 파일명 간소화: 거래소/심볼 정보는 폴더 경로로 대체, 파일명은 `{유형}_{타임프레임}_{시간}.{확장자}`
- 텍스트 리포트 거래 내역에 **포지션 기간**(진입~청산 시간)과 각 **진입/청산 시각** 추가

### 동적 마진 (자본 대비 %) 도입

- 기존: `max_margin_per_entry` 고정 USDT → 자본이 커져도 마진 동일 → 수익률 체감
- 변경: `margin_pct` 옵션 추가 (예: 0.05 = 자본의 5%)
  - margin_pct > 0이면 매 진입 시 현재 자본 × margin_pct로 마진 동적 계산
  - margin_pct = 0이면 기존 고정 max_margin_per_entry 사용 (하위호환)
- 적용: BacktestEngine, LiveTrader, LiveSimulator 모두 동일 로직
- config.yaml: backtest, trader 섹션에 `margin_pct` 추가

### 전략 파라미터 config.yaml 외부화

- `config.yaml`에 `strategy:` 섹션 신설 — BB전략 전체 파라미터를 설정 파일에서 관리
  - bb_period, bb_std, regime_window, regime_threshold
  - stoploss_pct, takeprofit_pct, trailing_start_pct, trailing_stop_pct
  - adx_entry_block, adx_rise_lookback
- `main.py`에 `_build_strategy_kwargs()` 헬퍼 추가 — config → BBStrategy kwargs 매핑
- strategy, backtest, simulate, trade 4개 커맨드 모두 config에서 전략 파라미터를 읽도록 통일
- `LiveSimulator`, `LiveTrader`에 `strategy_kwargs` 파라미터 추가 — 외부에서 전략 설정 주입
- `warmup_candles` 하드코딩 제거 → `backtest.warmup_candles` config에서 읽기

### 횡보장 ADX 상승 시 신규진입 + 물타기 억제

- ADX >= 20 이면서 N캔들 전보다 상승 중이면 추세 전환 임박으로 판단 (`trend_approaching`)
- (1번) 횡보 반전매매 **신규 진입** 차단 (관망)
- (2번) 횡보 반전매매 **물타기(2차/3차)** 억제 — 1차 진입만 손절 시 마진 50, 3차까지 물타기 후 손절 시 마진 150이므로 최대 손실 1/3로 감소
- 기존 포지션의 청산/손절은 정상 처리 (수익에 영향 없음)
- 파라미터: `adx_entry_block` (기본 20.0), `adx_rise_lookback` (기본 3캔들)
- 목적: 횡보→추세 전환 직전에 역방향 포지션 진입/물타기로 큰 손실 발생하는 패턴 방지

### 추세장 트레일링 스톱 도입

- 추세추종 물타기 3회 후 PnL이 `trailing_start_pct`(기본 2%) 이상이면 트레일링 활성화
- Long: 고점 대비 `trailing_stop_pct`(기본 1%) 하락 시 익절 / Short: 저점 대비 1% 상승 시 익절
- 트레일링 미활성 상태에서는 기존 고정 익절(3%) 폴백 유지
- 목적: 강한 추세에서 수익을 더 키우고, 추세 약화 시 수익을 지키며 조기 청산

### 실거래 트레이더 설정 분리

- `config.yaml`의 `trader:` 섹션에 `initial_capital`, `max_margin_per_entry`, `leverage_max/min`, `sideways_leverage_max` 설정 추가
- `main.py` trade 명령에서 `trader:` 설정을 우선 참조하고, 없으면 `backtest:`로 폴백하도록 수정
- 기존에는 실거래 트레이더가 `backtest:` 하위 설정만 읽어 백테스트와 독립적으로 조정 불가했음

## 2026-03-26 개선 작업

### 4. 실거래 트레이더 구현 (Binance Futures)

**목적**: 시뮬레이터로 검증한 전략을 실제 거래소에서 실행

**구현 내용**:

- `src/trader/live_trader.py` — 실거래 트레이더 엔진
  - 시뮬레이터와 동일한 전략/시그널 파이프라인 사용
  - 시그널 → ccxt 시장가 주문으로 변환
  - 거래소 포지션/잔고 주기적 동기화 (10틱마다)
  - 격리(isolated)/교차(cross) 마진 모드 지원
  - 일일 최대 손실 제한 (daily_loss_limit)
  - Ctrl+C 시 포지션 유지 + 안전 종료 + 로그/CSV 저장

- `src/exchange/base.py` — ExchangeWrapper 인증 API 확장
  - API 키/시크릿 지원, 테스트넷 모드
  - `set_leverage()`, `set_margin_mode()`: 거래소 설정
  - `create_market_order()`: 시장가 주문 실행
  - `fetch_balance()`, `fetch_positions()`: 잔고/포지션 조회
  - `fetch_ticker()`: 실시간 시세
  - `get_min_amount()`, `amount_to_precision()`: 수량 정밀도

- `.env.example` — API 키 템플릿
- `.gitignore` — `.env`, `__pycache__`, `data/` 등 제외
- `config/config.yaml` — trader 섹션 추가 (margin_mode, daily_loss_limit 등)
- `src/main.py` — `trade` CLI 명령어 추가, .env 로더

**안전장치**:

- 실거래 시작 전 "yes" 입력 확인 (테스트넷 제외)
- 1회 진입 마진 상한 (max_margin_per_entry)
- 일일 최대 손실 제한 도달 시 신규 진입 차단
- 물타기 3단계 + 횡보장 레버리지 제한 (이전 개선 포함)
- 거래소 reduceOnly 파라미터로 청산 주문 보호

**CLI 사용법**:

```bash
# .env 설정 후 실거래
python -m src.main trade -e binance_futures -s BTC/USDT -t 1h
python -m src.main trade -e binance_futures -s BTC/USDT --daily-loss-limit 50
```

**변경 파일**: `src/trader/live_trader.py` (신규), `src/trader/__init__.py` (신규), `src/exchange/base.py`, `src/exchange/factory.py`, `src/main.py`, `config/config.yaml`, `.env.example` (신규), `.gitignore` (신규)

---

### 3. 횡보장 반전매매 강제청산 방지 (물타기/마진/레버리지 개선)

**문제**: 횡보장에서 50x 레버리지 × 5단계 물타기(각 20%, 총 100% 자본 투입) → 소폭 역행에도 마진 전액 소진 → 강제청산 반복

**원인**:

1. 물타기 5단계 × 20% = 자본 100% 투입으로 방어 여력 없음
2. 횡보장에서도 추세장과 동일한 50x 레버리지 적용
3. 손절 레벨(BB% -0.20/-0.30)에 도달하기 전에 이미 강제청산

**수정**:

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| 물타기 단계 | 5단계 | 3단계 |
| 마진 비율 | 각 20% (총 100%) | 15%/10%/10% (총 35%) |
| Long 진입 BB% | 0.30/0.20/0.10/0.00/-0.10 | 0.25/0.10/-0.05 |
| Short 진입 BB% | 0.70/0.80/0.90/1.00/1.10 | 0.75/0.90/1.05 |
| Long 손절 | BB%≤-0.20(50%), BB%≤-0.30(100%) | BB%≤-0.15(100%) |
| Short 손절 | BB%≥1.20(50%), BB%≥1.30(100%) | BB%≥1.15(100%) |
| 횡보장 레버리지 | 추세장과 동일 (최대 50x) | 별도 상한 (기본 15x) |
| Long 익절 BB% | ≥0.70 | ≥0.65 |
| Short 익절 BB% | ≤0.30 | ≤0.35 |

**추가 변경**:

- `BBStrategy`에 `sideways_leverage_max` 파라미터 추가
- `config.yaml`에 `sideways_leverage_max: 15` 설정 추가
- `LiveSimulator`에도 `sideways_leverage_max` 전달

**변경 파일**: `src/strategy/bb_strategy.py`, `src/main.py`, `src/simulator/live_simulator.py`, `config/config.yaml`

---

### 1. 국면 판단 로직 개선 (다중 지표 점수 시스템)

**문제**: 2월 BTC 급락(78K→64K) 중 국면을 `sideways`로 오판하여 Long 반전매매 연속 진입 → 강제청산 반복 (-92.47%)

**원인**: 기존 국면 판단이 **BB width 변화율 + MACD** 2가지만 사용
- BB width 변화율은 후행 지표 — 변동성이 이미 확대된 후에야 감지
- MACD도 12/26 EMA 기반이라 빠른 전환에 느림
- 급격한 하락에서도 `sideways` 판정 → 반전매매 Long 진입 → 연속 손실

**수정**: `detect_regime()`을 **다중 지표 2단계 점수 시스템**으로 교체

1단계 — 추세 강도 (방향 무관):
| 지표 | 조건 | 점수 |
|------|------|------|
| ADX (신규) | ≥ 25 | 2.0 |
| ADX (신규) | 20~25 | 1.0 |
| BB width 변화율 | > 15% (기존) | 1.0 |

2단계 — 추세 방향 (양수=상승, 음수=하락):
| 지표 | 상승 시 | 하락 시 |
|------|---------|---------|
| EMA 배열 (12 vs 26) | +1.5 | -1.5 |
| 가격 vs SMA 20 | +1.0 | -1.0 |
| MACD diff | +1.0 | -1.0 |
| DI+ vs DI- (신규) | +1.0 | -1.0 |

국면 결정: 강도 ≥ 2.0 **AND** |방향| ≥ 2.0 → 추세

**추가 변경**:
- `compute_indicators()`에 ADX, DI+, DI- 지표 추가
- 시그널 메타데이터에 `adx` 값 포함
- 리포트(텍스트/HTML)에 ADX 값 표시

**변경 파일**: `src/strategy/bb_strategy.py`, `src/backtest/report.py`

---

### 2. 백테스트 지표 워밍업 데이터 로드

**문제**: `--start 2026-02-01`과 `--start 2026-01-01`로 백테스트 시 동일한 2월의 수익률이 크게 다름 (-40.66% vs +11.62%)

**원인**: `--start`를 지정하면 해당 날짜부터의 데이터만 DB에서 로드하여 지표(BB, MACD, ADX 등)를 계산. 워밍업 데이터가 부족해 초기 지표값이 불안정하고, 국면 오판 발생

**수정**:

- `--start` 지정 시 시작일 이전 100캔들 분량의 데이터를 추가 로드
- 워밍업 포함 전체 데이터로 지표 계산 + 시그널 생성
- 실제 시작일 이전의 시그널과 데이터를 제거한 뒤 백테스트 실행
- 리샘플링 경로도 동일하게 워밍업 적용

**변경 파일**: `src/main.py`

---

## 2026-03-25 개선 작업

### 4. CSV 내보내기 커맨드 추가 (export)

**요청**: 수집한 데이터를 원하는 타임프레임으로 수동 CSV 생성

**수정**:

- `export` CLI 커맨드 신규 추가
- DB에 저장된 데이터를 지정한 타임프레임으로 CSV 내보내기
- DB에 해당 타임프레임이 없으면 5m 데이터에서 자동 리샘플링
- `--start`, `--end`로 기간 지정 가능
- `--output`으로 출력 디렉토리 지정 가능

**사용법**:

```bash
python -m src.main export -e binance_futures -s BTC/USDT -t 1h
python -m src.main export -e binance_futures -s BTC/USDT -t 4h --start 2024-01-01
python -m src.main export -e binance_futures -s BTC/USDT -t 1d -o data/export
```

**변경 파일**: `src/main.py`

---

### 5. 실행 가이드 문서 추가

- `docs/howtorun.md` 신규 작성
- 전체 CLI 명령어 사용법, 옵션, 설정 항목 정리

---

### 1. 월별 수익률 첫 달 누락 수정

**문제**: 백테스트를 2월 1일부터 실행하면 월별 수익률에 2월이 표시되지 않음 (3월부터만 표시)

**원인**: `_calc_monthly_returns()`에서 `pct_change().dropna()` 사용 시 첫 번째 달은 이전 달 데이터가 없어 NaN → `dropna()`로 제거됨

**수정**:

- `_calc_monthly_returns()`에 `initial_capital` 파라미터 추가
- 첫 번째 달의 수익률을 `(월말 자본 - 초기 자본) / 초기 자본`으로 계산
- `dropna()` 제거하여 첫 달부터 표시

**변경 파일**: `src/backtest/evaluator.py`

---

### 2. 백테스트 리포트 이력 보존

**문제**: 백테스트 실행 시 리포트 파일이 매번 덮어써져서 이전 결과가 사라짐

**수정**: 리포트 파일명에 실행 시각 타임스탬프 추가

- `report_{exchange}_{symbol}_{tf}.txt` → `report_{exchange}_{symbol}_{tf}_{YYYYMMDD_HHMMSS}.txt`
- HTML 대시보드, 거래 내역 CSV도 동일하게 타임스탬프 포함
- 동일 `BacktestReport` 인스턴스 내에서는 같은 타임스탬프 사용 (txt/html/csv 세트 매칭)

**변경 파일**: `src/backtest/report.py`

---

### 3. 라이브 시뮬레이터 로그 시스템 추가

**문제**: 시뮬레이터가 터미널 출력(`print`)만 하고 파일 로그/이력을 남기지 않음

**수정**: 시뮬레이터 실행 시 `data/simulator/` 디렉토리에 상세 로그 파일 생성

**기록하는 이벤트**:

- 시뮬레이터 시작 (설정 정보: 거래소, 심볼, 자본, 폴링간격 등)
- 초기 워밍업 (데이터 범위, 시그널 수)
- 새 캔들 감지 (OHLCV 값)
- 시그널 실행 (진입/청산 방향, 가격, 레버리지, 사유)
- 상태 업데이트 (가격, 자본, PnL, 포지션 상태)
- 데이터 수신 오류 (스택 트레이스 포함)
- 종료 요약 (실행 시간, 처리 캔들 수, 손익, 승률)
- 거래 내역 CSV 자동 저장

**파일 형식**:

- 로그: `data/simulator/sim_{exchange}_{symbol}_{tf}_{YYYYMMDD_HHMMSS}.log`
- 거래 CSV: `data/simulator/trades_{exchange}_{symbol}_{tf}_{YYYYMMDD_HHMMSS}.csv`

**변경 파일**: `src/simulator/live_simulator.py`, `src/main.py`, `config/config.yaml`

---

## 2026-03-24 개선 작업

### 1. 백테스트 설정 반영 수정

**문제**: config.yaml에 `initial_capital: 1000`으로 설정했지만 백테스트가 10000으로 실행됨

**원인**: `main.py` argparse의 `--capital` 기본값이 `default=10000`이어서 config 값이 무시됨

**수정**:
- `--capital`, `--min-investment` argparse 기본값을 `None`으로 변경
- CLI 인자 미지정 시 config.yaml 값 사용

---

### 2. min_investment 단위 변경 (USDT → 코인 수량)

**수정 전**: `min_investment`가 USDT 마진 기준 (100 USDT)
**수정 후**: 코인 수량 기준 (0.001 BTC)

- `engine.py`: 마진 비교 대신 수량 비교 후 마진 역산
- `config.yaml`: `min_investment: 0.001`

---

### 3. 전략-엔진 간 평균가 계산 불일치 수정

**문제**: 리포트에서 `PnL=-0.0204`인데 실제 손실은 `-1,404.22 USDT`

**원인**:
- 전략: `(진입가 + 현재가) / 2` 단순 산술평균
- 엔진: `(평균가 × 기존마진 + 현재가 × 신규마진) / 총마진` 금액 가중평균

**수정**: 전략의 `_update_position()`에 `total_weight` 추가, `position_ratio`를 가중치로 사용하여 엔진과 동일한 금액 가중평균 적용

---

### 4. 리포트 PnL 단위 표시 및 포지션 그룹핑

**수정 내용**:
- 요약/거래통계/거래내역의 모든 금액에 `USDT` 단위 표시
- 전략 사유의 `PnL=-0.0204` → `PnL=-2.04%` (퍼센트 포맷)
- `Trade`에 `position_id` 추가
- 리포트를 포지션 단위로 그룹핑 (물타기 진입들을 하나의 포지션으로 묶어 표시)

**변경 전**:
```
── 거래 #1 (short) ──  진입/청산
── 거래 #2 (short) ──  진입/청산  ← 별도 거래처럼 보임
```

**변경 후**:
```
══ 포지션 #1 (short) ══
  총 마진/수량/물타기 횟수/총 손익
  ── 진입 1차 ──
  ── 진입 2차 ──
  ── 청산 ──
```

---

### 5. 추세추종 진입 횟수 제한 (무한 진입 버그 수정)

**문제**: `entry_step=min(long_step + 1, 5)`로 인해 5차 이후에도 계속 진입, 모두 "진입 5차"로 표시

**수정**: `long_step < 5` 조건 추가, `entry_step = long_step + 1`로 변경. 정확히 5회까지만 진입

---

### 6. 횡보장 청산 조건 변경

**수정 전**: BB% 50% (중앙) 복귀 시 청산
**수정 후**:
- Long: BB% >= 70% (상단 매도 영역) 에서 청산
- Short: BB% <= 30% (하단 매수 영역) 에서 청산

수익 구간이 20%p → 40%p로 확대

---

### 7. 청산 사유 텍스트 정확성 개선

**문제**: "익절"이라 표시되지만 실제 PnL이 마이너스

**수정**: 실제 PnL에 따라 `익절` / `청산` 구분 표기, 사유에 `PnL=+1.23%` 실제 수익률 포함

---

### 8. 횡보장 물타기 조건 강화

**수정**: 횡보 반전매매에서 수익 중일 때 추가 진입 안 함
- Long: `price < entry_price` (손실 중)일 때만 물타기
- Short: `price > entry_price` (손실 중)일 때만 물타기
- 추세추종은 기존대로 유지

---

### 9. 실거래 제약 반영 (수익률 -100% 초과 방지)

**문제**: 총 수익률 -100.33% — 실거래에서 불가능한 결과

**원인**: 레버리지 손실이 마진을 초과하고, 잔고 음수에서도 거래 계속

**수정**:
- **손실 상한**: `pnl < -total_margin`이면 `pnl = -total_margin` (강제청산 반영)
- **Equity 체크**: equity <= 0이면 즉시 강제청산 후 거래 중단
- **잔고 체크**: `capital <= 0`이면 진입 거부
- **마진 상한**: `capital`을 초과하는 마진 투입 불가
- **1회 진입 마진 상한**: `max_margin_per_entry: 50` USDT 설정

---

### 10. 데이터 수집 이어서 수집 지원

**문제**: 옵션 없이 재수집 시 기존 1년 데이터가 사라지고 3일치만 남음

**원인**: CSV는 매번 덮어쓰기, `--start` 없으면 최근 며칠만 가져옴

**수정**:
- `--start` 미지정 시 `db.get_last_datetime()`으로 마지막 시점부터 이어서 수집
- CSV는 DB 전체 데이터를 내보내기 (수집한 일부만이 아님)
- 파생 타임프레임도 DB 전체 base 데이터 기준으로 리샘플링

---

### 11. 라이브 시뮬레이터 신규 구현

실시간 거래소 데이터를 수신하고 백테스트 엔진으로 가상 매매를 실행하는 페이퍼 트레이딩 시스템

**실행**: `python -m src.main simulate -e binance_futures -s BTC/USDT`

**동작 흐름**:
1. 거래소에서 최근 100개 캔들로 전략 워밍업
2. 일정 간격으로 최신 OHLCV 폴링
3. 새 캔들 완성 시 전략 시그널 생성 → 백테스트 엔진으로 가상 매매
4. 터미널에 실시간 상태 출력 (가격, 자본, PnL, 포지션)
5. Ctrl+C로 중지 시 시뮬레이션 요약 출력

**특징**:
- API 키 불필요 (공개 OHLCV만 사용)
- 백테스트 엔진 재사용 (동일한 마진/강제청산/손실 제한 로직)
- `config.yaml`의 `simulator` 섹션으로 설정 가능

---

---

## 2026-03-23 초기 구현

### v0.3.0 — 백테스트 엔진

- **BacktestEngine**: 시그널 기반 가상 매매 시뮬레이션, 포지션 관리, Equity curve 기록
- **BacktestEvaluator**: Total Return, Sharpe Ratio, Max Drawdown, Win Rate, Profit Factor, 월별 수익률
- **BacktestReport**: 텍스트 리포트 + HTML 대시보드 (Chart.js) + 거래 내역 CSV
- CLI `backtest` 명령어 추가

### v0.2.0 — BB 전략 + 전략 프레임워크

- **BBStrategy**: 횡보 반전매매 (BB% 5단계 물타기) + 추세추종 (MACD/RSI/Volume)
- **BaseStrategy / Signal / SignalType / MarketRegime**: 전략 프레임워크
- 동적 레버리지 (BB width 기반), 시장 국면 판단
- CLI `strategy` 명령어, 모든 시간 KST 통일

### v0.1.0 — 데이터 수집 시스템

- **ExchangeWrapper**: ccxt 래퍼, OHLCV 페이지네이션
- **타임프레임 리샘플링**: 5m → 15m/1h/1d/1w/1M
- **저장소**: SQLite DB + CSV
- **TAWrapper**: 기술적 지표 (RSI, MACD, BB, ATR, OBV 등)
- CLI `collect`, `list-exchanges` 명령어
- YAML 설정 파일 (`config/config.yaml`)
