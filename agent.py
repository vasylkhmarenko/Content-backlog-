#!/usr/bin/env python3
"""Video URL / local file → Transcript → Ukrainian Scenario → Airtable

Supported inputs:
  - YouTube, TikTok, Twitter/X, Facebook, Vimeo, etc. (any yt-dlp source)
  - Direct video URL (.mp4, .mov, .webm …)
  - Local file path  (/path/to/video.mp4)

Instagram note: Instagram blocks server IPs.
  Workaround: download reel on your phone → upload to Google Drive/Dropbox
  → copy direct download link → pass here.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime

AIRTABLE_API_KEY  = os.environ.get("AIRTABLE_API_KEY",  "")
AIRTABLE_BASE_ID  = os.environ.get("AIRTABLE_BASE_ID",  "app4Nttqp62S6EbWj")
AIRTABLE_TABLE_ID = os.environ.get("AIRTABLE_TABLE_ID", "tblzsGkdWedM5hAgT")
ANTHROPIC_KEY     = os.environ.get("ANTHROPIC_API_KEY", "")

SCENARIO_PROMPT = """Ти — експерт зі створення вірусних Reels у ніші Tech/AI інструментів для україномовної аудиторії.

Тобі дають транскрипцію відео. Твоє завдання — створити повноцінний сценарій для власного рілса на цю тему.
Адаптуй ідею під українського глядача, не копіюй оригінал — переосмисли по-своєму.

Поверни відповідь ТІЛЬКИ у такому форматі:

🪝 ХУК (0–3 секунди):
[Одна потужна фраза, яка зупиняє скрол.]

📝 ТЕКСТ (озвучка):
[Повний текст для озвучення. Розмовний стиль, короткі речення. 60–90 секунд.]

🎥 ВІЗУАЛ:
[По кроках: що показувати на екрані в кожен момент.]

📣 CTA:
[Фінальна фраза + що зробити глядачу.]"""


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_local(source: str) -> bool:
    return os.path.exists(source)


def _is_direct_video(url: str) -> bool:
    """True for plain .mp4/.mov/.webm/etc. URLs (no JS needed)."""
    VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
    path = url.split("?")[0].lower()
    return any(path.endswith(ext) for ext in VIDEO_EXTS)


def _download_direct(url: str, dest: str) -> bool:
    """Download a plain video URL with progress."""
    print("   📥 Downloading direct video URL...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            while chunk := resp.read(1 << 16):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r   {pct}%", end="", flush=True)
        print()
        return True
    except Exception as e:
        print(f"   ❌ Download error: {e}")
        return False


# ── Step 1: get audio / video file, then transcribe ──────────────────────────

def transcribe(source: str) -> str | None:
    import tempfile
    import subprocess
    from faster_whisper import WhisperModel

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "audio.mp3")

        if _is_local(source):
            # Local file — transcribe directly (no download needed)
            print("   📂 Using local file...")
            input_path = source
        elif _is_direct_video(source):
            # Plain video URL — download ourselves
            video_path = os.path.join(tmpdir, "video.mp4")
            ok = _download_direct(source, video_path)
            if not ok:
                return None
            input_path = video_path
        else:
            # yt-dlp handles everything else (YouTube, TikTok, Twitter, …)
            print("   📥 Downloading via yt-dlp...")
            result = subprocess.run(
                [
                    "yt-dlp",
                    "-x", "--audio-format", "mp3",
                    "-o", audio_path,
                    source,
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"   ❌ yt-dlp error:\n{result.stderr.strip()}")
                return None
            input_path = audio_path

        print("   🎙️ Transcribing with Whisper...")
        model = WhisperModel("base", compute_type="int8")
        segments, _ = model.transcribe(input_path)
        transcript = " ".join(s.text for s in segments).strip()

    words = len(transcript.split())
    print(f"   ✓ {words} words")
    return transcript


# ── Step 2: generate Ukrainian scenario via Claude Code CLI ───────────────────

def generate_scenario(transcript: str) -> str | None:
    import subprocess

    prompt = f"{SCENARIO_PROMPT}\n\nТранскрипція:\n\n{transcript}\n\nСтвори сценарій рілса."
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"   ❌ claude CLI error: {result.stderr.strip()}")
        return None
    return result.stdout.strip()


# ── Step 3: push to Airtable ──────────────────────────────────────────────────

def push_to_airtable(source: str, transcript: str, scenario: str) -> bool:
    if not AIRTABLE_API_KEY:
        print("❌ AIRTABLE_API_KEY not set")
        return False

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
    payload = json.dumps({"records": [{"fields": {
        "Name": source,
        "Source URL": source if source.startswith("http") else os.path.basename(source),
        "Transcription": transcript,
        "Scenario (UA)": scenario,
        "Date": datetime.now().strftime("%Y-%m-%d"),
    }}]}).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {AIRTABLE_API_KEY}",
        "Content-Type": "application/json",
    }, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            return bool(result.get("records"))
    except urllib.error.HTTPError as e:
        print(f"   ❌ Airtable error {e.code}: {e.read().decode()}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def run(source: str) -> None:
    print(f"\n🔗 {source}\n")

    print("1️⃣  Transcribing...")
    transcript = transcribe(source)
    if not transcript:
        return
    print()

    print("2️⃣  Generating Ukrainian scenario...")
    scenario = generate_scenario(transcript)
    if not scenario:
        return
    print("   ✓ Done\n")

    print("3️⃣  Saving to Airtable...")
    if not push_to_airtable(source, transcript, scenario):
        return
    print("   ✓ Saved\n")

    print("─" * 60)
    print(scenario)
    print("─" * 60)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        print("Usage: python agent.py <url-or-file-path>")
        sys.exit(1)
    run(sys.argv[1])


if __name__ == "__main__":
    main()
