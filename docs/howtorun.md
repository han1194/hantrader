# HanTrader 실행 가이드

## 사전 준비

```bash
# Python 3.11+ 필요
pip install -r requirements.txt
```

## 명령어 목록

모든 명령어는 프로젝트 루트에서 실행합니다.

```bash
python -m src.main <command> [options]
```

---

## 1. 데이터 수집 (collect)

거래소에서 OHLCV 데이터를 수집하여 DB/CSV에 저장합니다. API 키 없이 공개 데이터만 사용합니다.

```bash
# 기본 수집 (config.yaml에 설정된 거래소/심볼)
python -m src.main collect

# 특정 거래소 지정
python -m src.main collect -e binance_futures

# 특정 심볼 지정
python -m src.main collect -e binance_futures --symbols BTC/USDT,ETH/USDT
python -m src.main collect -e binance_futures --symbols BTC/USDT,ETH/USDT,XRP/USDT,SOL/USDT,DOGE/USDT

# 기간 지정 수집
python -m src.main collect -e binance_futures --start 2024-01-01 --end 2024-12-31

# 이어서 수집 (--start 미지정 시 DB 마지막 시점부터 자동 이어서 수집)
python -m src.main collect -e binance_futures --symbols BTC/USDT
```

- 기본 타임프레임: 5m (config에서 변경 가능)
- 파생 타임프레임 (15m, 1h, 1d, 1w, 1M)은 자동 리샘플링 생성
- 데이터 저장: `data/db/hantrader.db` (SQLite) + `data/csv/` (CSV)

---

## 2. CSV 내보내기 (export)

DB에 저장된 데이터를 원하는 타임프레임으로 CSV 파일로 내보냅니다.

```bash
# 1시간봉 CSV 내보내기
python -m src.main export -e binance_futures -s BTC/USDT -t 1h

# 기간 지정
python -m src.main export -e binance_futures -s BTC/USDT -t 4h --start 2024-06-01 --end 2024-12-31

# 출력 디렉토리 지정
python -m src.main export -e binance_futures -s BTC/USDT -t 1h -o data/export
```

- DB에 해당 타임프레임 데이터가 없으면 5m 데이터에서 자동 리샘플링
- 지원 타임프레임: 5m, 15m, 1h, 4h, 1d, 1w, 1M

---

## 3. 전략 시그널 생성 (strategy)

수집된 데이터로 전략 시그널을 생성합니다. `config/config.yaml`의 `strategy.name`에 따라 전략이 선택됩니다.

```bash
# BB 전략 (기본값: strategy.name: "bb")
python -m src.main strategy -e binance_futures -s BTC/USDT -t 1h

# BB MTF 전략 사용 시: config.yaml에서 strategy.name: "bb_mtf"로 변경 후 동일 명령어
```

- 시그널 결과를 터미널에 출력하고 CSV로 저장
- BB MTF 전략은 기준 TF의 위/아래 인접 TF 국면을 참고하여 허위 국면 전환을 필터링

---

## 4. 백테스트 (backtest)

과거 데이터로 전략을 시뮬레이션합니다.

```bash
# 단일 심볼 실행
python -m src.main backtest -e binance_futures -s BTC/USDT

# 여러 코인 동시 백테스트 (쉼표 구분)
python -m src.main backtest -e binance_futures -s BTC/USDT,ETH/USDT

# 기간 지정
python -m src.main backtest -e binance_futures -s BTC/USDT --start 2026-01-01 --end 2026-03-31
python -m src.main backtest -e binance_futures -s BTC/USDT --start 2026-01-01 --capital 100

# 자본금/레버리지 지정
python -m src.main backtest -e binance_futures -s BTC/USDT --capital 5000 --leverage-max 30

# 실제 테스트
python -m src.main backtest -e binance_futures -s BTC/USDT --start 2026-01-01 --capital 100
```

- 리포트 출력: `data/backtest/` (텍스트, HTML 대시보드, 거래 내역 CSV)
- 실행마다 타임스탬프 포함 파일명으로 이력 보존
- `--start` 지정 시 자동으로 100캔들 워밍업 데이터 추가 로드

### 평가 지표

