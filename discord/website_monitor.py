#!/usr/bin/env python3
"""
Website Change Monitor — Discord 봇 버전
새 게시물 / 항목 / 하이퍼링크(파일 포함) 추가를 감지하여 Discord 봇으로 알림
"""

import hashlib
import json
import subprocess
import sys
import asyncio
from datetime import datetime
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

try:
    import discord
    from discord.ext import tasks
except ImportError:
    print("discord.py 설치 중...")
    subprocess.run([sys.executable, "-m", "pip", "install", "discord.py"], check=True)
    import discord
    from discord.ext import tasks


# ── 경로 ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path.home() / ".website_monitor_config.json"
STATE_FILE  = Path.home() / ".website_monitor_state.json"

DEFAULT_CONFIG = {
    "interval_seconds": 300,
    "discord": {
        "bot_token": "",
        "channel_id": 0
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

    raw_texts = []
    for el in soup.select("li, td, th, h2, h3, h4, .title, .subject, .board-title, .post-title"):
        t = el.get_text(strip=True)
        if 5 < len(t) < 200:
            raw_texts.append(t)
    texts = list(dict.fromkeys(raw_texts))

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
        return None

    return {"new_links": new_links, "new_texts": new_texts}


# ── Discord Embed 생성 ───────────────────────────────────────────────────────

def build_embed(site_name: str, url: str, changes: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔔 변경 감지: {site_name}",
        url=url,
        description=f"[{url}]({url})",
        color=0x1a73e8,
        timestamp=datetime.now()
    )

    new_links = changes.get("new_links", [])
    new_texts = changes.get("new_texts", [])

    if new_links:
        link_lines = []
        for link in new_links[:10]:
            href  = link.get("href", "")
            text  = link.get("text", "") or href
            label = "📎" if link.get("is_file") else "🔗"
            link_lines.append(f"{label} [{text[:60]}]({href})")
        if len(new_links) > 10:
            link_lines.append(f"... 외 {len(new_links) - 10}개")
        embed.add_field(
            name=f"새 링크 / 파일 ({len(new_links)}개)",
            value="\n".join(link_lines),
            inline=False
        )

    if new_texts:
        text_lines = [f"• {t[:80]}" for t in new_texts[:10]]
        if len(new_texts) > 10:
            text_lines.append(f"... 외 {len(new_texts) - 10}개")
        embed.add_field(
            name=f"새 텍스트 항목 ({len(new_texts)}개)",
            value="\n".join(text_lines),
            inline=False
        )

    embed.set_footer(text="Website Monitor")
    return embed


# ── Discord 봇 ───────────────────────────────────────────────────────────────

class MonitorBot(discord.Client):
    def __init__(self, config: dict, state: dict):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.config = config
        self.state  = state
        self.channel_id = int(config["discord"]["channel_id"])

    async def on_ready(self):
        print(f"[{ts()}] 봇 로그인: {self.user}  (id: {self.user.id})")
        print(f"[{ts()}] 모니터 시작 | {len(self.config['sites'])}개 사이트 "
              f"| {self.config['interval_seconds']}초 간격\n")
        self.monitor_loop.change_interval(seconds=self.config["interval_seconds"])
        self.monitor_loop.start()

    @tasks.loop(seconds=300)   # on_ready에서 실제 간격으로 교체됨
    async def monitor_loop(self):
        channel = self.get_channel(self.channel_id)
        if channel is None:
            print(f"  [오류] 채널 ID {self.channel_id}를 찾을 수 없습니다.")
            return

        for site in self.config["sites"]:
            url  = site["url"]
            name = site.get("name", url)
            print(f"[{ts()}] 확인: {name}")

            html = await asyncio.get_event_loop().run_in_executor(None, fetch_html, url)
            if html is None:
                print()
                continue

            new_st = extract_state(html, url)
            old_st = self.state.get(url)

            if old_st is None:
                print(f"  → 초기 저장 완료 "
                      f"(링크 {len(new_st['links'])}개 / 텍스트 {len(new_st['texts'])}개)\n")
                self.state[url] = new_st
                save_json(STATE_FILE, self.state)
                continue

            changes = detect_changes(old_st, new_st)
            if changes:
                nl, nt = len(changes["new_links"]), len(changes["new_texts"])
                print(f"  → 변경 감지! 새 링크 {nl}개 / 새 텍스트 {nt}개")
                embed = build_embed(name, url, changes)
                await channel.send(embed=embed)
                self.state[url] = new_st
                save_json(STATE_FILE, self.state)
            else:
                print(f"  → 변화 없음\n")

        print(f"[{ts()}] 다음 체크까지 {self.config['interval_seconds']}초 대기...\n")


# ── 모니터 실행 ──────────────────────────────────────────────────────────────

def run_monitor():
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    state  = load_json(STATE_FILE, {})

    token      = config.get("discord", {}).get("bot_token", "")
    channel_id = config.get("discord", {}).get("channel_id", 0)

    if not token:
        print("봇 토큰이 설정되지 않았습니다.")
        print(f"  python {Path(__file__).name} bot-setup\n")
        return
    if not channel_id:
        print("채널 ID가 설정되지 않았습니다.")
        print(f"  python {Path(__file__).name} bot-setup\n")
        return
    if not config["sites"]:
        print("등록된 사이트가 없습니다.")
        print(f"  python {Path(__file__).name} add <URL> <이름>\n")
        return

    bot = MonitorBot(config, state)
    bot.run(token)


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_bot_setup():
    config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
    if "discord" not in config:
        config["discord"] = {"bot_token": "", "channel_id": 0}

    print("\n" + "=" * 60)
    print("  Discord 봇 설정")
    print("  1. https://discord.com/developers/applications 에서 봇 생성")
    print("  2. Bot 탭 → Token 복사")
    print("  3. 알림 보낼 채널에서 채널 ID 복사 (개발자 모드 필요)")
    print("=" * 60)

    config["discord"]["bot_token"]  = input("봇 Token: ").strip()
    config["discord"]["channel_id"] = int(input("채널 ID: ").strip())
    save_json(CONFIG_FILE, config)
    print("\n설정 저장 완료.")

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
    dc     = config.get("discord", {})
    token  = dc.get("bot_token", "")
    masked = (token[:20] + "...") if len(token) > 20 else (token or "(미설정)")
    ch_id  = dc.get("channel_id", 0) or "(미설정)"
    print(f"\n[Discord 봇 설정]")
    print(f"  토큰:      {masked}")
    print(f"  채널 ID:   {ch_id}")
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
Website Monitor (Discord 봇) — 명령어 목록
────────────────────────────────────────────────────
python website_monitor.py                     봇 시작 (모니터링)
python website_monitor.py bot-setup           봇 토큰 / 채널 ID 설정
python website_monitor.py add <URL> <이름>    사이트 추가
python website_monitor.py remove <URL|이름>   사이트 제거
python website_monitor.py list                목록 및 설정 확인
python website_monitor.py interval <초>       체크 간격 설정
python website_monitor.py reset               저장 상태 초기화
python website_monitor.py help                도움말
"""

def main():
    args = sys.argv[1:]
    cmd  = args[0] if args else "run"
    match cmd:
        case "bot-setup":  cmd_bot_setup()
        case "add":        cmd_add(args[1:])
        case "remove":     cmd_remove(args[1:])
        case "list":       cmd_list()
        case "interval":   cmd_interval(args[1:])
        case "reset":      cmd_reset()
        case "help":       print(HELP)
        case _:            run_monitor()

if __name__ == "__main__":
    main()
