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
│   ├── strategy/         # 트레이딩 전략 — bb/ 서브패키지(헬퍼 모듈로 분할) + bb_*.py shim
│   │   ├── base.py, registry.py
│   │   ├── bb/           # BB 계열 전략 (strategy/v2/v3/v4/v5/v6/v7/mtf/v2_mtf)
│   │   │                 # + 헬퍼: levels/indicators/regime/leverage/position/sideways/trend/hysteresis
│   │   └── bb_*.py       # 하위 호환 re-export shim (기존 import 경로 유지)
│   ├── backtest/         # 백테스트 엔진, 평가, 리포트
│   ├── simulator/        # 라이브 시뮬레이터 (LiveEngineBase 상속, 페이퍼 트레이딩)
│   ├── trader/           # 실거래 트레이더 (LiveEngineBase 상속, Binance Futures 실주문)
│   ├── indicators/       # ta 기술적 지표 래퍼
│   ├── storage/          # DB 저장, CSV 내보내기
│   ├── visualize/        # 공통 HTML 차트 생성기 (plotly 캔들 + 시그널 화살표 + 포지션 음영)
│   └── utils/            # LogManager (카테고리별 로깅), 타임프레임 리샘플링
├── data/
│   ├── db/               # SQLite DB 파일
│   ├── csv/              # CSV 출력 파일
│   ├── backtest/         # 백테스트 리포트 출력
│   ├── logs/             # 거래소/코인/날짜/모드/카테고리별 로그 파일
│   │   ├── system/       # 시스템 로그 (시작/종료, 설정, 에러)
│   │   └── {exchange}/{SYMBOL}/{날짜}/{mode}/  # trade/asset/signal/market/all.log
│   │       # mode: trade(실거래), sim(시뮬레이터), backtest(백테스트)
│   ├── trader/           # 실거래 상태, 거래내역 CSV
│   └── charts/           # `chart` 명령으로 생성한 HTML 차트
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
- BB전략 진입/손절 레벨은 `src/strategy/bb/levels.py` 모듈 상수로 정의 (LONG_ENTRY_LEVELS 등), config.yaml에서 오버라이드 가능. 오버라이드는 BBStrategy.__init__에서 levels 모듈 전역을 재바인딩 — 참조 시 반드시 `from . import levels` 후 `levels.LONG_ENTRY_LEVELS` 로 lazy access
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
- 전략은 레지스트리 기반 (`create_strategy(name, **kwargs)`) — config.yaml `strategy.name`으로 선택 ("bb", "bb_mtf", "bb_v2", "bb_v2_mtf", "bb_v3", "bb_v4", "bb_v5", "bb_v6", "bb_v7", "bb_v8", "bb_v9")
- BB MTF 전략: 기준 TF 위/아래 인접 TF 국면을 가중 투표로 합산, 허위 국면 전환 필터링 (예: 1h → 30m/2h 참고)
- BB V2 전략: BBW 최소 기준(`min_bbw_for_sideways`) + 추세 물타기 최소 간격(`min_entry_interval`) 추가, 기존 BB 전략 상속
- BB V2 MTF 전략: BB V2 + MTF 국면 판단 결합
- BB V3 전략: BB V2 상속 + 횡보 **신규진입**에 2가지 필터 추가 — (A) BB% 극단 돌파 필터(`bbp_breakout_upper/lower`, 기본 1.05/-0.05), (B) ADX OR 차단(`adx >= adx_entry_block`이면 rising 무관 차단). 기존 포지션 물타기/청산은 변경 없음
- BB V4 전략: BB V2 상속 + 국면 전환(trend→sideways) 쿨다운(`cooldown_candles`, 기본 5) — 전환 직후 N캔들 동안 횡보 **신규진입**만 차단 (물타기/청산 영향 없음)
- BB V5 전략: BB V2 상속 + Regime hysteresis(`hysteresis_candles`, 기본 3) — trend→sideways 전환을 N캔들 연속 sideways 조건 만족 시에만 허용 (추세의 일시 정지를 추세 종료로 오판 방지). sideways→trend 및 trend_up↔trend_down은 즉시 허용
- BB V6 전략: BB V2 상속 + 밴드 기울기(상/중/하단 slope) 정렬을 direction에 가산(`slope_lookback`/`slope_threshold`/`slope_weight`, 기본 3/0.001/0.5, 세 밴드 모두 정렬 시 ±1.5) + Squeeze 감지(`squeeze_bbw_ratio`, 기본 0.7; BBW가 rolling 평균의 해당 비율 미만이면 squeeze) 시 sideways 강제(`block_entry_on_squeeze=true`) — 후행 지표 의존을 완화하여 밴드 자체 움직임으로 국면 방향성 보강
- BB V7 전략: BB V2 상속 + **가격-밴드 돌파 기반 국면 판단** + V5 방식 hysteresis — ADX/EMA/MACD/DI 등 후행 지표 의존을 완전히 제거. 추세 상승 = (BB 폭 > 직전 N봉 평균 폭 × `width_expand_ratio`) AND (종가 > 직전 N봉 close 최고가 × (1 + `break_buffer_pct`)). 추세 하락은 하단 대칭. 그 외 횡보. 기본값 `width_lookback=5`/`width_expand_ratio=1.05`/`break_lookback=5`/`break_buffer_pct=0.001`/`hysteresis_candles=3`. V6의 squeeze 강제 sideways가 하락 추세 중 BB 수축을 횡보로 오판하는 문제 해결
- BB V8 전략: BB V2 상속 + 세 밴드 price 변화 조합 기반 국면 판단 — 다섯 조건 AND로 TREND_UP만 판정(그 외 SIDEWAYS): ① bb_upper > 직전 `band_avg_lookback` 봉 평균, ② close > bb_upper, ③ bb_lower < 직전 N봉 평균, ④ 폭 확장, ⑤ bb_middle 상승. TREND_DOWN은 미정의. 기본 `band_avg_lookback=3`
- BB V9 전략: **BB V4 상속** + **4개 독립 규칙 투표 기반 국면 판단** + V5 방식 hysteresis + **추세장 역추세 진입 차단(Option A)** + **V4 쿨다운** + **entry_regime 기반 Stop&Reverse + 분기 미스매치 차단 + 강한 추세 동적 트레일링** — 특정 백테스트 차트에서 드러난 오판 패턴(급락을 sideways 처리 / 1캔들 스파이크를 trend로 승격 / hysteresis 해제 직후 whipsaw / 추세 LONG 위에 횡보 분기 물타기 / trend_up→sideways→trend_down 경로에서 SHORT 진입 가드 차단)을 다층으로 해결. (A) 캔들 몸통 누적 방향성(`body_window`봉 sign(close-open)·|close-open|/ATR 합 ≥ `body_threshold`), (B) BB 외부 체류 연속 캔들 수(≥ `out_streak_min`봉 연속이면 추세), (C) 스윙 구조(최근 `swing_window`봉 vs 이전 `swing_window`봉의 high/low 모두 상승=HH+HL → +1, 모두 하락=LH+LL → -1), (D) 중단선 대비 종가 위치의 지속성(`mid_persist_window`봉 연속 동일부호 AND 괴리율 확장). 각 규칙이 -1/0/+1 반환 → 합산 `vote_threshold` 이상이면 TREND. 추가로 `_trend_signals`를 오버라이드하여 `generate_trend_signals(..., allow_counter_trend=False)` 로 호출 — 추세장에서는 추세추종 방향 진입만 허용(BB 상단=확인된 UP에서만 Long, BB 하단=확인된 DOWN에서만 Short). V4 상속으로 trend→sideways 전환 직후 `cooldown_candles` (기본 5) 동안 횡보 신규 진입 차단 — hysteresis 해제 직후 추세 재개로 인한 whipsaw 방지 (예: SOL 2026-04-09 08:00 "횡보 반전매수 2차"가 09:00 trend_down 재진입으로 손실로 이어지던 케이스 차단). 물타기 후 손절/트레일링/익절 로직은 유지. **`generate_signals` 오버라이드로 추가 4기능 — (1) `long_entry_regime`/`short_entry_regime` 추적 (1차 진입 시점의 regime 기록), (2) **Stop & Reverse**: 보유 LONG의 entry_regime=trend_up + 현재 regime=trend_down 일 때 (sideways 경유 포함) LONG 강제 청산 + SHORT 1차 신규 진입을 한 캔들에 동시 발생 — `trend.py` 의 `long_step==0` 가드 우회를 위해 직접 시그널 생성, (3) **분기 미스매치 차단**: 보유 포지션의 entry_regime 과 현재 regime 이 다르면(예: trend_up LONG 위에 sideways 분기 LONG 추가) 같은 방향 추가 진입 시그널 무시 — 박스 4 04-15 02:00 "횡보 반전매수 2차" 케이스 직접 차단, (4) **강한 추세 동적 트레일링**: `|v9_score_total| >= strong_score_threshold` 인 캔들에서는 `_trend_signals` 의 `trailing_stop_pct` 를 `strong_trailing_multiplier` 배 적용하여 박스 1 처럼 -10% 하락 중 +0.5% 되돌림으로 너무 빨리 빠지는 문제 완화. 토글 파라미터 `stop_and_reverse=True`/`block_branch_mismatch=True`/`strong_trailing_multiplier=3.0` 으로 옵션 제어 가능. 기본값 `atr_window=14`/`body_window=5`/`body_threshold=2.0`/`out_streak_min=2`/`swing_window=5`/`mid_persist_window=5`/`vote_threshold=2`/`hysteresis_candles=3`/`cooldown_candles=5`/`strong_score_threshold=3`/`strong_trailing_multiplier=3.0`/`block_branch_mismatch=True`/`stop_and_reverse=True`/`log_regime_per_candle=True` (signal.log 에 매 봉 `V9 봉 \| {ts} \| {regime} \| A/B/C/D total \| close bbp` 한 줄씩 INFO 출력 — 부담스러우면 false 로 토글)
- 매매 기록 DB 저장: 모드별로 3개 테이블에 분리 저장 — 실거래=`trades`, 백테스트=`backtest_trades`, 시뮬레이터=`simulator_trades` (모두 동일 스키마)
- `DatabaseStorage.TRADE_TABLES` dict로 모드→테이블 매핑, `save_trade(..., mode=...)` / `load_trades(..., mode=...)` / `clear_trades(exchange, symbol, mode, timeframe=...)` 제공
- `BacktestEngine`은 `db`/`save_mode`/`timeframe` 인자로 DB 저장 활성화 (main.py가 `db`, `save_mode="backtest"` 주입, 실행 전 이전 결과 `clear_trades`)
- `LiveSimulator`는 내부 `BacktestEngine`에 `save_mode="simulator"` 전달 → simulator_trades 테이블에 누적 저장 (세션간 보존)
- asset_history: 이벤트별(시작/진입/청산/동기화/종료) 잔고, 평가금, 포지션 상태, 누적 수수료/펀딩비, 일일 PnL, 청산가 — 실거래 전용
- 차트 시각화: `src/visualize/TradeChart` — plotly 캔들스틱 + BB 상/중/하단 + 매매 시그널 화살표(▲LONG/▼SHORT/■청산/✖손절/★익절) + 포지션 보유 구간 배경 음영(long=초록/short=빨강) + equity curve
- 차트 자동 생성: 백테스트는 리포트 이후 자동, 시뮬레이터/트레이더는 종료 시(`_save_summary`) 자동 — 모두 in-memory 시그널로 렌더링
- `chart` CLI로 DB에서 on-demand 생성 — `--mode {trader,backtest,simulator}` (기본 trader)로 조회 테이블 선택, `--timeframe` 필터
- 차트 저장 경로: 백테스트=`data/backtest/{날짜}/{SYMBOL}/chart_*.html`, 시뮬레이터=`data/simulator/{SYMBOL}/charts/`, 트레이더=`data/trader/{SYMBOL}/charts/`, chart CLI=`data/charts/{mode}/{SYMBOL}/`

