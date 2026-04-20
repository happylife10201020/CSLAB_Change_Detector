# Website Monitor

웹사이트 변경 사항(새 게시물, 링크, 파일 등)을 감지하여 **이메일** 또는 **Discord**로 알림을 보내는 Python 모니터링 도구입니다.

## 구조

```
website_monitor/
├── website_monitor.py        # 이메일 알림 버전 (Gmail SMTP)
└── discord/
    └── website_monitor.py    # Discord 봇 알림 버전
```

## 동작 방식

1. 설정된 URL을 주기적으로 크롤링
2. 이전 상태와 비교하여 새 링크, 파일, 텍스트 항목 감지
3. 변경이 있으면 이메일 또는 Discord로 알림 발송
4. 현재 상태를 `~/.website_monitor_state.json`에 저장

광고 등 내용 없는 해시 변화는 무시하고, 실제 새 항목이 추가된 경우에만 알림을 발송합니다.

## 설치

```bash
pip install requests beautifulsoup4
# Discord 버전 추가 설치
pip install discord.py
```

Python 3.10 이상 필요 (match 문 사용)

---

## 이메일 버전 (`website_monitor.py`)

### 초기 설정

```bash
# Gmail SMTP 설정 (앱 비밀번호 필요)
python website_monitor.py email-setup

# 모니터링할 사이트 추가
python website_monitor.py add https://example.com 예시사이트

# 모니터 시작
python website_monitor.py
```

> Gmail 앱 비밀번호: https://myaccount.google.com/apppasswords

### 명령어

| 명령어 | 설명 |
|--------|------|
| `python website_monitor.py` | 모니터 시작 |
| `email-setup` | Gmail SMTP 설정 |
| `add <URL> <이름>` | 사이트 추가 |
| `remove <URL\|이름>` | 사이트 제거 |
| `list` | 등록 사이트 및 설정 확인 |
| `interval <초>` | 체크 간격 설정 (기본: 300초) |
| `reset` | 저장 상태 초기화 |
| `help` | 도움말 |

---

## Discord 봇 버전 (`discord/website_monitor.py`)

### 초기 설정

```bash
cd discord

# Discord 봇 토큰 및 채널 ID 설정
python website_monitor.py bot-setup

# 모니터링할 사이트 추가
python website_monitor.py add https://example.com 예시사이트

# 봇 시작
python website_monitor.py
```

> Discord 개발자 포털: https://discord.com/developers/applications  
> 봇 생성 → Bot 탭 → Token 복사 → 알림 채널에서 채널 ID 복사 (개발자 모드 필요)

### 명령어

| 명령어 | 설명 |
|--------|------|
| `python website_monitor.py` | 봇 시작 |
| `bot-setup` | 봇 토큰 / 채널 ID 설정 |
| `add <URL> <이름>` | 사이트 추가 |
| `remove <URL\|이름>` | 사이트 제거 |
| `list` | 등록 사이트 및 설정 확인 |
| `interval <초>` | 체크 간격 설정 (기본: 300초) |
| `reset` | 저장 상태 초기화 |
| `help` | 도움말 |

---

## 설정 파일

설정은 홈 디렉터리에 JSON 파일로 저장됩니다.

| 파일 | 내용 |
|------|------|
| `~/.website_monitor_config.json` | 이메일/Discord 설정, 사이트 목록, 체크 간격 |
| `~/.website_monitor_state.json` | 마지막으로 감지한 페이지 상태 |

## 감지 대상

- 새로 추가된 하이퍼링크
- 새로 추가된 첨부 파일 (PDF, HWP, DOCX, XLSX, ZIP 등)
- 새로 추가된 텍스트 항목 (게시판 제목, 리스트, 테이블 셀 등)
