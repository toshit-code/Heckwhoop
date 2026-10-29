#!/usr/bin/env python3
"""
LIFELOCKER — AI Email Memory, Consequence Engine & Mail Reader
Powered by Groq gpt-oss-120b & Gemini with Gmail API
"""

import os
import sys
import json
import base64
import re
import sqlite3
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from flask import Flask, Response, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env.local"))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TOKEN_FILE = os.path.join(BASE_DIR, "user_token.json")
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
DB_FILE = os.path.join(BASE_DIR, "todos.db")
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

app = Flask(__name__)

# --- Database ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id TEXT,
            action TEXT NOT NULL,
            date_time TEXT,
            sort_date TEXT,
            category TEXT,
            consequence TEXT,
            source_subject TEXT,
            source_sender TEXT,
            source_quote TEXT,
            gmail_link TEXT,
            action_url TEXT,
            action_url_text TEXT,
            source_type TEXT DEFAULT 'email',
            priority INTEGER DEFAULT 10,
            status TEXT DEFAULT 'open',
            created_at TEXT
        )
    """)
    for col, col_type in [
        ("priority", "INTEGER DEFAULT 10"),
        ("msg_id", "TEXT"),
        ("action_url", "TEXT"),
        ("action_url_text", "TEXT"),
        ("source_type", "TEXT DEFAULT 'email'")
    ]:
        try:
            c.execute(f"ALTER TABLE todos ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS scanned_messages (
            msg_id TEXT PRIMARY KEY,
            subject TEXT,
            scanned_at TEXT,
            result TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

    recalculate_priorities()

# --- Gmail Service ---
def get_gmail_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_FILE) and os.path.getsize(TOKEN_FILE) > 0:
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def get_email_body(msg):
    if "parts" in msg.get("payload", {}):
        for part in msg["payload"]["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    elif "data" in msg.get("payload", {}).get("body", {}):
        data = msg["payload"]["body"]["data"]
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return ""

# --- LLM Prompts ---
EXTRACTION_PROMPT = """You are an email assistant for LIFELOCKER. Extract personal to-dos, required forms, deadlines, appointments, and actionable opportunities from emails.

WHAT QUALIFIES AS ACTIONABLE (Set is_actionable: true):
1. Hackathons, Grants, Contests & Projects:
   - Requesting API credits, cloud tokens, submissions, registrations, deadline reminders
2. Forms, Applications & Surveys:
   - Any email asking the user to fill out a Google Form, survey, application, or RSVP
3. Appointments & Schedule:
   - Dentist, doctor visits, interviews, team/client meetings with date or time
4. School & Academic:
   - Homework, classroom assignments, project submissions, exam notices
5. Travel & Bookings:
   - Flights, train/hotel reservations, passport/visa renewal deadlines
6. Deadlines & Payments:
   - Invoices to pay, fee dues, contract signings, submission cutoffs

STRICT EXCLUSIONS (Set is_actionable: false):
- Pure commercial advertising & sales discounts
- Routine SaaS product update announcements or automated Slack digests unless specifically requesting personal action
- Automated one-time passwords (OTP), 2FA codes, login security alerts
- Purchase receipts for transactions already completed

ACTIONABLE LINKS:
If the email contains an actionable web link directly related to completing the task (such as a Google Form, payment portal, submission URL):
- Extract the exact URL as "action_url" (or null if none)
- Provide a concise button label as "action_url_text" (e.g. "Pay Now", "Fill Form", "Submit Project", or null if none)

DATE RESOLUTION RULES:
- When the email mentions relative expressions like "tomorrow", "next Wednesday", "this Friday", "by next Monday":
  Calculate the exact calendar date (YYYY-MM-DD) based on Today's Reference Date provided.
- "sort_date": ISO formatted date string ("YYYY-MM-DD" or "YYYY-MM-DDTHH:MM" if time is given).
- "date_time": Clear human-readable date and time (e.g. "Wed, Nov 4, 2026 at 2:30 PM" or "Tomorrow, Oct 29, 2026").

