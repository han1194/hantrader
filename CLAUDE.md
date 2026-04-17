# HanTrader - 자동매매 봇 시스템

## 프로젝트 개요

암호화폐 자동매매 봇 시스템. 데이터 수집 → 전략 생성 → 백테스트 → 포트폴리오 최적화 → 자동매매 파이프라인을 구현한다.

## 기술 스택

- Python 3.11+
- ccxt: 거래소 API 래퍼
- ta: 기술적 지표
- pandas/numpy: 데이터 처리
- SQLAlchemy + SQLite: 데이터 저장
- vectorbt, scikit-learn, optuna, PyPortfolioOpt: 백테스트/최적화 (추후)

## 프로젝트 구조

```text
hantrader/
├── .env.example          # API 키 템플릿 (.env로 복사 후 사용)
├── .gitignore            # Git 제외 파일 (.env, __pycache__, data/ 등)
├── config/config.yaml    # 설정 파일 (거래소, 심볼, 수집, 전략, 백테스트, 시뮬레이터, 트레이더)
├── src/
│   ├── main.py           # CLI 엔트리포인트 (collect, strategy, backtest, simulate, trade)
│   ├── config.py         # AppConfig 데이터클래스 (YAML → 타입 안전 설정, resolve 폴백)
│   ├── core/             # 공통 엔진 (LiveEngineBase: 시뮬레이터/트레이더 베이스 클래스)
│   ├── exchange/         # ccxt 거래소 래퍼 (공개 API + 인증 거래 API, 팩토리 패턴)
│   ├── collector/        # 데이터 수집기 (이어서 수집 지원)
│   ├── strategy/         # 트레이딩 전략 (BB, BB MTF, BB V2, BB V2 MTF)
│   ├── backtest/         # 백테스트 엔진, 평가, 리포트
│   ├── simulator/        # 라이브 시뮬레이터 (LiveEngineBase 상속, 페이퍼 트레이딩)
│   ├── trader/           # 실거래 트레이더 (LiveEngineBase 상속, Binance Futures 실주문)
│   ├── indicators/       # ta 기술적 지표 래퍼
│   ├── storage/          # DB 저장, CSV 내보내기
│   └── utils/            # LogManager (카테고리별 로깅), 타임프레임 리샘플링
├── data/
│   ├── db/               # SQLite DB 파일
│   ├── csv/              # CSV 출력 파일
│   ├── backtest/         # 백테스트 리포트 출력
│   ├── logs/             # 거래소/코인/날짜/모드/카테고리별 로그 파일
│   │   ├── system/       # 시스템 로그 (시작/종료, 설정, 에러)
│   │   └── {exchange}/{SYMBOL}/{날짜}/{mode}/  # trade/asset/signal/market/all.log
│   │       # mode: trade(실거래), sim(시뮬레이터), backtest(백테스트)
│   └── trader/           # 실거래 상태, 거래내역 CSV
└── docs/
    ├── howtorun.md       # 실행 가이드 (CLI 명령어, 옵션, 전략 규칙)
    ├── CHANGELOG.md      # 변경 이력 (날짜별 개선/수정 기록)
    ├── PROMPTS.md        # AI 시스템 요구 프롬프트 이력
    └── cloud_deploy.md   # 클라우드 24시간 운영/배포 가이드
```

## 개발 규칙

