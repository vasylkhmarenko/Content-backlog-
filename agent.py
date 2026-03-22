#!/usr/bin/env python3
"""Content Backlog Agent — turns any content or link into Instagram, YouTube & Threads ideas."""

import json
import sys
from datetime import datetime
from pathlib import Path

import anthropic

BACKLOG_FILE = Path("backlog.json")

SYSTEM_PROMPT = """You are a creative content strategist for a personal creator.

Analyze the provided content or URL and generate specific, actionable content ideas for:
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


def load_backlog() -> list:
    if BACKLOG_FILE.exists():
        return json.loads(BACKLOG_FILE.read_text())
    return []


def save_backlog(backlog: list) -> None:
    BACKLOG_FILE.write_text(json.dumps(backlog, indent=2, ensure_ascii=False))


def process_content(content: str) -> dict | None:
    client = anthropic.Anthropic()

    is_url = content.strip().startswith(("http://", "https://"))

    if is_url:
        user_message = (
            f"Fetch and analyze this URL, then generate content ideas for my backlog: {content}"
        )
        tools = [{"type": "web_fetch_20260209", "name": "web_fetch"}]
    else:
        user_message = (
            f"Analyze this content and generate platform-specific ideas for my backlog:\n\n{content}"
        )
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
            # Server-side tool hit iteration limit — append and continue
            messages.append({"role": "assistant", "content": response.content})
            continue

        # end_turn — extract JSON from the text block
        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                # Strip markdown code fences if present
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
    print("⏳ Generating ideas...")
    data = process_content(content)
    if not data:
        print("❌ Failed to generate ideas. Make sure ANTHROPIC_API_KEY is set.")
        return

    backlog = load_backlog()
    entry = {
        "id": len(backlog) + 1,
        "date": datetime.now().isoformat(),
        "source": content,
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
    print("Paste any content or URL → get Instagram, YouTube & Threads ideas")
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
    else:
        cmd_add(" ".join(args))


if __name__ == "__main__":
    main()