| 지표 | 설명 | 기준 |
|------|------|------|
| Total Return | 전체 수익률 (최종/초기 - 1) | 양수면 수익 |
| Sharpe Ratio | 위험 대비 수익 (연간화) | 1이상 양호, 2이상 우수 |
| Max Drawdown | 고점 대비 최대 하락 비율 | 작을수록 좋음 |
| Win Rate | 수익 거래 수 / 전체 거래 수 | 높을수록 좋음 |
| Profit Factor | 총 수익 / 총 손실 절대값 | 1이상 수익, 2이상 우수 |

---

## 5. 라이브 시뮬레이터 (simulate)

실시간 거래소 데이터를 수신하며 가상 매매를 실행하는 페이퍼 트레이딩입니다. API 키 불필요.

```bash
# 기본 실행
python -m src.main simulate -e binance_futures -s BTC/USDT

# 타임프레임/자본금 지정
python -m src.main simulate -e binance_futures -s BTC/USDT -t 1h --capital 100
python -m src.main simulate -e binance_futures -s ETH/USDT -t 15m --capital 100
python -m src.main simulate -e binance_futures -s XRP/USDT -t 5m --capital 100
python -m src.main simulate -e binance_futures -s SOL/USDT -t 5m --capital 100

# 폴링 간격 지정 (초)
python -m src.main simulate -e binance_futures -s BTC/USDT --interval 30
```

- Ctrl+C로 중지 시 요약 출력 + 거래 내역 CSV 저장
- 로그 파일: `data/simulator/sim_{exchange}_{symbol}_{tf}_{timestamp}.log`

---

## 6. 실거래 트레이더 (trade)

전략 시그널에 따라 Binance Futures에서 실제 주문을 실행합니다.

### API 키 설정

```bash
# 1. .env.example을 .env로 복사
cp .env.example .env

# 2. .env 파일 편집 — API 키 입력
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# 테스트넷 사용 시 (권장: 실거래 전 테스트)
BINANCE_TESTNET=true
```

### 실행

```bash
# 실거래 실행 (실행 전 "yes" 확인 필요)
python -m src.main trade -e binance_futures -s BTC/USDT -t 1h

# 일일 손실 제한 설정
python -m src.main trade -e binance_futures -s BTC/USDT --daily-loss-limit 50

# 레버리지 지정
python -m src.main trade -e binance_futures -s BTC/USDT --leverage-max 25 --leverage-min 10
```

### 안전장치

- 실거래 시작 전 "yes" 입력 확인 (테스트넷 제외)
- 1회 진입 마진 상한 (`max_margin_per_entry`)
- 일일 최대 손실 제한 도달 시 신규 진입 차단
- 격리 마진 모드 (기본) — 포지션별 마진 격리
- 청산 주문은 `reduceOnly` 파라미터로 보호
- Ctrl+C 시 포지션 유지 + 로그/CSV 저장 (자동 청산 안 함)
- 10틱마다 거래소 잔고/포지션 자동 동기화

### 출력 파일

- 로그: `data/trader/trade_{exchange}_{symbol}_{tf}_{timestamp}.log`
- 거래 내역: `data/trader/trades_{exchange}_{symbol}_{tf}_{timestamp}.csv`

---

## 7. 거래소 목록 (list-exchanges)

```bash
python -m src.main list-exchanges
```

---

## 전략 선택

`config/config.yaml`의 `strategy.name` 필드로 전략을 선택합니다.

| 전략 이름 | 설명                                                     |
|-----------|----------------------------------------------------------|
| `bb`      | 기본 BB 전략 — 단일 타임프레임 국면 판단                 |
| `bb_mtf`  | BB MTF 전략 — 다중 타임프레임 국면 판단 (기존 BB 상속)   |

### BB MTF 전략 (bb_mtf)

기존 BB 전략의 국면 판단을 인접 타임프레임으로 보강합니다. 매매 로직(진입/손절/익절)은 기존 BB 전략과 동일하며, **국면 판단(횡보↔추세)만 다중 TF 가중 투표로 변경**됩니다.

| 기준 TF  | 하위 TF  | 상위 TF |
|----------|----------|---------|
| 5m       | 3m       | 15m     |
| 15m      | 5m       | 30m     |
| 30m      | 15m      | 1h      |
| **1h**   | **30m**  | **2h**  |
| 2h       | 1h       | 4h      |
| 4h       | 2h       | 8h      |
| 1d       | 12h      | 1w      |

**가중 투표 방식:**

