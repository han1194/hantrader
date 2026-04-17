# Git 사용 가이드 (HanTrader)

## 1. 완료된 세팅 내역

### 1-1. Git 초기화 (2026-04-17)

- 프로젝트 폴더에 git 저장소 초기화
- `.gitignore` 설정 완료 (아래 항목은 git에 포함되지 않음)
  - `.env` (API 키)
  - `data/db/`, `data/csv/`, `data/backtest/`, `data/simulator/`, `data/trader/`, `data/logs/`
  - `__pycache__/`, `*.log`, IDE 설정 등
- 첫 커밋 생성 (47개 파일)

### 1-2. 원격 저장소 2개 연결

| 이름 | 위치 | 용도 |
|---|---|---|
| `github` | https://github.com/han1194/hantrader.git | 인터넷 동기화 (Private, 본인만 접근 가능) |
| `usb` | E:/hantrader.git | USB 오프라인 동기화 |

### 1-3. Git 사용자 설정

```user.email = jungmok.han80@gmail.com
   user.name  = Han
```

---

## 2. 기본 개념

```[회사 PC] ──push──▶ [GitHub / USB] ◀──push── [집 PC]
   [회사 PC] ◀──pull── [GitHub / USB] ──pull──▶ [집 PC]
```

- **commit** : 변경사항을 저장하는 단위 (세이브 포인트)
- **push** : 내 PC의 커밋을 원격 저장소(GitHub/USB)에 올림
- **pull** : 원격 저장소의 최신 커밋을 내 PC로 가져옴
- **staging (add)** : 커밋할 파일을 선택하는 과정

---

## 3. 일상 사용법

### 3-1. 작업 시작 전 (최신 코드 가져오기)

```bash
# 인터넷 환경
git pull github main

# 또는 USB 환경 (USB 꽂은 상태)
git pull usb main
```

> 반드시 작업 시작 전에 pull부터 하는 습관을 들여야 충돌을 방지할 수 있다.

### 3-2. 작업 중 상태 확인

```bash
# 어떤 파일이 변경되었는지 확인
git status

# 변경 내용 상세 확인
git diff
```

### 3-3. 작업 끝난 후 (저장 + 업로드)

```bash
# 1단계: 변경된 파일 선택 (staging)
git add .                    # 변경된 파일 전부 선택
git add src/main.py          # 특정 파일만 선택할 때

# 2단계: 커밋 (세이브 포인트 생성)
git commit -m "작업 내용 설명"

# 3단계: 원격 저장소에 올리기
git push github main         # GitHub에 올리기
git push usb main            # USB에 올리기 (USB 꽂은 상태)
```

### 3-4. 한눈에 보는 흐름

```코드 수정 → git add . → git commit -m "설명" → git push github main
                                              → git push usb main
```

---

## 4. 자주 쓰는 명령어 모음

|       명령어             |        설명                         |
|-------------------------|------------------------------------|
| `git status`            | 현재 상태 확인 (변경/추가/삭제된 파일)  |
| `git diff`              | 변경된 내용 상세 보기                 |
| `git log --oneline -10` | 최근 커밋 10개 한줄로 보기            |
| `git add .`             | 모든 변경 파일 staging               |
| `git add 파일명`         | 특정 파일만 staging                  |
| `git commit -m "메시지"` | 커밋 생성                            |
| `git push github main`  | GitHub에 push                       |
| `git push usb main`     | USB에 push                          |
| `git pull github main`  | GitHub에서 pull                     |
| `git pull usb main`     | USB에서 pull                        |
| `git remote -v`         | 등록된 원격 저장소 목록                |

---

## 5. 집 PC 최초 세팅 절차

집 PC에서 처음 한 번만 실행하면 된다.

### 5-1. Git 설치 확인

```bash
git --version
```

설치 안 되어 있으면 https://git-scm.com 에서 다운로드.

### 5-2. 프로젝트 복제

```bash
# GitHub에서 복제 (인터넷 환경)
git clone https://github.com/han1194/hantrader.git /c/han/claude_code/hantrader

# 또는 USB에서 복제 (USB 꽂은 상태, 드라이브 문자 확인)
git clone E:/hantrader.git /c/han/claude_code/hantrader
```

### 5-3. 기본 설정

```bash
cd /c/han/claude_code/hantrader

# git 사용자 설정
git config --global user.email "jungmok.han80@gmail.com"
git config --global user.name "Han"

# USB remote 추가 (GitHub으로 복제한 경우)
git remote add usb E:/hantrader.git
git config --global --add safe.directory E:/hantrader.git

# GitHub remote 추가 (USB로 복제한 경우)
git remote add github https://github.com/han1194/hantrader.git

# remote 이름 정리 (clone 시 자동 생성된 origin 제거)
git remote rename origin github   # GitHub으로 복제한 경우
git remote rename origin usb      # USB로 복제한 경우
```