- 실행: `python -m src.main <command>`
- 설정: `config/config.yaml` 수정
- API 키: `.env.example` → `.env`로 복사 후 키 입력 (실거래 시 필수), 환경변수 이름은 `config.yaml`의 `exchanges.*.auth`에서 설정
- 인증 거래소 생성: `create_authenticated_exchange(exc_config)` — ExchangeConfig의 auth 환경변수에서 자동 로드
- 5m 데이터를 기본 수집하고 상위 타임프레임은 리샘플링으로 생성
- API 키 없이 공개 데이터(OHLCV) 수집 가능
- DB(SQLite)와 CSV 동시 저장
- 모든 시간은 KST(UTC+9) 기준, datetime에 +09:00 오프셋 표시하지 않음 (naive datetime)
- 심볼 입력 정규화: btc, BTC, btc/usdt, BTC_USDT → BTC/USDT (바이낸스 선물 USDT 거래 전용)
- BB전략 진입/손절 레벨은 모듈 상수로 정의 (LONG_ENTRY_LEVELS 등), config.yaml에서 오버라이드 가능
- 로그: `LogManager` 싱글톤 (`src/utils/log_manager.py`) — 거래소/코인/날짜/카테고리별 파일 자동 생성
- 로그 카테고리: SYSTEM(시작/종료/설정/에러), TRADE(주문/체결/청산), ASSET(잔고/수수료/펀딩), SIGNAL(전략/국면), MARKET(캔들/가격)
- 로그 레벨: config.yaml `logging.level`로 설정 (CLI `--log-level`로 오버라이드 가능), `logging.base_dir`로 저장 경로 설정
- 로그 사용: `LogManager.instance().bind(exchange, symbol, mode)` → `log.trade()`, `log.asset()`, `log.signal()`, `log.market()`, `log.system()`
- 로그 모드: `"trade"` (실거래), `"sim"` (시뮬레이터), `"backtest"` (백테스트) — 콘솔에 `[TRADE|TRD]`, `[SIM|SIG]`, `[BT|SYS]` 형식 표시
- 로그 파일: 카테고리별 파일(INFO+) + all.log(DEBUG+) + system/ 디렉토리(SYSTEM 카테고리)
- DEBUG 레벨에서 시그널 생성/미진입 사유, 추세확인 판단근거, 진입 불가 사유 등 상세 출력
- 시뮬레이터/트레이더는 `LiveEngineBase`(src/core/live_base.py) 상속 — 틱 루프, 시그널 생성, 상태 추적, 로깅 공통화
- 설정은 `AppConfig.from_yaml()`로 로드, `SimulatorConfig.resolve()`/`TraderConfig.resolve_for_symbol()`로 backtest 폴백 + 코인별 오버라이드 해석
- 코인별 개별 설정: `trader.symbol_overrides`에서 심볼별 레버리지, 거래수량(코인단위), 타임프레임 등 오버라이드 (미지정 항목은 trader 기본값 적용)
- `StrategyConfig.to_strategy_kwargs()`로 전략 파라미터 생성 (main.py에서 직접 dict 구성하지 않음)
- 자본 모드(`capital_mode`): `total`(실잔고 기준, 기본) / `virtual`(가상자본 기준, 실잔고 무시하고 PnL만 반영). CLI `--capital-mode` 또는 config로 설정
- 실거래 트레이더 상태는 `data/trader/state/{SYMBOL}.json`에 저장/복원 (`--capital` 미지정 시 자동 복원)
- 실거래 시작 시 거래소에서 심볼별 제약조건 조회 (최대 레버리지, 수수료율, 최소 주문금액/수량)
- config 레버리지가 거래소 한도 초과 시 자동 클램핑, 최소 주문금액(notional) 미달 시 진입 차단
- 거래 수수료(fee)는 ccxt 주문 응답에서 추출, capital 차감 및 PnL 계산에 반영
- 펀딩 수수료(funding fee)는 10틱마다 거래소에서 조회하여 누적 추적
- 포지션 liquidation price는 거래소 동기화 시 조회, 포지션 정보에 표시
- 시작/재시작 시 실시간 ticker 가격으로 즉시 매매 판단 (캔들 완료 대기 없이), 이후 캔들 완성 시점에 판단
- 중간 동기화: `sync_timeframe` (기본 15m) 캔들마다 거래소와 포지션/잔고 동기화 — liquidation, 외부 청산 등 메인 TF 사이 변화 감지
- 시작/종료 시에도 거래소 동기화 수행 (잔고, 포지션, 펀딩 수수료)
- Emergency stop: 진입/추매마다 거래소에 STOP_MARKET 주문 등록 (서버사이드 비상 손절, 마진 콜 방지)
- 전략은 레지스트리 기반 (`create_strategy(name, **kwargs)`) — config.yaml `strategy.name`으로 선택 ("bb", "bb_mtf", "bb_v2", "bb_v2_mtf")
- BB MTF 전략: 기준 TF 위/아래 인접 TF 국면을 가중 투표로 합산, 허위 국면 전환 필터링 (예: 1h → 30m/2h 참고)
- BB V2 전략: BBW 최소 기준(`min_bbw_for_sideways`) + 추세 물타기 최소 간격(`min_entry_interval`) 추가, 기존 BB 전략 상속
- BB V2 MTF 전략: BB V2 + MTF 국면 판단 결합
- 실거래 매매 결과는 DB에 저장 (trades 테이블: 매매 기록, asset_history 테이블: 자산 이력 스냅샷)
- trades: 시간, 코인, 방향, 액션, 가격, 수량, 총금액, 수수료, 펀딩비, 레버리지, 마진, 수익(률), 미실현수익(률) 등
- asset_history: 이벤트별(시작/진입/청산/동기화/종료) 잔고, 평가금, 포지션 상태, 누적 수수료/펀딩비, 일일 PnL, 청산가