## 현재 구현 상태

- [x] 데이터 수집 (ccxt 래퍼, 페이지네이션, 다중 거래소, 이어서 수집)
- [x] 타임프레임 리샘플링 (5m → 15m, 1h, 1d, 1w, 1M)
- [x] 저장소 (SQLite DB + CSV)
- [x] 기술적 지표 래퍼 (ta)
- [x] BB 전략 (횡보 반전매매 3단계 물타기 + 횡보장 레버리지 제한 + 추세추종, ADX 다중지표 국면판단)
- [x] BB MTF 전략 (다중 타임프레임 국면 판단 — 기준 TF 위/아래 TF 국면 참고로 허위 전환 필터링)
- [x] BB V2 / BB V2 MTF 전략 (BBW 최소 기준 + 물타기 간격 제한, bb_v2/bb_v2_mtf)
- [x] BB V3 전략 (bb_v3) — V2 + BB% 극단 돌파 필터(A) + ADX OR 차단(B), 밴드 돌파/고ADX 구간 역추세 진입 방지
- [x] BB V4 전략 (bb_v4) — V2 + 국면 전환(trend→sideways) 쿨다운(C), 전환 애매 구간 신규진입 차단
- [x] BB V5 전략 (bb_v5) — V2 + Regime hysteresis, 추세 일시 정지를 추세 종료로 오판하지 않도록 trend→sideways 전환에 N캔들 연속 조건 요구
- [x] BB V6 전략 (bb_v6) — V2 + 밴드 기울기(상/중/하단 slope) direction 보강(±1.5) + Squeeze 감지 시 sideways 강제, 후행 지표 의존 완화로 국면 방향성 판단 개선
- [x] BB V7 전략 (bb_v7) — V2 + 가격-밴드 돌파 기반 국면 판단(BB폭 확장 AND 종가가 직전 N봉 고점/저점 돌파) + V5 hysteresis. 후행 지표 의존 제거로 추세 진입/종료 지연 해소, V6의 squeeze 강제 sideways 오판 해결
- [x] BB V8 전략 (bb_v8) — V2 + 세 밴드 price 변화 조합 기반 TREND_UP 판정 (상단/중단/하단·폭·돌파 다섯 조건 AND)
- [x] BB V9 전략 (bb_v9) — V4 상속 + 4개 독립 규칙 투표(몸통 누적 방향성·BB 외부 체류·스윙구조·중단 괴리 지속성) + V5 hysteresis + 추세장 역추세 진입 차단(Option A) + V4 쿨다운. 급락/급등 신속 감지 + 1캔들 스파이크 오판 방지 + 추세장 칼날 잡기 제거 + hysteresis 해제 직후 whipsaw 차단
- [~] 업비트 거래소 지원 (`src/exchange/upbit.py` — 2026-04-17 병합 시점에 파일만 포팅됨, 팩토리/심볼정규화/인증 코드 통합 필요)
- [x] 백테스트 엔진 (시뮬레이션, 평가 지표, 텍스트/HTML 리포트, 국면별/방향별 분석 통계)
- [x] 백테스트 자동 수집 (실행 전 DB 마지막 시점 → 최신까지 이어서 수집 + CSV 출력, `--no-auto-collect`로 비활성화)
- [x] 라이브 시뮬레이터 (실시간 데이터 + 가상 매매 페이퍼 트레이딩)
- [x] 실거래 트레이더 (Binance Futures, .env API 키, 격리마진, 일일손실제한)
- [x] 실거래 상태 저장/복원 (재시작 시 데이터 보존, --capital 명시로 초기화)
- [x] 거래 수수료/펀딩 수수료 추적 (PnL 반영, 로그/CSV 기록)
- [x] Liquidation price 추적 (포지션 정보에 청산가 및 근접도 표시)
- [x] 시작 시 즉시 매매 판단 (재시작/접속 복귀 시 timeframe 대기 없이 1회 즉시 실행)
- [x] Emergency stop order (진입/추매마다 거래소 서버사이드 STOP_MARKET 등록, 마진 콜 방지)
- [x] 실거래 매매결과 DB 저장 (trades 테이블 + asset_history 테이블, SQLite)
- [x] 차트 시각화 (plotly HTML — 캔들 + BB + 매매 시그널 화살표 + 포지션 음영 + equity curve, 백테스트/시뮬레이터/트레이더/chart CLI 공통)
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

# 차트 생성 (DB OHLCV + 매매기록으로 HTML 차트, 최근 2000캔들 기본)
python -m src.main chart -e binance_futures -s btc -t 1h                    # trader(trades)
python -m src.main chart -e binance_futures -s btc -t 1h --mode backtest    # backtest_trades
python -m src.main chart -e binance_futures -s btc -t 1h --mode simulator   # simulator_trades
python -m src.main chart -e binance_futures -s btc -t 1h --start 2026-03-01 --end 2026-04-01

# 거래소 목록
python -m src.main list-exchanges
```
