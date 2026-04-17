# HanTrader 클라우드 24시간 운영 가이드

클라우드를 처음 사용하는 사람을 위한 가이드. 회원가입부터 실제 봇 구동까지 단계별로 설명한다.

---

## 목차

1. [클라우드란?](#1-클라우드란)
2. [클라우드 업체 선택](#2-클라우드-업체-선택)
3. [Oracle Cloud 가입 및 서버 생성](#3-oracle-cloud-가입-및-서버-생성)
4. [AWS Lightsail 가입 및 서버 생성 (대안)](#4-aws-lightsail-가입-및-서버-생성-대안)
5. [서버 접속 (SSH)](#5-서버-접속-ssh)
6. [서버 초기 설정](#6-서버-초기-설정)
7. [HanTrader 설치](#7-hantrader-설치)
8. [환경변수 설정 (.env)](#8-환경변수-설정-env)
9. [수동 실행 테스트](#9-수동-실행-테스트)
10. [24시간 자동 실행 (systemd)](#10-24시간-자동-실행-systemd)
11. [서버 보안 설정](#11-서버-보안-설정)
12. [배포 (코드 업데이트)](#12-배포-코드-업데이트)
13. [모니터링 및 알림](#13-모니터링-및-알림)
14. [백업](#14-백업)
15. [비용 정리](#15-비용-정리)
16. [트러블슈팅](#16-트러블슈팅)

---

## 1. 클라우드란?

인터넷에 있는 다른 사람의 컴퓨터를 빌려서 쓰는 것이다.
내 PC를 끄더라도 클라우드 서버는 24시간 켜져 있으므로 자동매매 봇을 계속 돌릴 수 있다.

**필요한 이유:**

- 내 PC를 24시간 켜두지 않아도 됨
- 네트워크 끊김 위험이 적음
- 서버가 죽어도 자동 재시작 설정 가능

---

## 2. 클라우드 업체 선택

### HanTrader가 필요한 스펙

매우 가벼운 프로그램이다. 최저 사양으로 충분하다.

|   항목  |        최소         | 권장       |
|--------|--------------------|------------|
| CPU    | 1 vCPU             | 1~2 vCPU   |
| RAM    | 512 MB             | 1~2 GB     |
| 디스크  | 20 GB              | 40 GB+     |
| OS     | Ubuntu 22.04 LTS   | Ubuntu 22.04/24.04 LTS |
| 리전    | 아시아              | 도쿄 또는 서울 |

### 업체 비교

|        업체        |   월 비용  | 난이도 |   추천도    |         비고      |
|-------------------|-----------|--------|-----------|-------------------|
| **Oracle Cloud**  |  **무료**  |   중   | ★★★★★ | 영구 무료, 스펙 넉넉 |
| **AWS Lightsail** |    $5     |   하   |  ★★★★  | 가장 쉬움, 도쿄 리전 |
| Vultr             |    $6     |   하   |   ★★★   | 간단, 도쿄/서울     |
| DigitalOcean      |    $6     |   하   |   ★★★   | 간단, 싱가포르      |

**추천:**

- 비용 최우선 → **Oracle Cloud** (영구 무료)
- 쉬운 설정 최우선 → **AWS Lightsail** (월 $5, 약 7,000원)

이 가이드에서는 **Oracle Cloud (무료)**를 기본으로, **AWS Lightsail**을 대안으로 설명한다.

---

## 3. Oracle Cloud 가입 및 서버 생성

### 3-1. 회원가입

1. 브라우저에서 `https://cloud.oracle.com` 접속
2. **"Start for free"** 또는 **"무료로 시작"** 클릭
3. 정보 입력:
   - **Country**: South Korea
   - **이름/성**: 영문으로 입력
   - **이메일**: 본인 이메일 (인증 필요)
   - **Home Region**: **South Korea (Chuncheon)** 선택 (서울 리전은 없고 춘천이 국내 리전)
     - 춘천이 없으면 **Japan East (Tokyo)** 선택
     - **주의: Home Region은 가입 후 변경 불가!** 신중하게 선택
4. 이메일 인증 링크 클릭
5. **비밀번호 설정** (대문자+소문자+숫자+특수문자 조합)
6. **결제 카드 등록** (본인 인증용, 무료 티어만 쓰면 과금 안 됨)
   - Visa 또는 Mastercard 필요
   - $1 인증 결제 후 즉시 취소됨
7. 가입 완료 → **Oracle Cloud Console** 접속

### 3-2. SSH 키 생성 (서버 접속용)

서버에 접속하려면 SSH 키가 필요하다. 내 PC에서 미리 만들어둔다.

**Windows (PowerShell 또는 Git Bash):**

```bash
# Git Bash 또는 PowerShell에서 실행
ssh-keygen -t ed25519 -f ~/.ssh/oracle_cloud

# 엔터 2번 (비밀번호 없이 생성)
# 결과:
#   ~/.ssh/oracle_cloud       ← 개인키 (절대 공유하지 말 것!)
#   ~/.ssh/oracle_cloud.pub   ← 공개키 (서버에 등록할 것)
```

공개키 내용 확인 (이후 서버 생성 시 붙여넣기용):

```bash
cat ~/.ssh/oracle_cloud.pub
```

출력 예시: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... user@DESKTOP-XXX`

### 3-3. 인스턴스(서버) 생성

1. Oracle Cloud Console → 좌상단 햄버거 메뉴(☰) → **Compute** → **Instances**
2. **"Create Instance"** 클릭

3. **Name**: `hantrader` (원하는 이름)

4. **Image and shape** (운영체제와 사양):
   - **Image**: **"Edit"** 클릭 → **Ubuntu** 선택 → **Canonical Ubuntu 22.04** 선택
   - **Shape**: **"Change shape"** 클릭:
     - **Shape series**: **Ampere** (ARM 프로세서, 무료)
     - **Shape name**: `VM.Standard.A1.Flex`
     - **OCPUs**: `1` (무료 범위: 최대 4)
     - **Memory**: `6` GB (무료 범위: 최대 24)
     - **"Select shape"** 클릭

5. **Networking** (기본값 사용):
   - VCN: 자동 생성
   - Subnet: Public Subnet
   - **Public IPv4 address**: "Assign a public IPv4 address" **체크** (반드시!)

6. **Add SSH keys**:
   - **"Paste public keys"** 선택
   - 아까 만든 `~/.ssh/oracle_cloud.pub` 내용을 붙여넣기

7. **Boot volume**: 기본 50GB (충분)

8. **"Create"** 클릭!

9. 인스턴스 상태가 **RUNNING**으로 바뀔 때까지 대기 (1~3분)

10. **Public IP 주소 확인** → 메모해둔다 (예: `152.67.xxx.xxx`)

> **인스턴스 생성 실패 시**: Oracle 무료 티어는 리소스가 부족할 때 "Out of capacity" 에러가 뜬다.
> 시간대를 바꿔서 재시도하거나 (새벽 시간 추천), Shape을 `VM.Standard.E2.1.Micro` (AMD, x86)로 변경해본다.

---

## 4. AWS Lightsail 가입 및 서버 생성 (대안)

Oracle이 어렵거나 인스턴스 확보가 안 될 때 사용한다. 월 $5.

### 4-1. AWS 회원가입

1. `https://aws.amazon.com` 접속
2. **"AWS 계정 생성"** 클릭
3. 이메일, 비밀번호, 계정 이름 입력
4. 연락처 정보 입력 (영문)
5. 결제 카드 등록 (Visa/Mastercard)
6. 전화번호 인증 (SMS 또는 음성)
7. Support Plan: **Basic (무료)** 선택
8. 가입 완료

### 4-2. Lightsail 인스턴스 생성

1. AWS 로그인 → 상단 검색에서 **"Lightsail"** 검색 → 클릭
2. Lightsail 콘솔 → **"Create instance"**

3. **Instance location**: **Tokyo** (ap-northeast-1) 선택
   - 클릭 → "Change AWS Region and Availability Zone" → Tokyo

4. **Pick your instance image**:
   - Platform: **Linux/Unix**
   - Blueprint: **OS Only** → **Ubuntu 22.04 LTS**

5. **Choose your instance plan**:
   - **$5 USD/month** 선택 (1 GB RAM, 1 vCPU, 40 GB SSD)
   - 처음 3개월 무료 제공

6. **Name your instance**: `hantrader`

7. **"Create instance"** 클릭

8. 인스턴스 목록에서 상태가 **Running**으로 바뀌면 완료

9. 인스턴스 이름 클릭 → **Public IP** 확인 → 메모

### 4-3. SSH 키 다운로드

Lightsail은 자동으로 SSH 키를 생성해준다.

1. Lightsail 콘솔 → **Account** → **SSH keys**
2. **Default key** 옆 **Download** 클릭 → `.pem` 파일 저장
3. 파일을 `~/.ssh/lightsail.pem`으로 이동:

```bash
# Git Bash에서
mv ~/Downloads/LightsailDefaultKey-ap-northeast-1.pem ~/.ssh/lightsail.pem
chmod 600 ~/.ssh/lightsail.pem
```

---

## 5. 서버 접속 (SSH)

내 PC에서 클라우드 서버에 접속하는 방법이다. 터미널(Git Bash, PowerShell, Windows Terminal)에서 실행한다.

### Oracle Cloud 접속

```bash
ssh -i ~/.ssh/oracle_cloud ubuntu@{서버IP}

# 예시:
ssh -i ~/.ssh/oracle_cloud ubuntu@152.67.100.50
```

### AWS Lightsail 접속

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@{서버IP}

# 예시:
ssh -i ~/.ssh/lightsail.pem ubuntu@54.178.xxx.xxx
```

**처음 접속 시:**
```
Are you sure you want to continue connecting (yes/no)?
```
→ `yes` 입력

**접속 성공 화면:**
```
Welcome to Ubuntu 22.04.x LTS
ubuntu@hantrader:~$
```

> **접속 안 될 때**: Oracle Cloud는 보안 규칙에서 SSH(22번 포트)가 열려 있는지 확인.
> Lightsail은 기본으로 열려 있으니 `.pem` 파일 경로와 권한(chmod 600)을 확인한다.

### SSH 접속 단축키 설정 (편의)

매번 긴 명령어 치기 귀찮으니 설정 파일을 만든다:

```bash
# 내 PC에서 ~/.ssh/config 파일 생성/편집
notepad ~/.ssh/config
```

내용:
```
# Oracle Cloud
Host hantrader
    HostName 152.67.xxx.xxx
    User ubuntu
    IdentityFile ~/.ssh/oracle_cloud

# AWS Lightsail (대안)
# Host hantrader
#     HostName 54.178.xxx.xxx
#     User ubuntu
#     IdentityFile ~/.ssh/lightsail.pem
```

이후 간단하게 접속:
```bash
ssh hantrader
```

---

## 6. 서버 초기 설정

서버에 SSH 접속한 상태에서 진행한다. (프롬프트가 `ubuntu@hantrader:~$`인 상태)

### 6-1. 시스템 업데이트

```bash
sudo apt update && sudo apt upgrade -y
```

### 6-2. Python 3.11 설치

Ubuntu 22.04 기본 Python은 3.10이다. 3.11을 설치한다:

```bash
# Python 3.11 설치
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3.11-dev

# 기본 python3 명령을 3.11로 설정
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# 확인
python3 --version
# → Python 3.11.x
```

### 6-3. pip 설치

```bash
curl -sS https://bootstrap.pypa.io/get-pip.py | python3
```

### 6-4. Git 설치 (보통 이미 설치되어 있음)

```bash
sudo apt install -y git
```

### 6-5. 시간대 설정 (KST)

```bash
sudo timedatectl set-timezone Asia/Seoul

# 확인
date
# → 한국 시간 표시됨
```

---

## 7. HanTrader 설치

### 7-1. 코드 가져오기

**방법 A: Git으로 클론 (추천 — 이후 업데이트가 쉬움)**

GitHub/GitLab 등에 올려두었다면:
```bash
cd ~
git clone https://github.com/{본인계정}/hantrader.git
cd hantrader
```

**방법 B: 로컬에서 직접 복사 (Git 없을 때)**

내 PC(Git Bash)에서 서버로 파일 전송:
```bash
# 내 PC에서 실행 (Git Bash)
scp -i ~/.ssh/oracle_cloud -r /c/han/claude_code/hantrader ubuntu@{서버IP}:~/hantrader
```

> **주의**: `.env` 파일은 아직 없어야 정상이다. 서버에서 직접 만든다 (8단계).
> `data/` 디렉토리는 서버에서 새로 생성되므로 굳이 복사하지 않아도 된다.

### 7-2. 가상환경 생성 및 패키지 설치

```bash
cd ~/hantrader

# 가상환경 생성
python3 -m venv venv

# 가상환경 활성화
source venv/bin/activate

# 프롬프트가 (venv) ubuntu@hantrader:~/hantrader$ 로 변경됨

# 패키지 설치
pip install --upgrade pip
pip install -r requirements.txt
```

> **설치 에러 시**: Oracle ARM 인스턴스에서 numpy/pandas 빌드 에러가 나면:
> ```bash
> sudo apt install -y gcc g++ gfortran libopenblas-dev
> pip install numpy pandas --no-cache-dir
> ```

### 7-3. 설치 확인

```bash
python -m src.main list-exchanges
# → 거래소 목록이 출력되면 정상
```

---

## 8. 환경변수 설정 (.env)

Binance API 키를 서버에 설정한다.

### 8-1. Binance API 키 발급 (아직 없다면)

1. Binance 로그인 → **API Management** (계정 → API 관리)
2. **"API 생성"** → 라벨 입력 (예: `hantrader-cloud`)
3. 보안 인증 (이메일 + 2FA)
4. **API Key**와 **Secret Key** 복사 → 메모장에 임시 저장
5. **API 제한 설정**:
   - ✅ Enable Reading
   - ✅ Enable Futures (선물 거래)
   - ❌ Enable Withdrawals (출금은 꺼둘 것!)
6. **IP 접근 제한** (중요!):
   - "Restrict access to trusted IPs only" 선택
   - 클라우드 서버의 Public IP 입력 (3단계에서 메모한 IP)

### 8-2. .env 파일 생성

서버에서:
```bash
cd ~/hantrader

# .env.example을 복사
cp .env.example .env

# 편집
nano .env
```

내용 수정:
```
BINANCE_API_KEY=여기에_API_KEY_붙여넣기
BINANCE_API_SECRET=여기에_SECRET_KEY_붙여넣기
BINANCE_TESTNET=false
```

**nano 편집기 사용법:**
- 화살표 키로 이동
- 기존 텍스트 지우고 새로 입력
- `Ctrl + O` → Enter → 저장
- `Ctrl + X` → 나가기

### 8-3. 파일 보안

```bash
chmod 600 .env
# 본인만 읽기/쓰기 가능, 다른 사용자 접근 차단
```

---

## 9. 수동 실행 테스트

systemd 서비스 등록 전에, 수동으로 실행해서 정상 작동하는지 확인한다.

### 9-1. 가상환경 활성화

```bash
cd ~/hantrader
source venv/bin/activate
```

### 9-2. 데이터 수집 테스트

```bash
python -m src.main collect -e binance_futures --symbols BTC/USDT
# 데이터가 수집되면 정상
# Ctrl+C로 중단
```

### 9-3. 시뮬레이터 테스트 (안전)

실거래 전에 시뮬레이터로 먼저 확인:
```bash
python -m src.main simulate -e binance_futures -s btc -t 1h
# 실시간 데이터로 가상 매매가 진행되면 정상
# Ctrl+C로 중단
```

### 9-4. 실거래 테스트 (주의!)

```bash
python -m src.main trade -e binance_futures -s btc -t 1h
# 실제 주문이 나간다! 소액으로 테스트할 것
# Ctrl+C로 중단
```

> **중요**: 수동 실행은 SSH 연결이 끊기면 프로그램도 종료된다.
> 24시간 실행하려면 다음 단계(systemd)를 진행해야 한다.

---

## 10. 24시간 자동 실행 (systemd)

Linux의 서비스 관리 도구인 systemd를 이용하면:
- 서버 부팅 시 자동 시작
- 프로그램 비정상 종료 시 자동 재시작
- SSH 접속 끊어져도 계속 실행

### 10-1. 서비스 파일 생성

```bash
sudo nano /etc/systemd/system/hantrader.service
```

내용:
```ini
[Unit]
Description=HanTrader Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/hantrader
ExecStart=/home/ubuntu/hantrader/venv/bin/python -m src.main trade -e binance_futures -s btc -t 1h
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

> **다중 코인 실행**: 코인별로 별도 서비스를 만든다 (아래 참고).

저장: `Ctrl+O` → Enter → `Ctrl+X`

### 10-2. 서비스 등록 및 시작

```bash
# systemd에 서비스 등록
sudo systemctl daemon-reload

# 부팅 시 자동 시작 등록
sudo systemctl enable hantrader

# 서비스 시작
sudo systemctl start hantrader

# 상태 확인
sudo systemctl status hantrader
```

정상이면 이런 출력이 나온다:
```
● hantrader.service - HanTrader Bot
     Loaded: loaded (/etc/systemd/system/hantrader.service; enabled)
     Active: active (running) since ...
```

### 10-3. 주요 명령어

```bash
# 상태 확인
sudo systemctl status hantrader

# 로그 실시간 보기
journalctl -u hantrader -f

# 최근 100줄 로그
journalctl -u hantrader -n 100

# 서비스 중지
sudo systemctl stop hantrader

# 서비스 재시작
sudo systemctl restart hantrader
```

### 10-4. 다중 코인 실행

코인별로 서비스 파일을 만든다:

```bash
# BTC 서비스
sudo cp /etc/systemd/system/hantrader.service /etc/systemd/system/hantrader-btc.service
sudo nano /etc/systemd/system/hantrader-btc.service
# ExecStart 줄에서 -s btc 확인

# ETH 서비스
sudo cp /etc/systemd/system/hantrader.service /etc/systemd/system/hantrader-eth.service
sudo nano /etc/systemd/system/hantrader-eth.service
# ExecStart 줄에서 -s btc → -s eth 로 변경
# Description도 HanTrader Bot (ETH) 등으로 변경
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable hantrader-btc hantrader-eth
sudo systemctl start hantrader-btc hantrader-eth
```

---

## 11. 서버 보안 설정

### 11-1. SSH 비밀번호 로그인 비활성화

SSH 키로만 접속하고, 비밀번호 로그인은 막는다:

```bash
sudo nano /etc/ssh/sshd_config
```

다음 항목을 찾아서 변경:
```
PasswordAuthentication no
```

적용:
```bash
sudo systemctl restart sshd
```

### 11-2. 방화벽 설정

```bash
# SSH(22번)만 허용, 나머지 차단
sudo ufw allow 22/tcp
sudo ufw enable
sudo ufw status
```

> Oracle Cloud는 콘솔에서도 Security List → Ingress Rules에서 포트를 관리한다.
> 22번 포트는 기본으로 열려 있다.

### 11-3. Binance API 키 IP 제한

Binance API Management에서 서버 IP만 허용해두면, API 키가 유출되어도 다른 곳에서 사용 불가.

---

## 12. 배포 (코드 업데이트)

로컬에서 코드를 수정한 뒤 서버에 반영하는 방법.

### 방법 A: Git 사용 (추천)

**로컬 PC에서:**
```bash
git add .
git commit -m "전략 파라미터 수정"
git push origin main
```

**서버에서 (SSH 접속 후):**
```bash
cd ~/hantrader
git pull
sudo systemctl restart hantrader
```

### 방법 B: scp로 파일 직접 복사

**로컬 PC (Git Bash)에서:**
```bash
# 특정 파일만 복사
scp -i ~/.ssh/oracle_cloud src/strategy/bb_strategy.py ubuntu@{서버IP}:~/hantrader/src/strategy/

# 서버에서 재시작
ssh hantrader "sudo systemctl restart hantrader"
```

### 배포 스크립트 (자동화)

서버에 `deploy.sh`를 만들어두면 한 줄로 배포할 수 있다:

```bash
# 서버의 ~/deploy.sh
#!/bin/bash
cd ~/hantrader
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart hantrader
echo "배포 완료: $(date)"
```

```bash
chmod +x ~/deploy.sh
```

로컬에서 원격 실행:
```bash
ssh hantrader "bash ~/deploy.sh"
```

---

## 13. 모니터링 및 알림

### 13-1. 로그 확인

서버에 SSH 접속해서:

```bash
# systemd 로그 (콘솔 출력)
journalctl -u hantrader -f

# 카테고리별 로그 파일 직접 확인
tail -f ~/hantrader/data/logs/binance_futures/BTC_USDT/$(date +%Y-%m-%d)/trade/trade.log
tail -f ~/hantrader/data/logs/binance_futures/BTC_USDT/$(date +%Y-%m-%d)/trade/all.log
```

### 13-2. Telegram 알림 (추천)

프로그램에 Telegram 알림을 추가하면 핸드폰으로 매매 알림을 받을 수 있다.
(현재 미구현 — 추후 기능 추가 예정)

### 13-3. 서비스 상태 스크립트

간단한 상태 확인 스크립트:

```bash
# ~/check_status.sh
#!/bin/bash
echo "=== HanTrader 상태 ==="
echo "서비스: $(systemctl is-active hantrader)"
echo "메모리: $(free -h | grep Mem | awk '{print $3 "/" $2}')"
echo "디스크: $(df -h / | tail -1 | awk '{print $3 "/" $2 " (" $5 ")"}')"
echo "업타임: $(uptime -p)"
echo ""
echo "=== 최근 로그 (5줄) ==="
journalctl -u hantrader -n 5 --no-pager
```

```bash
chmod +x ~/check_status.sh
bash ~/check_status.sh
```

---

## 14. 백업

### 14-1. 수동 백업 (내 PC로 다운로드)

```bash
# 내 PC (Git Bash)에서 실행
scp -i ~/.ssh/oracle_cloud -r ubuntu@{서버IP}:~/hantrader/data ~/hantrader_backup_$(date +%Y%m%d)
```

### 14-2. 자동 백업 (cron)

매일 자정에 DB와 상태 파일을 백업:

```bash
# 서버에서 crontab 편집
crontab -e
```

맨 아래에 추가:
```
0 0 * * * cp -r ~/hantrader/data/db ~/hantrader/data/db_backup_$(date +\%Y\%m\%d)
0 0 * * * cp -r ~/hantrader/data/trader/state ~/hantrader/data/state_backup_$(date +\%Y\%m\%d)
```

### 14-3. 오래된 백업 자동 삭제

7일 이상 된 백업은 삭제:
```
0 1 * * * find ~/hantrader/data/ -name "*_backup_*" -mtime +7 -exec rm -rf {} + 2>/dev/null
```

---

## 15. 비용 정리

### Oracle Cloud (무료 티어)

| 항목 | 비용 |
|------|------|
| 서버 (VM.Standard.A1.Flex) | 무료 |
| 디스크 (50GB) | 무료 |
| 네트워크 (10TB/월) | 무료 |
| **월 총액** | **$0** |

### AWS Lightsail

| 항목 | 비용 |
|------|------|
| 인스턴스 ($5 플랜) | $5/월 |
| 첫 3개월 | 무료 |
| **월 총액** | **$5 (약 7,000원)** |

---

## 16. 트러블슈팅

### SSH 접속이 안 된다

```bash
# 1. 서버 IP가 맞는지 확인 (클라우드 콘솔에서 확인)
# 2. SSH 키 파일 권한 확인
chmod 600 ~/.ssh/oracle_cloud
chmod 600 ~/.ssh/lightsail.pem

# 3. 상세 로그로 접속 시도
ssh -vvv -i ~/.ssh/oracle_cloud ubuntu@{서버IP}

# 4. Oracle Cloud: Security List에서 22번 포트 Ingress Rule 확인
# 5. AWS: Lightsail 콘솔 → Networking → Firewall에서 SSH 허용 확인
```

### 서비스가 계속 재시작된다

```bash
# 에러 로그 확인
journalctl -u hantrader -n 50 --no-pager

# 일반적인 원인:
# 1. .env 파일 없음 또는 API 키 오류
# 2. 패키지 미설치 (venv 활성화 확인)
# 3. config.yaml 문법 에러
```

### pip install이 실패한다 (ARM 서버)

```bash
# 빌드 도구 설치
sudo apt install -y gcc g++ gfortran libopenblas-dev cmake

# 개별 설치
pip install numpy --no-cache-dir
pip install pandas --no-cache-dir
pip install ta --no-cache-dir
```

### 디스크가 꽉 찼다

```bash
# 디스크 사용량 확인
df -h /

# 큰 파일 찾기
du -sh ~/hantrader/data/*

# 오래된 로그 정리
find ~/hantrader/data/logs -name "*.log" -mtime +30 -delete

# 오래된 백테스트 리포트 정리
find ~/hantrader/data/backtest -mtime +90 -delete
```

### 서버 시간이 맞지 않다

```bash
# 시간대 확인
timedatectl

# KST로 설정
sudo timedatectl set-timezone Asia/Seoul

# NTP 동기화 활성화
sudo timedatectl set-ntp true
```

---

## 빠른 시작 요약 (체크리스트)

1. [ ] Oracle Cloud 가입 + 결제 카드 등록
2. [ ] SSH 키 생성 (`ssh-keygen`)
3. [ ] 인스턴스 생성 (Ubuntu 22.04, ARM, 1 OCPU/6GB)
4. [ ] SSH 접속 확인
5. [ ] 시스템 업데이트 + Python 3.11 설치
6. [ ] HanTrader 코드 복사 (git clone 또는 scp)
7. [ ] 가상환경 생성 + 패키지 설치
8. [ ] `.env` 파일 생성 (API 키)
9. [ ] 수동 실행 테스트 (simulate 먼저)
10. [ ] systemd 서비스 등록 + 시작
11. [ ] 보안 설정 (SSH 키 전용, 방화벽, API IP 제한)
12. [ ] 백업 cron 등록
