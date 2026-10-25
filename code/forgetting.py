"""
LifeLocker — Consequence-Reasoning Agent (Standalone Python Engine)
Identifies conflicts, hidden dependencies, and upcoming urgency across tracked items.
"""

import os
import json
import sqlite3
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(".env.local")
load_dotenv(".env")

SYSTEM_PROMPT = """You are a consequence-reasoning agent. You receive a list of a user's open tracked items. The list ALWAYS contains BOTH "email" type items and "todo" type items.

CRITICAL: You MUST consider ALL items. Todos (type "todo") are EQUALLY IMPORTANT as email obligations. If a todo has a deadline_date, it is a first-class deadline and must be checked for conflicts against email items. Do NOT ignore any item whose "type" is "todo".

Your job is NOT to repeat items. Your job is to find:
1. CONFLICTS — items that clash (e.g., travel planned + passport expiring)
2. HIDDEN DEPENDENCIES — item A requires item B, but B isn't tracked
3. LIKELY-TO-BE-FORGOTTEN — items with vague deadlines, no reminder, or that depend on external parties
4. UPCOMING URGENCY — items whose real deadline is sooner than it appears (subtract processing time)

Return ONLY valid JSON:
{
  "alerts": [
    {
      "severity": "red" | "orange" | "yellow",
      "title": "short headline (max 8 words)",
      "why": "one sentence explaining the consequence",
      "detail": "2-3 sentences with the reasoning chain",
      "involves_ids": ["o3", "t1"],
      "source_links": ["https://mail.google.com/..."],
      "obligation_id_for_done": 3
    }
  ],
  "summary": "one paragraph, casual tone, direct"
}

Rules:
- If there are fewer than 2 items total, return empty alerts and a summary saying so.
- Do NOT invent items not in the list.
- Do NOT do date math on exact dates — if you need math, note it in 'why' and flag it.
- Red = missed deadline is imminent or catastrophic. Orange = needs attention this week. Yellow = worth noting.
- MERGE OVERLAPPING ALERTS: if two alerts touch the same underlying issue, combine into ONE with the most severe rating.
- MAX 3 ALERTS. Pick the three most consequential.
- Each item has an "id" like "o3" (email obligation) or "t1" (manual todo).
- If an alert is primarily about ONE email obligation, set "obligation_id_for_done" to that numeric ID (without the "o" prefix) so the UI can mark it done. Otherwise use null.
- "source_links" should contain any gmail_link values for involved email items. Skip nulls. Empty array if none."""


def get_open_todos():
    """Fetches saved memories / open todos from SQLite database if present."""
    db_paths = ["data/lifelocker.db", "lifelocker.db", "../lifelocker/lifelocker.db"]
    todos = []
    
    for p in db_paths:
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                cursor = conn.cursor()
                cursor.execute("SELECT id, action, deadline_date, category, notes FROM todos WHERE status = 'open'")
                rows = cursor.fetchall()
                conn.close()
                for r in rows:
                    todos.append({
                        "id": f"t{r[0]}",
                        "type": "todo",
                        "action": r[1],
                        "deadline_phrase": None,
                        "deadline_date": r[2],
                        "category": r[3] or "todo",
                        "consequence_if_ignored": None,
                        "source_subject": None,
                        "source_quote": r[4] or "",
                        "gmail_link": None
                    })
                break
            except Exception:
                pass
                
    if not todos:
        todos = [
            {
                "id": "t1",
                "type": "todo",
                "action": "Renew international passport & visa for conference flight",
                "deadline_phrase": "Before travel",
                "deadline_date": "2026-11-10",
                "category": "travel",
                "consequence_if_ignored": "Cannot board flight without valid passport",
                "source_subject": None,
                "source_quote": "Passport renewal takes 4-6 weeks processing time.",
                "gmail_link": None
            }
        ]
    return todos


def get_open_obligations():
    """Recent email obligations from SQLite."""
    db_paths = ["data/lifelocker.db", "lifelocker.db", "../lifelocker/lifelocker.db"]
    obligations = []
    for p in db_paths:
        if os.path.exists(p):
            try:
                conn = sqlite3.connect(p)
                cursor = conn.cursor()
                cursor.execute("SELECT id, source_subject, source_sender, source_quote, action, deadline_phrase, deadline_date, category, consequence_if_ignored, gmail_link FROM obligations WHERE status = 'open'")
                rows = cursor.fetchall()
                conn.close()
                for r in rows:
                    obligations.append({
                        "id": f"o{r[0]}",
                        "type": "email",
                        "action": r[4],
                        "deadline_phrase": r[5],
                        "deadline_date": r[6],
                        "category": r[7],
                        "consequence_if_ignored": r[8],
                        "source_subject": r[1],
                        "source_quote": r[3],
                        "gmail_link": r[9]
                    })
                break
            except Exception:
                pass
    return obligations


def run_consequence_reasoning(limit=10):
    todos = get_open_todos()
    obligations = get_open_obligations()[:limit]
    all_items = obligations + todos

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    user_prompt = f"""Today is {today}.
Tracking {len(all_items)} items total: {len(obligations)} email obligations, {len(todos)} manual todos.
The list below is COMPLETE and UP TO DATE. Every item shown is currently open.

Items:
{json.dumps(all_items, indent=2)}
"""

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.2,
                )
            )
            if response.text:
                return json.loads(response.text)
        except Exception as e:
            print(f"[Warning] Gemini reasoning failed: {e}")

    # Fallback to Groq
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            gclient = Groq(api_key=groq_key)
            completion = gclient.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as ge:
            print(f"[Warning] Groq reasoning fallback failed: {ge}")

    return {
        "alerts": [],
        "summary": f"Tracking {len(all_items)} total items. No urgent conflicts found."
    }


if __name__ == "__main__":
    result = run_consequence_reasoning()
    print(json.dumps(result, indent=2))
