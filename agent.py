#!/usr/bin/env python3
"""Content Backlog Agent — turns any content or link into Instagram, YouTube & Threads ideas."""

import json
import re
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

BACKLOG_FILE = Path("backlog.json")

SYSTEM_PROMPT = """You are a creative content strategist for a personal creator.

Analyze the provided content and generate specific, actionable content ideas for:
- Instagram: Reels, carousels, Stories, static posts
- YouTube: Video concepts with hooks, formats, and thumbnail ideas
- Threads: Text posts, thread formats, conversation starters

Return ONLY a valid JSON object in this exact format — no prose, no markdown fences:
{
  "source_summary": "2-3 sentence summary of what the input is about",
  "ideas": {
    "instagram": [
      {"title": "...", "description": "one sentence on the angle/execution", "format": "Reel|Post|Story|Carousel"}
    ],
    "youtube": [
      {"title": "...", "description": "one sentence on the angle/execution", "format": "Short|Long-form|Tutorial|Vlog|Essay"}
    ],
    "threads": [
      {"title": "...", "description": "one sentence on the angle/execution", "format": "Single post|Thread"}
    ]
  }
}

Generate 2-3 ideas per platform. Be specific, platform-native, and actionable."""


# ── Backlog helpers ────────────────────────────────────────────────────────────

def load_backlog() -> list:
    if BACKLOG_FILE.exists():
        return json.loads(BACKLOG_FILE.read_text())
    return []


def save_backlog(backlog: list) -> None:
    BACKLOG_FILE.write_text(json.dumps(backlog, indent=2, ensure_ascii=False))


# ── Social media metadata fetchers ────────────────────────────────────────────

def _fetch_url(url: str, timeout: int = 8) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def fetch_tiktok_meta(url: str) -> str | None:
    """TikTok has a public oEmbed endpoint — returns title + author."""
    oembed = f"https://www.tiktok.com/oembed?url={urllib.parse.quote(url)}"
    raw = _fetch_url(oembed)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        title = data.get("title", "")
        author = data.get("author_name", "")
        return f"TikTok by @{author}: {title}" if title else None
    except Exception:
        return None


def fetch_instagram_meta(url: str) -> str | None:
    """Try Instagram's embed page to extract caption text."""
    # Extract shortcode from URL
    match = re.search(r"/(reel|p)/([A-Za-z0-9_-]+)", url)
    if not match:
        return None
    shortcode = match.group(2)
    embed_url = f"https://www.instagram.com/reel/{shortcode}/embed/"
    raw = _fetch_url(embed_url)
    if not raw:
        return None
    # Pull caption from embed HTML
    cap = re.search(r'class="Caption"[^>]*>(.*?)</div>', raw, re.DOTALL)
    if cap:
        text = re.sub(r"<[^>]+>", "", cap.group(1)).strip()
        if text:
            return f"Instagram Reel caption: {text[:500]}"
    return None


def fetch_youtube_meta(url: str) -> str | None:
    """YouTube oEmbed for title."""
    oembed = f"https://www.youtube.com/oembed?url={urllib.parse.quote(url)}&format=json"
    raw = _fetch_url(oembed)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        title = data.get("title", "")
        author = data.get("author_name", "")
        return f"YouTube video by {author}: {title}" if title else None
    except Exception:
        return None


def detect_and_fetch(url: str) -> str | None:
    """Try to extract meaningful text from a social media URL."""
    u = url.lower()
    if "tiktok.com" in u:
        return fetch_tiktok_meta(url)
    if "instagram.com" in u:
        return fetch_instagram_meta(url)
    if "youtube.com" in u or "youtu.be" in u:
        return fetch_youtube_meta(url)
    return None


# ── Claude API processing (requires ANTHROPIC_API_KEY) ───────────────────────