## 현재 구현 상태

- [x] 데이터 수집 (ccxt 래퍼, 페이지네이션, 다중 거래소, 이어서 수집)
- [x] 타임프레임 리샘플링 (5m → 15m, 1h, 1d, 1w, 1M)
- [x] 저장소 (SQLite DB + CSV)
- [x] 기술적 지표 래퍼 (ta)
- [x] BB 전략 (횡보 반전매매 3단계 물타기 + 횡보장 레버리지 제한 + 추세추종, ADX 다중지표 국면판단)
- [x] BB MTF 전략 (다중 타임프레임 국면 판단 — 기준 TF 위/아래 TF 국면 참고로 허위 전환 필터링)
- [x] BB V2 / BB V2 MTF 전략 (BBW 최소 기준 + 물타기 간격 제한, bb_v2/bb_v2_mtf)
- [~] 업비트 거래소 지원 (`src/exchange/upbit.py` — 2026-04-17 병합 시점에 파일만 포팅됨, 팩토리/심볼정규화/인증 코드 통합 필요)
- [x] 백테스트 엔진 (시뮬레이션, 평가 지표, 텍스트/HTML 리포트, 국면별/방향별 분석 통계)
- [x] 라이브 시뮬레이터 (실시간 데이터 + 가상 매매 페이퍼 트레이딩)
- [x] 실거래 트레이더 (Binance Futures, .env API 키, 격리마진, 일일손실제한)
- [x] 실거래 상태 저장/복원 (재시작 시 데이터 보존, --capital 명시로 초기화)
- [x] 거래 수수료/펀딩 수수료 추적 (PnL 반영, 로그/CSV 기록)
- [x] Liquidation price 추적 (포지션 정보에 청산가 및 근접도 표시)
- [x] 시작 시 즉시 매매 판단 (재시작/접속 복귀 시 timeframe 대기 없이 1회 즉시 실행)
- [x] Emergency stop order (진입/추매마다 거래소 서버사이드 STOP_MARKET 등록, 마진 콜 방지)
- [x] 실거래 매매결과 DB 저장 (trades 테이블 + asset_history 테이블, SQLite)
- [ ] 포트폴리오 최적화
- [ ] 리스크 관리
- [ ] 성과 모니터링

## CLI 명령어

```bash
# 데이터 수집 (이어서 수집 지원)
python -m src.main collect -e binance_futures --symbols BTC/USDT
python -m src.main collect -e binance_futures --start 2024-01-01

# 전략 시그널 생성 (심볼: btc, BTC, btc/usdt, BTC/USDT 모두 동일)
python -m src.main strategy -e binance_futures -s btc -t 1h

# 백테스트 (다중 심볼: btc,eth)
python -m src.main backtest -e binance_futures -s btc -t 1h
python -m src.main backtest -e binance_futures -s btc,eth -t 1h

# DB 데이터를 CSV로 내보내기 (타임프레임 지정 가능)
python -m src.main export -e binance_futures -s btc -t 1h
python -m src.main export -e binance_futures -s btc -t 4h --start 2024-01-01

# 라이브 시뮬레이터 (페이퍼 트레이딩)
python -m src.main simulate -e binance_futures -s btc -t 1h

# 실거래 트레이더 (.env에 API 키 필요)
python -m src.main trade -e binance_futures -s btc -t 1h
python -m src.main trade -e binance_futures -s btc --daily-loss-limit 50
python -m src.main trade -e binance_futures -s btc --capital 100 --capital-mode virtual

# 거래소 목록
python -m src.main list-exchanges
```