Return valid JSON without markdown:
{
  "is_actionable": true | false,
  "action": "clear concise task description",
  "action_url": "https://... or null",
  "action_url_text": "short action text or null",
  "date_time": "human readable date and time or null",
  "sort_date": "YYYY-MM-DD or YYYY-MM-DDTHH:MM if time mentioned, else null",
  "category": "academic | hackathon | project | health | travel | legal | work | finance | personal",
  "consequence": "specific real-world impact if missed or ignored, or null",
  "source_quote": "relevant sentence from email"
}
"""

CONSEQUENCE_REASONING_PROMPT = """You are LIFELOCKER's consequence-reasoning intelligence.
Analyze the user's active tasks across their emails and custom tasks.
Find HIDDEN CONFLICTS, CROSS-TASK PREREQUISITES, and DEPENDENCIES.

Example Patterns:
- Flight trip confirmed + Passport expiring -> Renewing passport must be top priority because renewal takes weeks.
- User task 'Apply for Visa' + Flight booking -> Passport renewal must happen first before visa can be issued.
- Overdue bill + manual expense task -> Prioritize paying bill before cutoff/penalty.

Return valid JSON:
{
  "has_conflict": true | false,
  "alert_title": "short urgent warning or null",
  "alert_explanation": "one clear sentence detailing the real-world consequence chain or null",
  "top_priority_action": "exact task name that must be done first or null"
}
"""

SUMMARIZATION_PROMPT = """You are an email intelligence assistant for LIFELOCKER.
Summarize this email clearly and concisely.

