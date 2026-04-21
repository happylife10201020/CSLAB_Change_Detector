#!/usr/bin/env python3
"""
Website Change Monitor — GitHub Actions 버전
새 게시물 / 항목 / 하이퍼링크(파일 포함) 추가를 감지하여 Discord로 알림
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ── 경로 ────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
STATE_FILE  = SCRIPT_DIR / "state.json"


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


# ── Discord REST API ─────────────────────────────────────────────────────────

def build_embed(site_name: str, url: str, changes: dict) -> dict:
    fields = []

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
        fields.append({
            "name":   f"새 링크 / 파일 ({len(new_links)}개)",
            "value":  "\n".join(link_lines),
            "inline": False
        })

    if new_texts:
        text_lines = [f"• {t[:80]}" for t in new_texts[:10]]
        if len(new_texts) > 10:
            text_lines.append(f"... 외 {len(new_texts) - 10}개")
        fields.append({
            "name":   f"새 텍스트 항목 ({len(new_texts)}개)",
            "value":  "\n".join(text_lines),
            "inline": False
        })

    return {
        "title":       f"🔔 변경 감지: {site_name}",
        "url":         url,
        "description": f"[{url}]({url})",
        "color":       0x1a73e8,
        "fields":      fields,
        "footer":      {"text": "Website Monitor"},
        "timestamp":   datetime.now(timezone.utc).isoformat()
    }

def send_discord_message(token: str, channel_id: str, embed: dict):
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type":  "application/json"
    }
    resp = requests.post(url, headers=headers, json={"embeds": [embed]})
    if not resp.ok:
        print(f"  [Discord 오류] {resp.status_code}: {resp.text}")
    return resp.ok


# ── 메인 ────────────────────────────────────────────────────────────────────

def main():
    token      = os.environ.get("DISCORD_BOT_TOKEN", "")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "")

    if not token or not channel_id:
        print("[오류] 환경변수 DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID 가 필요합니다.")
        sys.exit(1)

    config = load_json(CONFIG_FILE, {"sites": []})
    state  = load_json(STATE_FILE, {})

    sites = config.get("sites", [])
    if not sites:
        print("[오류] config.json 에 사이트가 없습니다.")
        sys.exit(1)

    state_changed = False

    for site in sites:
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
            state_changed = True
            continue

        changes = detect_changes(old_st, new_st)
        if changes:
            nl, nt = len(changes["new_links"]), len(changes["new_texts"])
            print(f"  → 변경 감지! 새 링크 {nl}개 / 새 텍스트 {nt}개")
            embed = build_embed(name, url, changes)
            if send_discord_message(token, channel_id, embed):
                state[url] = new_st
                state_changed = True
        else:
            print(f"  → 변화 없음\n")

    if state_changed:
        save_json(STATE_FILE, state)
        print(f"[{ts()}] state.json 저장 완료")

if __name__ == "__main__":
    main()
