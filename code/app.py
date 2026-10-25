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

init_db()

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
EXTRACTION_PROMPT = """You are an email assistant for LIFELOCKER. Your goal is to extract personal to-dos, required forms, deadlines, appointments, and actionable opportunities from emails.

WHAT QUALIFIES AS ACTIONABLE (Set is_actionable: true):
1. Hackathons, Buildathons, Grants & Contests:
   - Requesting API credits, cloud tokens, or project sponsorships (e.g. fill Google form for credits)
   - Project submissions, demo filings, team registrations, deadline reminders
2. Required Forms & Applications:
   - Any email asking the user to fill out a Google Form, survey, application, or RSVP
3. Appointments & Schedule:
   - Dentist, doctor visits, interviews, team/client meetings with date or time
4. Travel & Bookings:
   - Flights, train/hotel reservations, passport/visa renewal deadlines
5. Real Deadlines & Dues:
   - Submissions, bills/invoices to pay, exam clearances, tuition/fee dues, contract signings

STRICT EXCLUSIONS (Set is_actionable: false):
- Pure commercial advertising & sales discounts (e.g. "Get 50% off summer collection", "Upgrade your ChatGPT Plus subscription")
- Routine SaaS product update announcements or automated Slack digests unless specifically requesting personal action
- Automated one-time passwords (OTP), 2FA codes, login security alerts
- Purchase receipts for transactions already completed

CRITICAL: If an email mentions filling a form to get credits for a hackathon, submitting a project, or attending an appointment, ALWAYS mark is_actionable: true.

ACTIONABLE LINKS:
If the email contains an actionable web link directly related to completing the task (such as a Google Form, billing/payment website, portal submission, registration, or appointment confirmation URL):
- Extract the exact URL as "action_url" (or null if none)
- Provide a concise, action-oriented button label as "action_url_text" (e.g. "Pay Now", "Fill Form", "Submit Project", "Confirm Slot", "More Info", etc., or null if none)

Return valid JSON without markdown:
{
  "is_actionable": true | false,
  "action": "clear, concise task description (e.g. Fill form to request Buildathon credits, Dentist Appointment)",
  "action_url": "https://... or null",
  "action_url_text": "short action text e.g. Pay Now, Fill Form, Confirm Slot or null",
  "date_time": "human readable date and time (e.g. by October 31, or Wednesday at 11:00 AM) or null",
  "sort_date": "YYYY-MM-DD or YYYY-MM-DDTHH:MM if time mentioned for chronological sorting, else null",
  "category": "hackathon | project | health | travel | legal | academic | work | finance | personal",
  "consequence": "specific real-world impact if missed or ignored",
  "source_quote": "relevant sentence from email"
}
"""

