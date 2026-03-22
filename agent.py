#!/usr/bin/env python3
"""Content Backlog Agent — turns any content or link into Instagram, YouTube & Threads ideas."""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path

BACKLOG_FILE = Path("backlog.json")
COOKIES_FILE = Path("cookies.txt")
WHISPER_MODEL = "base"  # tiny | base | small | medium | large


def _ensure_ffmpeg() -> None:
    """Add static ffmpeg to PATH if system ffmpeg is unavailable."""
    import shutil
    if shutil.which("ffmpeg"):
        return
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except ImportError:
        pass

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

SCENARIO_PROMPT = """Ти — експерт зі створення вірусних Reels у ніші Tech/AI інструментів для україномовної аудиторії.

Тобі дають транскрипцію або опис відео. Твоє завдання — створити повноцінний сценарій для власного рілса на цю тему.

Адаптуй ідею під українського глядача, не копіюй оригінал — переосмисли її по-своєму.

Поверни відповідь ТІЛЬКИ у такому форматі (без зайвого тексту):

🎬 СЦЕНАРІЙ РІЛСА

🪝 ХУК (0–3 секунди):
[Одна потужна фраза, яка зупиняє скрол. Має викликати здивування або цікавість.]

📝 ОСНОВНИЙ ТЕКСТ (озвучка):
[Повний текст для озвучення. Розмовний стиль, короткі речення. 60–90 секунд.]

🎥 ВІЗУАЛЬНІ ВКАЗІВКИ:
[По кроках: що показувати на екрані в кожен момент. Конкретно і практично.]

📣 ЗАКЛИК ДО ДІЇ:
[Фінальна фраза + що зробити глядачу: підписатись, зберегти, написати в коментарях тощо.]"""


# ── Backlog helpers ────────────────────────────────────────────────────────────

def load_backlog() -> list:
    if BACKLOG_FILE.exists():
        return json.loads(BACKLOG_FILE.read_text())
    return []


def save_backlog(backlog: list) -> None:
    BACKLOG_FILE.write_text(json.dumps(backlog, indent=2, ensure_ascii=False))


# ── yt-dlp helpers ────────────────────────────────────────────────────────────

def _yt_dlp_base_cmd() -> list[str]:
    cmd = ["yt-dlp", "--no-check-certificates"]
    if COOKIES_FILE.exists():
        cmd += ["--cookies", str(COOKIES_FILE)]
    return cmd


def fetch_metadata(url: str) -> dict | None:
    """Extract title, description, uploader via yt-dlp --dump-json."""
    cmd = _yt_dlp_base_cmd() + ["--dump-json", "--no-download", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def transcribe_audio(url: str) -> str | None:
    _ensure_ffmpeg()
    """Download audio from URL and transcribe with Whisper."""
    try:
        import whisper
    except ImportError:
        print("   ⚠️  Whisper not installed. Run: pip install openai-whisper")
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.%(ext)s")
        cmd = _yt_dlp_base_cmd() + [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "-o", audio_path,
            url,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                print(f"   ⚠️  Download failed: {result.stderr[:200]}")
                return None
        except Exception as e:
            print(f"   ⚠️  Download error: {e}")
            return None

        # Find the downloaded file
        mp3_files = list(Path(tmpdir).glob("*.mp3"))
        if not mp3_files:
            return None

        print(f"   🎙️  Transcribing with Whisper ({WHISPER_MODEL})...")
        model = whisper.load_model(WHISPER_MODEL)
        result = model.transcribe(str(mp3_files[0]))
        return result.get("text", "").strip()


def extract_content(url: str) -> tuple[str, str]:
    """
    Returns (content_text, method_used).
    Tries: metadata description → Whisper transcription.
    """
    print("   📋 Fetching metadata...")
    meta = fetch_metadata(url)

    if meta:
        title = meta.get("title", "")
        description = meta.get("description", "") or meta.get("caption", "")
        uploader = meta.get("uploader", "") or meta.get("channel", "")

        parts = []
        if uploader:
            parts.append(f"Creator: @{uploader}")
        if title:
            parts.append(f"Title: {title}")
        if description:
            parts.append(f"Caption/Description: {description[:800]}")

        if parts:
            return "\n".join(parts), "metadata"

    # Fall back to Whisper
    print("   🎵 No description found — transcribing audio...")
    transcript = transcribe_audio(url)
    if transcript:
        return f"Audio transcript:\n{transcript}", "whisper"

    return "", "failed"


# ── Idea generation ───────────────────────────────────────────────────────────

def generate_scenario_api(content: str) -> str | None:
    """Generate a Ukrainian reel scenario via Claude API."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": f"Ось транскрипція/опис відео:\n\n{content}\n\nСтвори сценарій мого рілса на цю тему."}]

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=SCENARIO_PROMPT,
            messages=messages,
        )
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        for block in response.content:
            if block.type == "text":
                return block.text.strip()
        break
    return None


def generate_ideas_api(content: str) -> dict | None:
    """Use Claude API if ANTHROPIC_API_KEY is set."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": f"Generate content ideas for my backlog:\n\n{content}"}]

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
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
                    return {"source_summary": text, "ideas": {"instagram": [], "youtube": [], "threads": []}}
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
    for key, label in [("instagram", "📸 Instagram"), ("youtube", "🎥 YouTube"), ("threads", "🧵 Threads")]:
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

    if is_url:
        if not COOKIES_FILE.exists():
            print("⚠️  cookies.txt not found.")
            print("   1. Install: https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc")
            print("   2. Go to instagram.com (logged in) → export cookies.txt")
            print(f"   3. Drop cookies.txt in: {Path.cwd()}")
            print("\n   Or describe the content and I'll generate ideas directly.")
            return

        print(f"⏳ Processing {content[:60]}...")
        extracted, method = extract_content(content)

        if not extracted:
            print("❌ Could not extract content. Try describing it manually.")
            return

        print(f"   ✓ Got content via {method}\n")
        data = generate_ideas_api(extracted)

        if not data:
            # Print extracted content for in-session use
            print("── Extracted content (paste this to Claude Code for ideas) ──")
            print(extracted)
            print("─" * 60)
            return

        _write_entry(content, data)
    else:
        # Plain text — generate via API or print for in-session use
        data = generate_ideas_api(content)
        if data:
            _write_entry(content, data)
        else:
            print("── Send this to Claude Code for ideas ──")
            print(content)


