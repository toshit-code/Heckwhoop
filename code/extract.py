import os
import json
import re
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from google import genai
from google.genai import types

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env.local"))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv("/home/toshibaba/lifelocker/.env")

SYSTEM_PROMPT = """You are an email intelligence agent that identifies tasks, deadlines, and actionable obligations from incoming emails to build a user to-do list.

Decide if the email contains an actionable to-do, deadline, or obligation for the user.
Actionable items include:
- Direct tasks or requests to reply, review, submit, or sign
- Submissions, registrations, forms to fill, contests, or project deadlines
- Meeting/interview dates or events the user needs to attend
- Payment due dates, fee deadlines, or expiration dates

Exclusions (is_actionable: false):
- Pure receipts for already completed purchases
- One-time passwords (OTP), 2FA codes, automated security login alerts
- Generic social media conversation activity notifications (e.g., Slack digests or updates) unless specifically calling out an urgent task directed at the user

Return valid JSON without markdown fences:
{
  "is_actionable": true,
  "action": "clear concise task description",
  "deadline_phrase": "phrase from email like 'by October 31' or null",
  "deadline_date": "YYYY-MM-DD or null",
  "category": "work | project | finance | academic | event | personal",
  "consequence_if_ignored": "impact or consequence if missed, or null",
  "source_quote": "relevant sentence from email"
}
"""

GEMINI_MODELS = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]


def safe_json_parse(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Model returned invalid JSON: {text[:300]}")


def extract_action(email_subject, email_body, sender, received_date=None):
    if received_date is None:
        received_date = datetime.now(timezone.utc)

    user_prompt = f"""Email received on: {received_date.strftime('%Y-%m-%d')}
From: {sender}
Subject: {email_subject}

Body:
{email_body[:3500]}
"""

    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        client = genai.Client(api_key=gemini_key)
        for model_name in GEMINI_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1,
                    )
                )
                if response.text:
                    return safe_json_parse(response.text)
            except Exception as e:
                continue

    # Fallback to Groq if available
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            gclient = Groq(api_key=groq_key)
            completion = gclient.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return safe_json_parse(completion.choices[0].message.content)
        except Exception:
            pass

    return {
        "is_actionable": False,
        "action": None,
        "deadline_phrase": None,
        "deadline_date": None,
        "category": "none",
        "consequence_if_ignored": None,
        "source_quote": ""
    }


if __name__ == "__main__":
    test_subj = "Urgent: Final Project Submission Required"
    test_body = "Hi Toshit, Please submit your final project report and Github repository link by October 28, 2026. Submissions received after this will be marked late."
    test_sender = "Professor Davis <faculty@university.edu>"
    res = extract_action(test_subj, test_body, test_sender)
    print(json.dumps(res, indent=2))
