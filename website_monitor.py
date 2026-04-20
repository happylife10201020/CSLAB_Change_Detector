#!/usr/bin/env python3
"""
Website Change Monitor — 이메일 알림 버전
새 게시물 / 항목 / 하이퍼링크(파일 포함) 추가를 감지하여 이메일로 알림
"""

import hashlib
import json
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("패키지 설치 중...")
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4"], check=True)
    import requests
    from bs4 import BeautifulSoup


# ── 경로 ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path.home() / ".website_monitor_config.json"
STATE_FILE  = Path.home() / ".website_monitor_state.json"

DEFAULT_CONFIG = {
    "interval_seconds": 300,
    "email": {
        "smtp_host":    "smtp.gmail.com",
        "smtp_port":    587,
        "sender":       "",
        "app_password": "",
        "recipients":   []
    },
    "sites": []
}


# ── 유틸 ────────────────────────────────────────────────────────────────────

def load_json(path: Path, default: dict) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(json.dumps(default))

def save_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── 이메일 ───────────────────────────────────────────────────────────────────

def send_email(cfg: dict, subject: str, body_html: str):
    ec = cfg["email"]
    if not ec["sender"] or not ec["app_password"] or not ec["recipients"]:
        print("  [이메일] 설정 미완료 → email-setup 명령어로 설정하세요.\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = ec["sender"]
    msg["To"]      = ", ".join(ec["recipients"])
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(ec["smtp_host"], ec["smtp_port"]) as s:
            s.ehlo()
            s.starttls()
            s.login(ec["sender"], ec["app_password"])
            s.sendmail(ec["sender"], ec["recipients"], msg.as_string())
        print(f"  [이메일] 발송 완료 → {', '.join(ec['recipients'])}")
    except Exception as e:
        print(f"  [이메일] 발송 실패: {e}")


def build_email_html(site_name: str, url: str, changes: dict) -> str:
    rows_links = ""
    for link in changes.get("new_links", []):
        href  = link.get("href", "")
        text  = link.get("text", href) or href
        label = "📎 파일" if link.get("is_file") else "🔗 링크"
        rows_links += (
            f'<tr><td style="padding:6px 12px;color:#5f6368;">{label}</td>'
            f'<td style="padding:6px 12px;"><a href="{href}" style="color:#1a73e8;">{text}</a></td></tr>'
        )

    list_texts = "".join(
        f'<li style="margin:4px 0;">{t}</li>'
        for t in changes.get("new_texts", [])
    )

    sec_links = (
        f'<h3 style="color:#1a73e8;margin-top:24px;">새 링크 / 파일 ({len(changes["new_links"])}개)</h3>'
        f'<table style="border-collapse:collapse;width:100%;font-size:14px;">'
        f'<thead><tr style="background:#f1f3f4;">'
        f'<th style="padding:6px 12px;text-align:left;">유형</th>'
        f'<th style="padding:6px 12px;text-align:left;">주소</th>'
        f'</tr></thead><tbody>{rows_links}</tbody></table>'
        if rows_links else ""
    )
    sec_texts = (
        f'<h3 style="color:#1a73e8;margin-top:24px;">새 텍스트 항목 ({len(changes["new_texts"])}개)</h3>'
        f'<ul style="font-size:14px;line-height:1.7;">{list_texts}</ul>'
        if list_texts else ""
    )

    return f"""<html><body style="font-family:sans-serif;color:#202124;max-width:700px;margin:auto;padding:24px;">
  <div style="border-left:4px solid #1a73e8;padding-left:16px;margin-bottom:20px;">
    <h2 style="margin:0 0 4px;">🔔 변경 감지: {site_name}</h2>
    <p style="margin:0;font-size:13px;color:#5f6368;">{ts()}</p>
  </div>
  <p><a href="{url}" style="color:#1a73e8;">{url}</a></p>
  {sec_links}{sec_texts}
  <hr style="border:none;border-top:1px solid #e0e0e0;margin-top:32px;">
  <p style="font-size:12px;color:#9aa0a6;">Website Monitor</p>
</body></html>"""


# ── 페이지 파싱 ──────────────────────────────────────────────────────────────

FILE_EXTS = {
    ".pdf", ".hwp", ".hwpx", ".docx", ".doc", ".xlsx", ".xls",
    ".pptx", ".ppt", ".zip", ".rar", ".7z", ".tar", ".gz",
    ".txt", ".csv", ".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mp3"
}

def is_file_link(href: str) -> bool:
    return any(urlparse(href).path.lower().endswith(ext) for ext in FILE_EXTS)

def extract_state(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "meta", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    # 링크 수집
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        href = urljoin(base_url, href)
        if href in seen:
            continue
        seen.add(href)
        links.append({
            "href":    href,
            "text":    a.get_text(strip=True)[:100],
            "is_file": is_file_link(href)
        })

    # 텍스트 항목 수집 (게시판 제목, 리스트, 테이블 셀 등)
    raw_texts = []
    for el in soup.select("li, td, th, h2, h3, h4, .title, .subject, .board-title, .post-title"):
        t = el.get_text(strip=True)
        if 5 < len(t) < 200:
            raw_texts.append(t)
    texts = list(dict.fromkeys(raw_texts))   # 중복 제거, 순서 유지

    return {
        "link_hrefs": [l["href"] for l in links],
        "links":      links,
        "texts":      texts,
        "page_hash":  short_hash(soup.get_text(separator=" ", strip=True))
    }

def fetch_html(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        r.encoding = r.apparent_encoding
        return r.text
    except requests.RequestException as e:
        print(f"  [오류] {e}")
        return None


# ── 변경 비교 ────────────────────────────────────────────────────────────────

def detect_changes(old: dict, new: dict) -> dict | None:
    if old["page_hash"] == new["page_hash"]:
        return None

    old_hrefs = set(old["link_hrefs"])
    new_links  = [l for l in new["links"]  if l["href"] not in old_hrefs]

    old_texts = set(old["texts"])
    new_texts  = [t for t in new["texts"]  if t not in old_texts]

    if not new_links and not new_texts:
        return None   # 해시 변화만 있고 추적 가능한 변경 없음 (광고 등)

    return {"new_links": new_links, "new_texts": new_texts}


# ── 모니터 루프 ──────────────────────────────────────────────────────────────

def run_monitor():
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    state  = load_json(STATE_FILE, {})

    if not config["sites"]:
        print("등록된 사이트가 없습니다.\n")
        print(f"  사이트 추가:  python {Path(__file__).name} add <URL> <이름>")
        print(f"  이메일 설정:  python {Path(__file__).name} email-setup\n")
        return

    interval = config["interval_seconds"]
    print(f"[{ts()}] 모니터 시작 | {len(config['sites'])}개 사이트 | {interval}초 간격\n")

    while True:
        for site in config["sites"]:
            url  = site["url"]
            name = site.get("name", url)
            print(f"[{ts()}] 확인: {name}")

            html = fetch_html(url)
            if html is None:
                print()
                continue

            new_st = extract_state(html, url)
            old_st = state.get(url)

            if old_st is None:
                print(f"  → 초기 저장 완료 "
                      f"(링크 {len(new_st['links'])}개 / 텍스트 {len(new_st['texts'])}개)\n")
                state[url] = new_st
                save_json(STATE_FILE, state)
                continue

            changes = detect_changes(old_st, new_st)
            if changes:
                nl, nt = len(changes["new_links"]), len(changes["new_texts"])
                print(f"  → ✅ 변경 감지! 새 링크 {nl}개 / 새 텍스트 {nt}개")
                send_email(config, f"[변경 감지] {name}", build_email_html(name, url, changes))
                state[url] = new_st
                save_json(STATE_FILE, state)
            else:
                print(f"  → 변화 없음\n")

        print(f"[{ts()}] {interval}초 대기...\n")
        time.sleep(interval)


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_email_setup():
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    print("\n" + "=" * 52)
    print("  Gmail SMTP 설정")
    print("  앱 비밀번호: https://myaccount.google.com/apppasswords")
    print("=" * 52)
    config["email"]["sender"]       = input("발신 Gmail 주소: ").strip()
    pw = input("앱 비밀번호 (16자리, 띄어쓰기 무관): ").strip().replace(" ", "")
    config["email"]["app_password"] = pw
    r  = input("수신자 이메일 (여러 개면 쉼표 구분): ").strip()
    config["email"]["recipients"]   = [x.strip() for x in r.split(",") if x.strip()]
    save_json(CONFIG_FILE, config)
    print("\n설정 저장 완료.")
    if input("테스트 메일 발송? (y/n): ").strip().lower() == "y":
        send_email(config, "[테스트] Website Monitor", "<p>이메일 설정 완료 ✅</p>")

def cmd_add(args):
    if len(args) < 2:
        print("사용법: add <URL> <이름>")
        return
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    config["sites"].append({"url": args[0], "name": args[1]})
    save_json(CONFIG_FILE, config)
    print(f"추가됨: {args[1]}  ({args[0]})")

def cmd_remove(args):
    if not args:
        print("사용법: remove <URL 또는 이름>")
        return
    key    = args[0]
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    before = len(config["sites"])
    config["sites"] = [s for s in config["sites"]
                       if s["url"] != key and s.get("name") != key]
    save_json(CONFIG_FILE, config)
    print(f"{before - len(config['sites'])}개 제거됨")

def cmd_list():
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    ec = config.get("email", {})
    print(f"\n[이메일 설정]")
    print(f"  발신: {ec.get('sender') or '(미설정)'}")
    print(f"  수신: {', '.join(ec.get('recipients', [])) or '(미설정)'}")
    print(f"\n[모니터링 사이트]  체크 간격: {config['interval_seconds']}초")
    for i, s in enumerate(config["sites"], 1):
        print(f"  {i}. {s['name']}  {s['url']}")
    if not config["sites"]:
        print("  없음")
    print()

def cmd_interval(args):
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    if not args:
        print(f"현재 간격: {config['interval_seconds']}초")
        return
    config["interval_seconds"] = int(args[0])
    save_json(CONFIG_FILE, config)
    print(f"체크 간격 → {args[0]}초")

def cmd_reset():
    STATE_FILE.unlink(missing_ok=True)
    print("상태 초기화 완료 (다음 실행 시 현재 상태를 기준점으로 재저장)")

HELP = """
Website Monitor — 명령어 목록
────────────────────────────────────────────────────
python website_monitor.py                   모니터 시작
python website_monitor.py email-setup       Gmail SMTP 설정
python website_monitor.py add <URL> <이름>  사이트 추가
python website_monitor.py remove <URL|이름> 사이트 제거
python website_monitor.py list              목록 및 설정 확인
python website_monitor.py interval <초>     체크 간격 설정
python website_monitor.py reset             저장 상태 초기화
python website_monitor.py help              도움말
"""

def main():
    args = sys.argv[1:]
    cmd  = args[0] if args else "run"
    match cmd:
        case "email-setup": cmd_email_setup()
        case "add":         cmd_add(args[1:])
        case "remove":      cmd_remove(args[1:])
        case "list":        cmd_list()
        case "interval":    cmd_interval(args[1:])
        case "reset":       cmd_reset()
        case "help":        print(HELP)
        case _:             run_monitor()

if __name__ == "__main__":
    main()