CONSEQUENCE_REASONING_PROMPT = """You are LIFELOCKER's consequence-reasoning intelligence.
Analyze the user's active tasks across their inbox emails AND custom user-created tasks.
Find HIDDEN CONFLICTS, CROSS-TASK PREREQUISITES, and DEPENDENCIES.

Example Patterns:
- Flight trip confirmed (e.g. Flight to USA in July) + Passport expiring or renewal needed ->
  Renewing passport MUST be elevated to TOP PRIORITY because renewal takes 4-8 weeks processing time. If not renewed in advance, the user CANNOT board the flight to USA!
- User manual task: 'Apply for Japan Tourist Visa' + Email flight booking: 'Flight to Tokyo on Feb 8' + Email reminder: 'Passport expires March 2027' ->
  Passport renewal must happen first before visa can be issued.
- Overdue bill + manual expense task -> Prioritize paying bill before cutoff/penalty.

Return valid JSON:
{
  "has_conflict": true | false,
  "alert_title": "short urgent warning (e.g. Renew Passport before USA flight) or null",
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

def extract_with_llm(subject, sender, body):
    # Immediate skip for automated security alerts and OTPs
    lower_subj = subject.lower()
    lower_sender = sender.lower()
    if "security alert" in lower_subj or "no-reply@accounts.google.com" in lower_sender:
        return {"is_actionable": False}

    user_prompt = f"Subject: {subject}\nFrom: {sender}\nBody:\n{body[:3500]}"
    res = call_llm_json(EXTRACTION_PROMPT, user_prompt)
    if res.get("is_actionable"):
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
    if not scanned:
        # Also check if it exists in todos by msg_id or gmail_link
        c.execute("SELECT 1 FROM todos WHERE msg_id = ? OR gmail_link LIKE ?", (msg_id, f"%{msg_id}%"))
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

def store_todo(item):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    msg_id = item.get('msg_id', '')
    gmail_link = item.get('gmail_link', '')

    # Check if this email was already stored as a todo
    if msg_id:
        c.execute("SELECT id FROM todos WHERE msg_id = ?", (msg_id,))
    elif gmail_link:
        c.execute("SELECT id FROM todos WHERE gmail_link = ?", (gmail_link,))
    else:
        c.execute("SELECT id FROM todos WHERE action = ? AND source_type = 'manual'", (item['action'],))
    existing = c.fetchone()

    if existing is None:
        c.execute("""
            INSERT INTO todos (
                msg_id, action, date_time, sort_date, category, consequence,
                source_subject, source_sender, source_quote, gmail_link,
                action_url, action_url_text, source_type, priority, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 10, 'open', ?)
        """, (
            msg_id,
            item['action'],
            item.get('date_time') or item.get('deadline_phrase') or '',
            item.get('sort_date') or item.get('deadline_date') or '9999-99-99',
            item.get('category', 'personal'),
            item.get('consequence', ''),
            item.get('source_subject', ''),
            item.get('source_sender', ''),
            item.get('source_quote', ''),
            gmail_link,
            item.get('action_url') or None,
            item.get('action_url_text') or None,
            item.get('source_type', 'email'),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
    conn.close()

def save_consequence_alert(alert):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO system_state (key, value) VALUES ('consequence_alert', ?)", (json.dumps(alert),))
    # Reset priorities to default 10 for open tasks first if no conflict or updating
    if not alert.get("has_conflict"):
        c.execute("UPDATE todos SET priority = 10 WHERE priority = 1")
    elif alert.get("top_priority_action"):
        top_name = alert["top_priority_action"]
        c.execute("UPDATE todos SET priority = 1 WHERE action LIKE ? AND status = 'open'", (f"%{top_name}%",))
    conn.commit()
    conn.close()

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

def get_todos():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, action, date_time, sort_date, category, consequence, source_subject, source_sender, source_quote, gmail_link, priority, status, action_url, action_url_text, source_type
        FROM todos
        WHERE status != 'skipped'
        ORDER BY
            status ASC,
            priority ASC,
            CASE WHEN sort_date IS NULL OR sort_date = '' OR sort_date = '9999-99-99' THEN 1 ELSE 0 END ASC,
            sort_date ASC,
            id DESC
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
    """Re-evaluates consequence reasoning for only open (unfinished) tasks (both email and user custom tasks)."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT id, action, date_time, category, source_subject, source_type
        FROM todos
        WHERE status = 'open'
    """)
    open_rows = c.fetchall()
    open_items = [{
        "id": r[0],
        "action": r[1],
        "date_time": r[2],
        "category": r[3],
        "source_subject": r[4],
        "source_type": r[5] or "email"
    } for r in open_rows]

    if len(open_items) < 2:
        # Less than 2 open tasks -> clear the conflict banner
        save_consequence_alert({"has_conflict": False, "alert_title": None, "alert_explanation": None, "top_priority_action": None})
    else:
        # Re-run consequence analysis on remaining open items
        new_alert = run_consequence_analysis(open_items)
        save_consequence_alert(new_alert)

# --- Flask Routes ---
@app.route("/")
def home():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.route("/api/todos")
def api_get_todos():
    return jsonify({
        "todos": get_todos(),
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

    # Re-evaluate consequence alert for remaining open tasks
    refresh_consequence_state()

    return jsonify({"ok": True, "todos": get_todos(), "consequence_alert": get_consequence_alert()})

@app.route("/api/todos/<int:todo_id>/skip", methods=["POST"])
def api_skip_todo(todo_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE todos SET status = 'skipped' WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()

    # Re-evaluate consequence alert for remaining open tasks
    refresh_consequence_state()

    return jsonify({"ok": True, "todos": get_todos(), "consequence_alert": get_consequence_alert()})

@app.route("/api/todos/<int:todo_id>", methods=["DELETE"])
def api_delete_todo(todo_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()

    refresh_consequence_state()
    return jsonify({"ok": True, "todos": get_todos(), "consequence_alert": get_consequence_alert()})

@app.route("/api/todos/manual", methods=["POST"])
def api_add_manual_todo():
    data = request.get_json() or {}
    action = (data.get("action") or "").strip()
    if not action:
        return jsonify({"error": "Task description is required"}), 400

    date_time = (data.get("date_time") or "").strip()
    category = (data.get("category") or "personal").strip()

    sort_date = "9999-99-99"
    if date_time:
        # Check for simple YYYY-MM-DD pattern
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", date_time)
        if match:
            sort_date = match.group(1)

    item = {
        "action": action,
        "date_time": date_time or None,
        "sort_date": sort_date,
        "category": category,
        "consequence": data.get("consequence", ""),
        "source_subject": "Personal To-Do",
        "source_sender": "User input",
        "source_quote": "",
        "gmail_link": "",
        "action_url": data.get("action_url") or None,
        "action_url_text": data.get("action_url_text") or None,
        "source_type": "manual"
    }

    store_todo(item)
    refresh_consequence_state()

    return jsonify({"ok": True, "todos": get_todos(), "consequence_alert": get_consequence_alert()})

@app.route("/api/rescan-reset", methods=["POST"])
def api_rescan_reset():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM scanned_messages")
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "Scanned message history cleared"})

# --- See Mails Endpoints ---
@app.route("/api/emails")
def api_get_emails():
    try:
        service = get_gmail_service()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        # If body is not in request, fetch from Gmail
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
    def generate():
        yield f"data: {json.dumps({'type': 'log', 'text': 'Connecting to Gmail...'})}\n\n"
        try:
            service = get_gmail_service()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Gmail error: {e}'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'log', 'text': 'Connected. Fetching top 5 inbox messages...'})}\n\n"
        query = "newer_than:14d -category:promotions -category:social -category:forums"
        try:
            res = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': f'Failed to query emails: {e}'})}\n\n"
            return

        messages = res.get("messages", [])
        yield f"data: {json.dumps({'type': 'log', 'text': f'Evaluating {len(messages)} recent messages (filtering ads & SaaS onboarding)...'})}\n\n"

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
            body = get_email_body(msg) or msg.get("snippet", "")
            gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

            # Check if already scanned / read
            if is_already_scanned(msg_id):
                yield f"data: {json.dumps({'type': 'log', 'text': f'[{idx}/{len(messages)}] \"{subject[:35]}\" -> Already processed (skipping)'})}\n\n"
                continue

            new_evaluated_count += 1
            yield f"data: {json.dumps({'type': 'log', 'text': f'[{idx}/{len(messages)}] Analyzing new email: \"{subject[:35]}\"...'})}\n\n"

            try:
                parsed = extract_with_llm(subject, sender, body)
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
                    msg_text = f"    -> [SELECT] {task_action} ({due_info})"
                    yield f"data: {json.dumps({'type': 'log', 'text': msg_text})}\n\n"
                else:
                    record_scanned(msg_id, subject, "skipped")
                    yield f"data: {json.dumps({'type': 'log', 'text': '    -> [SKIP] (marketing ad, routine setup, or non-actionable)'})}\n\n"
            except Exception as item_err:
                yield f"data: {json.dumps({'type': 'log', 'text': f'    -> [ERROR] Failed analyzing item: {item_err}'})}\n\n"

            time.sleep(0.05)

        # Run Consequence Reasoning across all active (open) items (both email & custom tasks)
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
            yield f"data: {json.dumps({'type': 'log', 'text': 'Running consequence reasoning for cross-email & custom task conflicts/dependencies...'})}\n\n"
            consequence_alert = run_consequence_analysis(open_items)
            if consequence_alert.get("has_conflict"):
                save_consequence_alert(consequence_alert)
                alert_title_txt = consequence_alert.get("alert_title", "")
                yield f"data: {json.dumps({'type': 'log', 'text': f'    -> ⚠️ CONFLICT: {alert_title_txt}'})}\n\n"
            else:
                save_consequence_alert({"has_conflict": False, "alert_title": None, "alert_explanation": None, "top_priority_action": None})
        else:
            save_consequence_alert({"has_conflict": False, "alert_title": None, "alert_explanation": None, "top_priority_action": None})

        yield f"data: {json.dumps({'type': 'done', 'found_count': found_count, 'todos': get_todos(), 'consequence_alert': get_consequence_alert()})}\n\n"

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"\nLIFELOCKER running on http://127.0.0.1:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