### 5-4. .env 파일 생성

`.env`는 git에 포함되지 않으므로 직접 만들어야 한다.

```bash
cp .env.example .env
```

`.env` 파일을 열어서 API 키 입력.

### 5-5. Python 환경 설치

집 PC에는 이미 `bot310` 환경이 있으므로 그대로 사용.
새로 만들어야 한다면:

```bash
conda create -n bot310 python=3.11
conda activate bot310
pip install -r requirements.txt
```

---

## 6. 문제 상황별 대처법

### 6-1. push가 거부될 때 (reject)

다른 PC에서 먼저 push한 내용이 있을 때 발생한다.

```bash
# 먼저 pull로 가져온 후 다시 push
git pull github main
git push github main
```

### 6-2. pull 할 때 충돌 (conflict) 발생

양쪽에서 같은 파일의 같은 부분을 수정했을 때 발생한다.

```
<<<<<<< HEAD
내 PC의 코드
=======
원격 저장소의 코드
>>>>>>> 커밋해시
```

1. 파일을 열어서 `<<<<<<<`, `=======`, `>>>>>>>` 표시를 찾는다
2. 둘 중 원하는 코드를 남기고 표시를 삭제한다
3. 저장 후:

```bash
git add .
git commit -m "충돌 해결"
git push github main
```

> 충돌을 피하려면: 항상 작업 시작 전에 pull을 먼저 하면 대부분 방지된다.

### 6-3. 실수로 커밋한 것을 되돌리고 싶을 때

```bash
# 직전 커밋 취소 (변경 내용은 유지, 커밋만 취소)
git reset --soft HEAD~1

# 파일 하나만 변경 전으로 되돌리기
git checkout -- 파일명
```

### 6-4. USB 드라이브 문자가 바뀌었을 때

USB가 `E:`가 아닌 다른 문자(예: `F:`)로 잡힐 때:

```bash
# 기존 usb remote 제거 후 새로 등록
git remote remove usb
git remote add usb F:/hantrader.git
git config --global --add safe.directory F:/hantrader.git
```

### 6-5. 커밋 안 하고 다른 PC 작업을 가져오고 싶을 때

작업 중인 내용을 임시 저장(stash)할 수 있다.

```bash
# 임시 저장
git stash

# pull 실행
git pull github main

# 임시 저장한 내용 복원
git stash pop
```

---

## 7. PC별 환경 정보

| | 회사 PC | 집 PC |
|---|---|---|
| conda 환경 이름 | `trading` | `bot310` |
| 프로젝트 경로 | `/c/han/claude_code/hantrader` | (집 PC에서 clone한 경로) |

---

## 8. git에 포함되지 않는 파일 (PC마다 별도 관리)

이 파일들은 `.gitignore`에 의해 git에서 제외된다. 각 PC에서 직접 관리해야 한다.

| 파일/폴더 | 설명 | 비고 |
|---|---|---|
| `.env`              | API 키              | `.env.example` 복사 후 키 입력 |
| `data/db/`          | SQLite DB           | 수집 데이터, 각 PC에서 개별 생성 |
| `data/csv/`         | CSV 출력              | |
| `data/backtest/`    | 백테스트 리포트         | |
| `data/logs/`        | 로그 파일             | |
| `data/trader/`      | 실거래 상태/거래내역    | |
| `data/simulator/`   | 시뮬레이터 데이터       | |

---

## 8. 권장 작업 루틴

```
┌─────────────────────────────────────────┐
│            매일 작업 루틴                 │
├─────────────────────────────────────────┤
│                                         │
│  1. VSCode에서 프로젝트 폴더 열기           │
│     터미널(Ctrl+`) 열고 conda 활성화       │
│     conda activate trading  ← 회사      │
│     conda activate bot310   ← 집        │
│                                         │
│  2. 최신 코드 가져오기                     │
│     git pull github main                │
│                                         │
│  3. 코드 작업 진행                        │
│     ...                                 │
│                                         │
│  4. 작업 끝나면 저장                      │
│     git add .                           │
│     git commit -m "작업 내용"            │
│     git push github main                │
│     git push usb main  ← USB 있을 때     │
│                                         │
│  5. 다른 PC에서 2번부터 반복               │
│                                         │
└─────────────────────────────────────────┘
```

## 9. 시작 - 종료

``` VSCode 터미널에서 그대로 하면 됩니다.


  # VSCode 터미널 열기 (Ctrl + `)
  conda activate trading
  git pull github main

  # 작업 ...

  # 끝나면
  git add .
  git commit -m "작업 내용"
  git push github main

참고로 conda activate는 git과는 관계없습니다. git 명령어는 conda 환경 활성화 없이도 동작합니다. 다만 코드 실행(python -m src.main ...)할 때 conda 환경이 필요하니 습관적으로 먼저 activate 하는 건 좋습니다.

그리고 현재 conda 환경 이름이 trading이군요.