Return valid JSON:
{
  "summary": "2-sentence clear overview of the email",
  "key_points": ["bullet 1", "bullet 2", "bullet 3"]
}
"""

def call_llm_json(system_prompt, user_prompt):
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            for m in ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
                try:
                    comp = client.chat.completions.create(
                        model=m,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.1,
                        timeout=10.0
                    )
                    text = comp.choices[0].message.content
                    return json.loads(text)
                except Exception:
                    continue
        except Exception:
            pass

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            gclient = genai.Client(api_key=gemini_key)
            for gm in ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash"]:
                try:
                    resp = gclient.models.generate_content(
                        model=gm,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            response_mime_type="application/json",
                            temperature=0.1
                        )
                    )
                    text = resp.text.strip()
                    if text.startswith("```"):
                        text = re.sub(r"^```(?:json)?\s*", "", text)
                        text = re.sub(r"\s*```$", "", text)
                    match = re.search(r"\{.*\}", text, re.DOTALL)
                    if match:
                        return json.loads(match.group())
                except Exception:
                    continue
        except Exception:
            pass

    return {}

def ensure_resolved_date(res, ref_dt=None):
    if not ref_dt:
        ref_dt = datetime.now()

    sort_date = res.get("sort_date")
    date_time = res.get("date_time") or ""

    is_valid_sort = bool(sort_date and re.match(r"^\d{4}-\d{2}-\d{2}", str(sort_date)) and not str(sort_date).startswith("9999"))

    dt_lower = date_time.lower().strip()
    from datetime import timedelta
    target_date = None

    if not is_valid_sort:
        if "tomorrow" in dt_lower:
            target_date = ref_dt + timedelta(days=1)
        elif "today" in dt_lower:
            target_date = ref_dt
        elif "yesterday" in dt_lower:
            target_date = ref_dt - timedelta(days=1)
        else:
            weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            for idx, day in enumerate(weekdays):
                if day in dt_lower:
                    current_weekday = ref_dt.weekday()
                    days_ahead = idx - current_weekday
                    if "next" in dt_lower:
                        if days_ahead <= 0:
                            days_ahead += 7
                    else:
                        if days_ahead <= 0:
                            days_ahead += 7
                    target_date = ref_dt + timedelta(days=days_ahead)
                    break

        if target_date:
            time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)\b", date_time)
            if time_match:
                hr = int(time_match.group(1))
                mn = int(time_match.group(2) or 0)
                ampm = time_match.group(3).lower()
                if ampm == "pm" and hr < 12:
                    hr += 12
                elif ampm == "am" and hr == 12:
                    hr = 0
                res["sort_date"] = f"{target_date.strftime('%Y-%m-%d')}T{hr:02d}:{mn:02d}"
            else:
                res["sort_date"] = target_date.strftime("%Y-%m-%d")

    # Format date_time into a clean, human-readable calculated calendar date
    final_sort = res.get("sort_date")
    if final_sort and not final_sort.startswith("9999"):
        has_relative = any(w in dt_lower for w in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "tomorrow", "today", "yesterday", "next"])
        if has_relative or not date_time:
            time_part = ""
            time_match = re.search(r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))\b", date_time)
            if time_match:
                time_part = f" at {time_match.group(1).upper()}"
            elif "T" in final_sort:
                try:
                    t_hr_mn = datetime.strptime(final_sort[:16], "%Y-%m-%dT%H:%M").strftime("%I:%M %p").lstrip("0")
                    time_part = f" at {t_hr_mn}"
                except Exception:
                    pass

            try:
                base_d = datetime.strptime(final_sort[:10], "%Y-%m-%d")
                res["date_time"] = base_d.strftime(f"%a, %b %d, %Y{time_part}")
            except Exception:
                pass

    return res

def extract_with_llm(subject, sender, body, email_date=None):
    lower_subj = subject.lower()
    lower_sender = sender.lower()
    if "security alert" in lower_subj or "no-reply@accounts.google.com" in lower_sender:
        return {"is_actionable": False}

    now = datetime.now()
    now_str = now.strftime("%A, %B %d, %Y (%Y-%m-%d)")
    date_context = f"Today's Reference Date: {now_str}"
    if email_date:
        date_context += f"\nEmail Received Date: {email_date}"

    user_prompt = f"{date_context}\nSubject: {subject}\nFrom: {sender}\nBody:\n{body[:3500]}"
    res = call_llm_json(EXTRACTION_PROMPT, user_prompt)
    if res.get("is_actionable"):
        res = ensure_resolved_date(res, now)
        return res
    return {"is_actionable": False}

def run_consequence_analysis(items):
    if not items or len(items) < 2:
        return {"has_conflict": False}

    items_summary = [{
        "action": it["action"],
        "date_time": it.get("date_time"),
        "category": it.get("category"),
        "source_type": it.get("source_type", "email"),
        "source_subject": it.get("source_subject", "")
    } for it in items]

    res = call_llm_json(CONSEQUENCE_REASONING_PROMPT, json.dumps(items_summary, indent=2))
    return res

# --- Database Operations ---
def is_already_scanned(msg_id):
    if not msg_id:
        return False
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM scanned_messages WHERE msg_id = ?", (msg_id,))
    scanned = c.fetchone() is not None
    conn.close()
    return scanned

def record_scanned(msg_id, subject, result):
    if not msg_id:
        return
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO scanned_messages (msg_id, subject, scanned_at, result)
        VALUES (?, ?, ?, ?)
    """, (msg_id, subject[:200], datetime.now(timezone.utc).isoformat(), result))
    conn.commit()
    conn.close()