def cmd_scenario(input_text: str) -> None:
    """Transcribe a reel URL (or accept pasted text) and generate a Ukrainian scenario."""
    is_url = input_text.strip().startswith(("http://", "https://"))

    if is_url:
        if not COOKIES_FILE.exists():
            print("⚠️  cookies.txt not found — needed to download Instagram audio.")
            print("   Or paste the transcript directly: python agent.py scenario \"your transcript\"")
            return
        print(f"⏳ Processing {input_text[:60]}...")
        content, method = extract_content(input_text)
        if not content:
            print("❌ Could not extract content from URL.")
            print("   Try: python agent.py scenario \"paste transcript here\"")
            return
        print(f"   ✓ Got content via {method}\n")
    else:
        content = input_text

    print("🇺🇦 Generating Ukrainian reel scenario...\n")
    scenario = generate_scenario_api(content)

    if scenario:
        print(scenario)
        print()
        # Optionally save to backlog as well
        backlog = load_backlog()
        entry = {
            "id": len(backlog) + 1,
            "date": datetime.now().isoformat(),
            "source": input_text[:120],
            "source_summary": content[:300],
            "scenario_uk": scenario,
            "ideas": {},
            "status": "pending",
        }
        backlog.append(entry)
        save_backlog(backlog)
        print(f"✅ Saved to backlog as entry #{entry['id']}")
    else:
        print("── Paste this into Claude Code to generate the scenario ──")
        print(content)
        print("─" * 60)
        print("Prompt: Створи сценарій рілса на цю тему українською мовою з хуком, основним текстом, візуальними вказівками та CTA.")


def cmd_airtable() -> None:
    """Sync all backlog entries to Airtable — one row per idea."""
    api_key = os.environ.get("AIRTABLE_API_KEY")
    base_id = os.environ.get("AIRTABLE_BASE_ID")
    table_name = os.environ.get("AIRTABLE_TABLE_NAME", "Content Backlog")

    if not api_key or not base_id:
        print("❌ Missing environment variables. Set these before running:")
        print("   export AIRTABLE_API_KEY=your_personal_access_token")
        print("   export AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX")
        print("   export AIRTABLE_TABLE_NAME='Content Backlog'  # optional, default used if omitted")
        print("\nGet your token at: https://airtable.com/create/tokens")
        print("Find your Base ID in the API docs: https://airtable.com/api")
        return

    backlog = load_backlog()
    if not backlog:
        print("Backlog is empty — nothing to sync.")
        return

    # Flatten entries → one record per idea
    records = []
    platform_labels = {"instagram": "Instagram", "youtube": "YouTube", "threads": "Threads"}
    for entry in backlog:
        for platform_key, platform_label in platform_labels.items():
            for idea in entry.get("ideas", {}).get(platform_key, []):
                records.append({
                    "fields": {
                        "Name": idea.get("title", ""),
                        "Platform": platform_label,
                        "Format": idea.get("format", ""),
                        "Description": idea.get("description", ""),
                        "Source Summary": entry.get("source_summary", ""),
                        "Source": entry.get("source", ""),
                        "Date": entry.get("date", "")[:10],
                        "Entry ID": int(entry.get("id", 0)),
                    }
                })

    if not records:
        print("No ideas found in backlog.")
        return

    # Airtable allows max 10 records per request
    url = f"https://api.airtable.com/v0/{base_id}/{urllib.parse.quote(table_name)}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    pushed = 0
    for i in range(0, len(records), 10):
        batch = records[i:i + 10]
        payload = json.dumps({"records": batch}).encode()
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                pushed += len(result.get("records", []))
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"❌ Airtable error {e.code}: {body}")
            return

    print(f"✅ Synced {pushed} ideas to Airtable → {table_name}")
    print(f"   Base: {base_id}")


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
    print("🎯 Reel Scenario Generator")
    print("Paste a reel URL or transcript → get a Ukrainian scenario")
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
        elif content.lower().startswith("scenario "):
            cmd_scenario(content[9:].strip())
        else:
            cmd_scenario(content)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        interactive()
    elif args[0] == "list":
        cmd_list()
    elif args[0] == "scenario" and len(args) > 1:
        cmd_scenario(" ".join(args[1:]))
    elif args[0] == "airtable":
        cmd_airtable()
    elif args[0] == "save" and len(args) > 1:
        cmd_save(" ".join(args[1:]))
    else:
        cmd_add(" ".join(args))


if __name__ == "__main__":
    main()
