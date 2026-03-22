#!/usr/bin/env python3
"""Reel → Transcription → Ukrainian Scenario → Airtable"""

import json
import os
import sys
import time
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path

AIRTABLE_API_KEY  = os.environ.get("AIRTABLE_API_KEY",  "")
AIRTABLE_BASE_ID  = os.environ.get("AIRTABLE_BASE_ID",  "app4Nttqp62S6EbWj")
AIRTABLE_TABLE_ID = os.environ.get("AIRTABLE_TABLE_ID", "tblzsGkdWedM5hAgT")
ASSEMBLYAI_KEY    = os.environ.get("ASSEMBLYAI_API_KEY", "")
ANTHROPIC_KEY     = os.environ.get("ANTHROPIC_API_KEY",  "")
COOKIES_FILE      = Path("cookies.txt")

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


# ── Step 1: get direct video URL via yt-dlp ───────────────────────────────────

def get_video_url(reel_url: str) -> str | None:
    cmd = ["yt-dlp", "--get-url", "--no-check-certificates", "-f", "best[ext=mp4]/best"]
    if COOKIES_FILE.exists():
        cmd += ["--cookies", str(COOKIES_FILE)]
    cmd.append(reel_url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        url = result.stdout.strip().splitlines()[0] if result.returncode == 0 else None
        return url or None
    except Exception:
        return None


# ── Step 2: transcribe via AssemblyAI ────────────────────────────────────────

def _aai_request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"https://api.assemblyai.com/v2{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers={
        "authorization": ASSEMBLYAI_KEY,
        "content-type": "application/json",
    }, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def transcribe(video_url: str) -> str | None:
    if not ASSEMBLYAI_KEY:
        print("❌ ASSEMBLYAI_API_KEY not set")
        return None

    print("   📤 Submitting to AssemblyAI...")
    job = _aai_request("POST", "/transcript", {"audio_url": video_url})
    job_id = job.get("id")
    if not job_id:
        print(f"   ❌ AssemblyAI error: {job}")
        return None

    print("   ⏳ Transcribing", end="", flush=True)
    while True:
        time.sleep(3)
        status = _aai_request("GET", f"/transcript/{job_id}")
        s = status.get("status")
        if s == "completed":
            print(" ✓")
            return status.get("text", "").strip()
        elif s == "error":
            print(f"\n   ❌ {status.get('error')}")
            return None
        print(".", end="", flush=True)


# ── Step 3: generate Ukrainian scenario via Claude ────────────────────────────

def generate_scenario(transcript: str) -> str | None:
    if not ANTHROPIC_KEY:
        print("❌ ANTHROPIC_API_KEY not set")
        return None
    try:
        import anthropic
    except ImportError:
        print("❌ Run: pip install anthropic")
        return None

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    messages = [{"role": "user", "content": f"Транскрипція:\n\n{transcript}\n\nСтвори сценарій рілса."}]

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


# ── Step 4: push to Airtable ──────────────────────────────────────────────────

def push_to_airtable(reel_url: str, transcript: str, scenario: str) -> bool:
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_ID}"
    payload = json.dumps({"records": [{"fields": {
        "Name": reel_url,
        "Source URL": reel_url,
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

def run(reel_url: str) -> None:
    print(f"\n🔗 {reel_url}\n")

    # Step 1 — get direct video URL
    print("1️⃣  Getting video URL...")
    video_url = get_video_url(reel_url)
    if not video_url:
        print("   ❌ Could not extract video URL (try adding cookies.txt)")
        return
    print(f"   ✓ Got CDN URL\n")

    # Step 2 — transcribe
    print("2️⃣  Transcribing...")
    transcript = transcribe(video_url)
    if not transcript:
        return
    print(f"   ✓ {len(transcript.split())} words\n")

    # Step 3 — generate scenario
    print("3️⃣  Generating Ukrainian scenario...")
    scenario = generate_scenario(transcript)
    if not scenario:
        return
    print(f"   ✓ Done\n")

    # Step 4 — save to Airtable
    print("4️⃣  Saving to Airtable...")
    if push_to_airtable(reel_url, transcript, scenario):
        print("   ✓ Saved\n")
    else:
        return

    # Print scenario to terminal too
    print("─" * 60)
    print(scenario)
    print("─" * 60)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python agent.py <reel_url>")
        print("Example: python agent.py https://www.instagram.com/reel/...")
        sys.exit(1)
    run(sys.argv[1])


if __name__ == "__main__":
    main()
