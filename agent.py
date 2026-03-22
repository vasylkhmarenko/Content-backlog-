#!/usr/bin/env python3
"""Reel → Transcript24 → Ukrainian Scenario → Airtable"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime

AIRTABLE_API_KEY  = os.environ.get("AIRTABLE_API_KEY",  "")
AIRTABLE_BASE_ID  = os.environ.get("AIRTABLE_BASE_ID",  "app4Nttqp62S6EbWj")
AIRTABLE_TABLE_ID = os.environ.get("AIRTABLE_TABLE_ID", "tblzsGkdWedM5hAgT")
TRANSCRIPT24_KEY  = os.environ.get("TRANSCRIPT24_API_KEY", "")
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


# ── Step 1: transcribe via Transcript24 ──────────────────────────────────────

def transcribe(reel_url: str) -> str | None:
    if not TRANSCRIPT24_KEY:
        print("❌ TRANSCRIPT24_API_KEY not set")
        return None

    print("   📤 Sending to Transcript24...")
    payload = json.dumps({"url": reel_url, "prefer": "auto"}).encode()
    req = urllib.request.Request(
        "https://api.transcript24.com/transcribe",
        data=payload,
        headers={
            "Authorization": f"Bearer {TRANSCRIPT24_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"   ❌ Transcript24 error {e.code}: {e.read().decode()}")
        return None

    captions = data.get("caption", [])
    if not captions:
        print("   ❌ No captions returned")
        return None

    transcript = " ".join(c["text"] for c in captions).strip()
    mode = data.get("mode", "?")
    words = len(transcript.split())
    print(f"   ✓ {words} words (mode: {mode})")
    return transcript


# ── Step 2: generate Ukrainian scenario via Claude Code CLI ───────────────────

def generate_scenario(transcript: str) -> str | None:
    import subprocess

    prompt = f"{SCENARIO_PROMPT}\n\nТранскрипція:\n\n{transcript}\n\nСтвори сценарій рілса."
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"   ❌ claude CLI error: {result.stderr.strip()}")
        return None
    return result.stdout.strip()


# ── Step 3: push to Airtable ──────────────────────────────────────────────────

def push_to_airtable(reel_url: str, transcript: str, scenario: str) -> bool:
    if not AIRTABLE_API_KEY:
        print("❌ AIRTABLE_API_KEY not set")
        return False

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

    print("1️⃣  Transcribing...")
    transcript = transcribe(reel_url)
    if not transcript:
        return
    print()

    print("2️⃣  Generating Ukrainian scenario...")
    scenario = generate_scenario(transcript)
    if not scenario:
        return
    print("   ✓ Done\n")

    print("3️⃣  Saving to Airtable...")
    if not push_to_airtable(reel_url, transcript, scenario):
        return
    print("   ✓ Saved\n")

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
