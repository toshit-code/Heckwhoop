#!/usr/bin/env python3
"""
Gmail to To-Do List Engine (Powered by Google Gemini 3.8 Flash)
Fast, stable CLI that scans your Gmail inbox and generates an actionable to-do list.
"""

import os
import sys
import json
import base64
import re
from datetime import datetime, timezone
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env.local"))
load_dotenv(os.path.join(BASE_DIR, ".env"))

TOKEN_FILE = os.path.join(BASE_DIR, "user_token.json")
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
TODO_MD_FILE = os.path.join(BASE_DIR, "TODO.md")
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

SYSTEM_PROMPT = """You are an email intelligence assistant. Your job is to extract actionable tasks, deadlines, and to-do items from a user's incoming emails.

Determine if the email contains an actionable to-do or deadline for the user.
Actionable items include:
- Direct tasks or requests to reply, review, submit, or sign
- Submissions, registrations, forms to fill, contests, or project deadlines
- Meeting/interview dates or events the user needs to attend
- Payment due dates, fee deadlines, or expiration dates

Exclusions (is_actionable: false):
- Pure receipts for already completed purchases
- One-time passwords (OTP), 2FA codes, automated security login alerts
- Generic social media conversation activity notifications (e.g. Slack digests) unless calling out an explicit personal task

Return valid JSON without markdown:
{
  "is_actionable": true | false,
  "action": "clear, concise task description (e.g. Submit project before deadline)",
  "deadline_phrase": "exact phrase from email like 'by October 31' or null",
  "deadline_date": "YYYY-MM-DD or null",
  "category": "work | project | finance | academic | event | personal",
  "consequence_if_ignored": "impact if missed, or null",
  "source_quote": "relevant sentence from email"
}
"""

GEMINI_MODELS = ["gemini-3.8-flash", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash"]


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
            print("\n" + "=" * 60)
            print("🔑 Starting Gmail Authentication...")
            print("Please log in with your Google account when prompted.")
            print("=" * 60 + "\n")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
        print(f"✅ Credentials saved to {TOKEN_FILE}!\n")

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


def parse_json_safely(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    return None


def extract_action_with_gemini(subject, sender, body):
    user_prompt = f"Subject: {subject}\nFrom: {sender}\nBody:\n{body[:3500]}"
    api_key = os.getenv("GEMINI_API_KEY")

    if api_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            for model in GEMINI_MODELS:
                try:
                    resp = client.models.generate_content(
                        model=model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            temperature=0.1
                        )
                    )
                    if resp.text:
                        parsed = parse_json_safely(resp.text)
                        if parsed:
                            return parsed
                except Exception:
                    continue
        except Exception as e:
            print(f"[Notice] Gemini error: {e}")

    # Fallback to Groq if configured
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            gclient = Groq(api_key=groq_key)
            comp = gclient.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            parsed = parse_json_safely(comp.choices[0].message.content)
            if parsed:
                return parsed
        except Exception:
            pass

    return {"is_actionable": False}


def update_todo_markdown(todos):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 📬 Gmail Actionable To-Do List",
        f"> *Last synced: {now_str} via Google Gemini 3.8 Flash*",
        "",
        "## Pending Tasks",
        ""
    ]

    if not todos:
        lines.append("- *No pending actionable tasks found in recent emails.*")
    else:
        for t in todos:
            due = f" **(Due: {t.get('deadline_date') or t.get('deadline_phrase')})**" if t.get('deadline_date') or t.get('deadline_phrase') else ""
            consequence = f"\n  > ⚠️ *Impact:* {t['consequence_if_ignored']}" if t.get('consequence_if_ignored') else ""
            link = f"\n  > 🔗 [Open Email in Gmail]({t['gmail_link']})" if t.get('gmail_link') else ""
            lines.append(f"- [ ] **{t['action']}** [{t['category'].upper()}]{due}{consequence}{link}\n")

    with open(TODO_MD_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    max_emails = 12
    if len(sys.argv) > 1:
        try:
            max_emails = int(sys.argv[1])
        except ValueError:
            pass

    print("\n" + "=" * 60)
    print("🚀 GMAIL INBOX TO-DO LIST (Gemini 3.8 Flash)")
    print("=" * 60)
    print(f"📥 Scanning last {max_emails} emails from your inbox...\n")

    try:
        service = get_gmail_service()
    except Exception as e:
        print(f"❌ Failed to connect to Gmail: {e}")
        return

    query = "newer_than:14d -category:promotions -category:social -category:forums"
    results = service.users().messages().list(userId="me", q=query, maxResults=max_emails).execute()
    messages = results.get("messages", [])

    if not messages:
        print("No recent unread messages found.")
        return

    extracted_todos = []

    for idx, msg_meta in enumerate(messages, 1):
        msg_id = msg_meta["id"]
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        headers = msg.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")
        body = get_email_body(msg)
        gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

        # Clean snippet if body empty
        if not body.strip():
            body = msg.get("snippet", "")

        analysis = extract_action_with_gemini(subject, sender, body)

        if analysis.get("is_actionable") and analysis.get("action"):
            analysis["source_subject"] = subject
            analysis["source_sender"] = sender
            analysis["gmail_link"] = gmail_link
            extracted_todos.append(analysis)
            print(f"[{idx}/{len(messages)}] 🎯 TASK FOUND: {analysis['action']}")
            if analysis.get("deadline_date"):
                print(f"       📅 Due: {analysis['deadline_date']}")
            if analysis.get("consequence_if_ignored"):
                print(f"       ⚠️  Impact: {analysis['consequence_if_ignored']}")
            print()
        else:
            print(f"[{idx}/{len(messages)}] ⏭️  Skipped: {subject[:45]}...")

    print("\n" + "=" * 60)
    print(f"✨ SUMMARY: Found {len(extracted_todos)} Actionable To-Do Items")
    print("=" * 60)

    if extracted_todos:
        for i, t in enumerate(extracted_todos, 1):
            deadline_str = f" [Due: {t.get('deadline_date') or t.get('deadline_phrase')}]" if (t.get('deadline_date') or t.get('deadline_phrase')) else ""
            print(f"\n{i}. 📌 {t['action']}{deadline_str}")
            print(f"   Category: {t.get('category', 'personal').upper()}")
            if t.get("consequence_if_ignored"):
                print(f"   Consequence: {t['consequence_if_ignored']}")
            print(f"   Link: {t['gmail_link']}")
    else:
        print("Your inbox is clear! No urgent pending tasks detected.")

    update_todo_markdown(extracted_todos)
    print(f"\n📝 Saved formatted checklist to: {TODO_MD_FILE}\n")


if __name__ == "__main__":
    main()