- 기준 TF 국면: ±2.0점
- 상위 TF 국면: ±1.0점 (큰 흐름 확인)
- 하위 TF 국면: ±0.5점 (세밀한 전환 포착)
- 총점 |score| >= 임계값(기본 2.5) → 추세, 미만 → 횡보

기본 임계값 2.5이므로 기준 TF가 추세(±2)여도 **인접 TF 최소 1개가 추세를 확인**해야 추세로 판정합니다.

```yaml
# config/config.yaml MTF 설정 예시
strategy:
  name: "bb_mtf"
  mtf_weight_upper: 1.0       # 상위 TF 가중치
  mtf_weight_lower: 0.5       # 하위 TF 가중치
  mtf_trend_threshold: 2.5    # 추세 판정 임계값
```

> **백테스트 비교 방법**: `strategy.name`만 `"bb"` ↔ `"bb_mtf"`로 변경하여 동일 조건으로 백테스트 후 결과를 비교하세요.

---

## BB 전략 규칙

### 국면 판단 — 단일 TF (bb 전략)

1. **추세 강도**: ADX(>=25: 2점, 20~25: 1점) + BB width 확대(1점)
2. **추세 방향**: EMA 12/26(+/-1.5) + 가격/SMA20(+/-1.0) + MACD diff(+/-1.0) + DI+/DI-(+/-1.0)
3. 강도 >= 2.0 AND |방향| >= 2.0 → 추세장, 그 외 → 횡보장

### 횡보장 (반전매매, 3단계 물타기)

| 항목 | Long | Short |
|------|------|-------|
| 1차 진입 | BB% <= 0.25 (15%) | BB% >= 0.75 (15%) |
| 2차 물타기 | BB% <= 0.10 (10%) | BB% >= 0.90 (10%) |
| 3차 물타기 | BB% <= -0.05 (10%) | BB% >= 1.05 (10%) |
| 익절 | BB% >= 0.65 | BB% <= 0.35 |
| 손절 | BB% <= -0.15 (100%) | BB% >= 1.15 (100%) |
| 레버리지 | 횡보장 상한 적용 (기본 15x) | 동일 |

### 추세장 (추세추종)

- 상승추세 + BB상단 → Long, 하락추세 + BB하단 → Short
- MACD/RSI/Volume 2개 이상 확인 시 진입
- 물타기 3회 후 손절 -2% / 익절 +3% (레버리지 적용 전)
- 레버리지: BB width 기반 동적 조정 (max~min)

---

## 설정 파일

`config/config.yaml`에서 주요 설정을 변경할 수 있습니다.

| 항목 | 설명 | 기본값 |
|------|------|--------|
| `backtest.initial_capital` | 초기 자본금 (USDT) | 1000 |
| `backtest.min_investment` | 최소 투자 수량 (코인) | 0.001 |
| `backtest.max_margin_per_entry` | 1회 진입 마진 상한 (USDT) | 50 |
| `backtest.leverage_max` | 최대 레버리지 | 50 |
| `backtest.leverage_min` | 최소 레버리지 | 50 |
| `backtest.sideways_leverage_max` | 횡보장 레버리지 상한 | 15 |
| `collector.base_timeframe` | 기본 수집 타임프레임 | 5m |
| `simulator.lookback_candles` | 시뮬레이터 워밍업 캔들 수 | 100 |
| `trader.margin_mode` | 마진 모드 (isolated/cross) | isolated |
| `trader.daily_loss_limit` | 일일 최대 손실 (USDT, 0=무제한) | 100 |

---

## 공통 옵션

| 옵션 | 설명 |
|------|------|
| `--config` | 설정 파일 경로 (기본: config/config.yaml) |
| `--log-level` | 로그 레벨: DEBUG, INFO, WARNING, ERROR (기본: INFO) |
| `-e, --exchange` | 거래소 이름 (예: binance_futures) |
| `-s, --symbol` | 심볼 (예: BTC/USDT) |
| `-t, --timeframe` | 타임프레임 (예: 5m, 15m, 1h, 4h, 1d) |

---

## 실행 흐름 요약

```text
1. collect  → 거래소 OHLCV 데이터 수집 (DB + CSV)
2. strategy → 시그널 생성 (확인용)
3. backtest → 과거 데이터 시뮬레이션 (전략 검증)
4. simulate → 실시간 페이퍼 트레이딩 (실전 검증)
5. trade    → 실거래 실행 (API 키 필요)
```