def process_with_api(content: str) -> dict | None:
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    is_url = content.strip().startswith(("http://", "https://"))

    if is_url:
        meta = detect_and_fetch(content)
        if meta:
            user_message = f"Generate content ideas for my backlog based on this:\n\n{meta}\n\nOriginal URL: {content}"
            tools = None
        else:
            user_message = f"Fetch and analyze this URL, then generate content ideas: {content}"
            tools = [{"type": "web_fetch_20260209", "name": "web_fetch"}]
    else:
        user_message = f"Analyze this and generate platform-specific ideas:\n\n{content}"
        tools = None

    messages = [{"role": "user", "content": user_message}]

    while True:
        kwargs: dict = dict(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                if "```json" in text:
                    text = text.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in text:
                    text = text.split("```", 1)[1].split("```", 1)[0].strip()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {
                        "source_summary": text,
                        "ideas": {"instagram": [], "youtube": [], "threads": []},
                    }
        break

    return None


# ── Display ───────────────────────────────────────────────────────────────────

def print_entry(entry: dict) -> None:
    date = entry["date"][:10]
    source = entry["source"]
    if len(source) > 70:
        source = source[:67] + "..."

    print(f"\n{'─' * 62}")
    print(f"#{entry['id']}  {date}  |  {source}")
    if entry.get("source_summary"):
        print(f"↳ {entry['source_summary']}")

    ideas = entry.get("ideas", {})
    platforms = [
        ("instagram", "📸 Instagram"),
        ("youtube", "🎥 YouTube"),
        ("threads", "🧵 Threads"),
    ]

    for key, label in platforms:
        items = ideas.get(key, [])
        if items:
            print(f"\n  {label}")
            for idea in items:
                fmt = f"[{idea['format']}] " if idea.get("format") else ""
                print(f"    • {fmt}{idea['title']}")
                if idea.get("description"):
                    print(f"      {idea['description']}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_list() -> None:
    backlog = load_backlog()
    if not backlog:
        print('Backlog is empty. Add something with: python agent.py "your content or URL"')
        return
    print(f"\n📋 Content Backlog — {len(backlog)} entries")
    for entry in reversed(backlog):
        print_entry(entry)
    print()


def cmd_add(content: str) -> None:
    is_url = content.strip().startswith(("http://", "https://"))

    # Try to fetch social media metadata first
    meta = None
    if is_url:
        print("⏳ Fetching metadata...")
        meta = detect_and_fetch(content)
        if meta:
            print(f"   {meta[:120]}")

    import os
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("⏳ Generating ideas via API...")
        data = process_with_api(content)
        if data:
            _write_entry(content, data)
            return
        print("❌ API call failed.")
    else:
        # No API key — print what we have so the user can get ideas from Claude Code session
        if meta:
            print("\n💡 Metadata fetched. Paste this into your Claude Code chat to get ideas:\n")
            print(f"   {meta}")
        else:
            print("\n⚠️  No ANTHROPIC_API_KEY set and couldn't fetch metadata automatically.")
            print("   Describe the content in your Claude Code chat and ask for backlog ideas.")
            print("   Then run: python agent.py save '<json>'")


def cmd_save(json_str: str) -> None:
    """Save pre-generated JSON ideas directly (for use without API key)."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return
    _write_entry(data.get("source", ""), data)


def _write_entry(source: str, data: dict) -> None:
    backlog = load_backlog()
    entry = {
        "id": len(backlog) + 1,
        "date": datetime.now().isoformat(),
        "source": source,
        "source_summary": data.get("source_summary", ""),
        "ideas": data.get("ideas", {}),
        "status": "pending",
    }
    backlog.append(entry)
    save_backlog(backlog)
    print_entry(entry)
    print(f"\n✅ Saved to backlog as entry #{entry['id']}")


def interactive() -> None:
    print("🎯 Content Backlog Agent")
    print("Paste any content, URL, or social media link")
    print("Commands: 'list' to view backlog, 'quit' to exit\n")

    while True:
        try:
            content = input("→ ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not content:
            continue
        if content.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break
        if content.lower() == "list":
            cmd_list()
        else:
            cmd_add(content)


def main() -> None:
    args = sys.argv[1:]

    if not args:
        interactive()
    elif args[0] == "list":
        cmd_list()
    elif args[0] == "save" and len(args) > 1:
        cmd_save(" ".join(args[1:]))
    else:
        cmd_add(" ".join(args))


if __name__ == "__main__":
    main()