def recalculate_priorities():
    """
    Standard priority recalculation based on actual urgency and deadline:
    - Consequence alert conflict items: Priority 1
    - Overdue or due today: Priority 2
    - Due within 2 days: Priority 3
    - Due within 5 days: Priority 4
    - Other dated items: Priority 5
    - Undated items: Priority 10
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    alert = get_consequence_alert()
    top_conflict = (alert.get("top_priority_action") or "").lower() if alert and alert.get("has_conflict") else ""
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    c.execute("SELECT id, action, date_time, sort_date, category, consequence, source_subject, source_quote, status FROM todos")
    rows = c.fetchall()

    for r in rows:
        todo_id, action, date_time, sort_date, category, consequence, subject, quote, status = r
        if status in ('done', 'skipped'):
            continue

        if top_conflict:
            tc_clean = top_conflict.strip().lower()
            act_clean = (action or "").strip().lower()
            tc_words = set(re.findall(r"\w+", tc_clean))
            act_words = set(re.findall(r"\w+", act_clean))
            common = tc_words.intersection(act_words) - {"the", "a", "an", "for", "to", "and", "or", "in", "on", "before", "after", "by", "with"}
            if tc_clean in act_clean or act_clean in tc_clean or len(common) >= 2:
                c.execute("UPDATE todos SET priority = 1 WHERE id = ?", (todo_id,))
                continue

        priority = 10
        if sort_date and sort_date != '9999-99-99':
            try:
                item_date = sort_date[:10]
                if item_date <= now_date:
                    priority = 2
                else:
                    d1 = datetime.strptime(now_date, "%Y-%m-%d")
                    d2 = datetime.strptime(item_date, "%Y-%m-%d")
                    diff = (d2 - d1).days
                    if diff <= 2:
                        priority = 3
                    elif diff <= 5:
                        priority = 4
                    else:
                        priority = 5
            except Exception:
                priority = 10

        c.execute("UPDATE todos SET priority = ? WHERE id = ?", (priority, todo_id))

    conn.commit()
    conn.close()

def store_todo(item):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    msg_id = item.get('msg_id', '')
    gmail_link = item.get('gmail_link', '')

    if msg_id:
        c.execute("SELECT id FROM todos WHERE msg_id = ?", (msg_id,))
    elif gmail_link:
        c.execute("SELECT id FROM todos WHERE gmail_link = ?", (gmail_link,))
    else:
        c.execute("SELECT id FROM todos WHERE action = ? AND source_type = 'manual'", (item['action'],))
    existing = c.fetchone()

    category = item.get('category', 'personal')
    consequence = item.get('consequence', '')
    priority = item.get('priority', 10)

    if existing is None:
        c.execute("""
            INSERT INTO todos (
                msg_id, action, date_time, sort_date, category, consequence,
                source_subject, source_sender, source_quote, gmail_link,
                action_url, action_url_text, source_type, priority, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """, (
            msg_id,
            item['action'],
            item.get('date_time') or item.get('deadline_phrase') or '',
            item.get('sort_date') or item.get('deadline_date') or '9999-99-99',
            category,
            consequence,
            item.get('source_subject', ''),
            item.get('source_sender', ''),
            item.get('source_quote', ''),
            gmail_link,
            item.get('action_url') or None,
            item.get('action_url_text') or None,
            item.get('source_type', 'email'),
            priority,
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
    else:
        todo_id = existing[0]
        c.execute("""
            UPDATE todos SET
                action = ?,
                date_time = ?,
                sort_date = ?,
                category = ?,
                consequence = ?,
                action_url = ?,
                action_url_text = ?
            WHERE id = ?
        """, (
            item['action'],
            item.get('date_time') or item.get('deadline_phrase') or '',
            item.get('sort_date') or item.get('deadline_date') or '9999-99-99',
            category,
            consequence,
            item.get('action_url') or None,
            item.get('action_url_text') or None,
            todo_id
        ))
        conn.commit()
    conn.close()

    recalculate_priorities()

def save_consequence_alert(alert):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES ('consequence_alert', ?)", (json.dumps(alert),))
    conn.commit()
    conn.close()

    recalculate_priorities()

def get_consequence_alert():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT value FROM system_state WHERE key = 'consequence_alert'")
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            pass
    return None

def get_todos(sort_by="criticalness"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    if sort_by == "time":
        order_by = """
            status ASC,
            CASE WHEN sort_date IS NULL OR sort_date = '' OR sort_date = '9999-99-99' THEN 1 ELSE 0 END ASC,
            sort_date ASC,
            priority ASC,
            id DESC
        """
    else:  # criticalness (default)
        order_by = """
            status ASC,
            priority ASC,
            CASE WHEN sort_date IS NULL OR sort_date = '' OR sort_date = '9999-99-99' THEN 1 ELSE 0 END ASC,
            sort_date ASC,
            id DESC
        """

    c.execute(f"""
        SELECT id, action, date_time, sort_date, category, consequence, source_subject, source_sender, source_quote, gmail_link, priority, status, action_url, action_url_text, source_type
        FROM todos
        WHERE status != 'skipped'
        ORDER BY {order_by}
    """)
    rows = c.fetchall()
    conn.close()
    return [{
        "id": r[0],
        "action": r[1],
        "date_time": r[2],
        "sort_date": r[3],
        "category": r[4],
        "consequence": r[5],
        "source_subject": r[6],
        "source_sender": r[7],
        "source_quote": r[8],
        "gmail_link": r[9],
        "priority": r[10],
        "status": r[11],
        "action_url": r[12],
        "action_url_text": r[13],
        "source_type": r[14] or "email"
    } for r in rows]

def refresh_consequence_state():
    """Re-evaluates consequence reasoning for open tasks."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, action, date_time, category, source_subject, source_type
        FROM todos
        WHERE status = 'open'
    """)
    open_rows = c.fetchall()
    conn.close()

    open_items = [{
        "id": r[0],
        "action": r[1],
        "date_time": r[2],
        "category": r[3],
        "source_subject": r[4],
        "source_type": r[5] or "email"
    } for r in open_rows]

    if len(open_items) < 2:
        save_consequence_alert({"has_conflict": False, "alert_title": None, "alert_explanation": None, "top_priority_action": None})
    else:
        new_alert = run_consequence_analysis(open_items)
        save_consequence_alert(new_alert)

    recalculate_priorities()

# --- Flask Routes ---
@app.route("/")
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.route("/api/todos")
def api_get_todos():
    sort_by = request.args.get("sort", "criticalness")
    return jsonify({
        "todos": get_todos(sort_by=sort_by),
        "consequence_alert": get_consequence_alert()
    })

@app.route("/api/todos/<int:todo_id>/complete", methods=["POST"])
def api_complete_todo(todo_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT status FROM todos WHERE id = ?", (todo_id,))
    row = c.fetchone()
    new_status = "open" if (row and row[0] == "done") else "done"
    c.execute("UPDATE todos SET status = ? WHERE id = ?", (new_status, todo_id))
    conn.commit()
    conn.close()

    refresh_consequence_state()
    recalculate_priorities()

    sort_by = request.args.get("sort", "criticalness")
    return jsonify({"ok": True, "todos": get_todos(sort_by=sort_by), "consequence_alert": get_consequence_alert()})

@app.route("/api/todos/<int:todo_id>/skip", methods=["POST"])
def api_skip_todo(todo_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE todos SET status = 'skipped' WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()

    refresh_consequence_state()
    recalculate_priorities()

    sort_by = request.args.get("sort", "criticalness")
    return jsonify({"ok": True, "todos": get_todos(sort_by=sort_by), "consequence_alert": get_consequence_alert()})

@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
def api_delete_todo(todo_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()

    refresh_consequence_state()
    recalculate_priorities()

    sort_by = request.args.get("sort", "criticalness")
    return jsonify({"ok": True, "todos": get_todos(sort_by=sort_by), "consequence_alert": get_consequence_alert()})

@app.route("/api/todos/manual", methods=["POST"])
def api_add_manual_todo():
    data = request.get_json() or {}
    action = (data.get("action") or "").strip()
    if not action:
        return jsonify({"error": "Task description is required"}), 400

    raw_date = (data.get("date_time") or "").strip()

    sort_date = "9999-99-99"
    display_date = raw_date
    if raw_date:
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw_date)
        if match:
            sort_date = match.group(1)
            try:
                parsed_dt = datetime.strptime(sort_date, "%Y-%m-%d")
                display_date = parsed_dt.strftime("%b %d, %Y")
            except Exception:
                display_date = sort_date

    item = {
        "action": action,
        "date_time": display_date or None,
        "sort_date": sort_date,
        "category": (data.get("category") or "personal").strip(),
        "consequence": "",
        "source_subject": "Personal To-Do",
        "source_sender": "User input",
        "source_quote": "",
        "gmail_link": "",
        "action_url": data.get("action_url") or None,
        "action_url_text": data.get("action_url_text") or None,
        "source_type": "manual"
    }

    store_todo(item)
    recalculate_priorities()
    refresh_consequence_state()

    sort_by = request.args.get("sort", "criticalness")
    return jsonify({"ok": True, "todos": get_todos(sort_by=sort_by), "consequence_alert": get_consequence_alert()})

@app.route("/api/rescan-reset", methods=["POST"])
def api_rescan_reset():
    clear_todos = request.args.get("clear_todos", "false").lower() == "true"
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM scanned_messages")
    if clear_todos:
        c.execute("DELETE FROM todos WHERE source_type = 'email'")
        c.execute("DELETE FROM system_state WHERE key = 'consequence_alert'")
    conn.commit()
    conn.close()
    recalculate_priorities()
    return jsonify({
        "ok": True,
        "message": "Scanned message history cleared" + (" and email tasks reset" if clear_todos else ""),
        "todos": get_todos(),
        "consequence_alert": get_consequence_alert()
    })

# --- See Mails Endpoints ---
@app.route("/api/emails")
def api_get_emails():
    try:
        service = get_gmail_service()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    scope = request.args.get("scope", "").lower()
    if scope == "today":
        limit = 50
        query = "newer_than:1d"
    elif scope == "3d":
        limit = 50
        query = "newer_than:3d"
    elif scope == "7d":
        limit = 50
        query = "newer_than:7d"
    elif scope.isdigit():
        limit = max(1, min(int(scope), 50))
        query = request.args.get("q", "newer_than:14d")
    else:
        limit = int(request.args.get("limit", 12))
        query = request.args.get("q", "newer_than:14d")

    try:
        res = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = res.get("messages", [])
        email_list = []

        for m in messages:
            msg_id = m["id"]
            try:
                msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            except Exception:
                continue

            headers = msg.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
            sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")
            date_str = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
            snippet = msg.get("snippet", "")
            body = get_email_body(msg) or snippet

            email_list.append({
                "id": msg_id,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "snippet": snippet,
                "body": body,
                "gmail_link": f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"
            })

        return jsonify({"emails": email_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/emails/summarize", methods=["POST"])
def api_summarize_email():
    data = request.get_json() or {}
    subject = data.get("subject", "No Subject")
    body = data.get("body", "")

    if not body.strip():
        msg_id = data.get("id")
        if msg_id:
            try:
                service = get_gmail_service()
                msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
                body = get_email_body(msg) or msg.get("snippet", "")
            except Exception as e:
                return jsonify({"error": f"Failed to retrieve email: {e}"}), 500

    user_text = f"Subject: {subject}\n\nBody:\n{body[:3500]}"
    res = call_llm_json(SUMMARIZATION_PROMPT, user_text)

    summary_text = res.get("summary") or "Could not generate summary."
    key_points = res.get("key_points") or []

    return jsonify({
        "summary": summary_text,
        "key_points": key_points
    })

# --- Realtime Scan Stream ---
@app.route("/api/scan-stream")
def api_scan_stream():
    scope = request.args.get("scope", "5").lower()
    sort_by = request.args.get("sort", "criticalness")

    if scope == "today":
        max_results = 50
        query = "newer_than:1d -category:promotions -category:social -category:forums"
        scope_label = "today's inbox messages"
    elif scope == "3d":
        max_results = 50
        query = "newer_than:3d -category:promotions -category:social -category:forums"
        scope_label = "messages from the past 3 days"
    elif scope == "7d":
        max_results = 50
        query = "newer_than:7d -category:promotions -category:social -category:forums"
        scope_label = "messages from the past 7 days"
    else:
        try:
            max_results = max(1, min(int(scope), 50))
        except ValueError:
            max_results = 5
        query = "newer_than:14d -category:promotions -category:social -category:forums"
        scope_label = f"latest {max_results} messages"

    def generate():
        yield f"data: {json.dumps({'type': 'log', 'text': 'Connecting to Gmail...'})}\n\n"
        try:
            service = get_gmail_service()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Gmail error: {e}'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'log', 'text': f'Connected. Querying {scope_label}...'})}\n\n"
        try:
            res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Failed to query emails: {e}'})}\n\n"
            return

        messages = res.get("messages", [])
        if not messages:
            yield f"data: {json.dumps({'type': 'log', 'text': f'No emails found matching {scope_label}.'})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'log', 'text': f'Evaluating {len(messages)} message(s)...'})}\n\n"

        found_count = 0
        new_evaluated_count = 0
        for idx, m in enumerate(messages, 1):
            msg_id = m["id"]

            try:
                msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            except Exception:
                continue

            headers = msg.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
            sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")
            date_str = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
            body = get_email_body(msg) or msg.get("snippet", "")
            gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

            if is_already_scanned(msg_id):
                yield f"data: {json.dumps({'type': 'log', 'text': f'[{idx}/{len(messages)}] \"{subject[:35]}\" -> Already processed'})}\n\n"
                continue

            new_evaluated_count += 1
            yield f"data: {json.dumps({'type': 'log', 'text': f'[{idx}/{len(messages)}] Analyzing: \"{subject[:35]}\"...'})}\n\n"

            try:
                parsed = extract_with_llm(subject, sender, body, email_date=date_str)
                if parsed.get("is_actionable") and parsed.get("action"):
                    parsed["msg_id"] = msg_id
                    parsed["source_subject"] = subject
                    parsed["source_sender"] = sender
                    parsed["gmail_link"] = gmail_link
                    store_todo(parsed)
                    record_scanned(msg_id, subject, "selected")
                    found_count += 1
                    due_info = parsed.get("date_time") or parsed.get("sort_date") or "No deadline"
                    task_action = parsed.get("action")
                    msg_text = f"    -> [TASK] {task_action} ({due_info})"
                    yield f"data: {json.dumps({'type': 'log', 'text': msg_text})}\n\n"
                else:
                    record_scanned(msg_id, subject, "skipped")
                    yield f"data: {json.dumps({'type': 'log', 'text': '    -> [SKIP] Non-actionable or marketing'})}\n\n"
            except Exception as item_err:
                yield f"data: {json.dumps({'type': 'log', 'text': f'    -> [ERROR] Failed analyzing item: {item_err}'})}\n\n"

            time.sleep(0.05)

        # Run Consequence Reasoning across active items
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT id, action, date_time, category, source_subject, source_type FROM todos WHERE status = 'open'")
        open_items = [{
            "id": r[0],
            "action": r[1],
            "date_time": r[2],
            "category": r[3],
            "source_subject": r[4],
            "source_type": r[5] or "email"
        } for r in c.fetchall()]
        conn.close()

        if len(open_items) >= 2:
            yield f"data: {json.dumps({'type': 'log', 'text': 'Analyzing dependencies and upcoming conflicts...'})}\n\n"
            consequence_alert = run_consequence_analysis(open_items)
            if consequence_alert.get("has_conflict"):
                save_consequence_alert(consequence_alert)
                alert_title_txt = consequence_alert.get("alert_title", "")
                yield f"data: {json.dumps({'type': 'log', 'text': f'    -> Conflict: {alert_title_txt}'})}\n\n"
            else:
                save_consequence_alert({"has_conflict": False, "alert_title": None, "alert_explanation": None, "top_priority_action": None})
        else:
            save_consequence_alert({"has_conflict": False, "alert_title": None, "alert_explanation": None, "top_priority_action": None})

        recalculate_priorities()
        yield f"data: {json.dumps({'type': 'done', 'found_count': found_count, 'todos': get_todos(sort_by=sort_by), 'consequence_alert': get_consequence_alert()})}\n\n"

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response

if __name__ == "__main__":
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"\nLIFELOCKER running on http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
