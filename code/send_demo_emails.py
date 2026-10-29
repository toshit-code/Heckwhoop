#!/usr/bin/env python3
"""
LIFELOCKER Automated Demo Email Sender
Sends the 3 official demo emails directly to your Gmail inbox:
1. Urgent: Passport Expiration Notice
2. Flight Booking Confirmed: New Delhi (DEL) to Tokyo Narita (NRT) (with ticket PDF link)
3. Action Required: Submit Your Hackathon Team Form (Heckwhoop, with form link)
"""

import os
import sys
import base64
from email.mime.text import MIMEText

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
SEND_TOKEN_FILE = os.path.join(BASE_DIR, "send_token.json")
SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']

DEMO_EMAILS = [
    {
        "subject": "Urgent: Passport Expiration Notice",
        "sender_name": "Passport Services Division",
        "body": """Dear Toshit,

Our records indicate that your passport is approaching its final validity window and will expire in less than 45 days.

Standard passport renewal processing times currently take 3 to 4 weeks. Please apply for an online renewal as soon as possible to avoid emergency expedited fees or international travel disruptions.

Passport Processing Division
Ministry of External Affairs / Passport Seva"""
    },
    {
        "subject": "Flight Booking Confirmed: New Delhi (DEL) to Tokyo Narita (NRT)",
        "sender_name": "All Nippon Airways (ANA)",
        "body": """Hello Toshit,

Your flight from New Delhi to Tokyo Narita has been confirmed for December 10, 2026 at 11:15 PM.

Booking Reference: NH-98210
Passenger: Toshit
Seat: 14A (Economy Class)
Route: Indira Gandhi International (DEL) -> Tokyo Narita International (NRT)
Departure: December 10, 2026 at 11:15 PM

You can download and view your official e-ticket PDF boarding confirmation here:
https://ana-airways.com/tickets/NH98210.pdf

We look forward to welcoming you on board for your trip to Japan!

All Nippon Airways (ANA) Customer Reservations"""
    },
    {
        "subject": "Action Required: Submit Your Hackathon Team Form",
        "sender_name": "Heckwhoop 2026 Organizing Team",
        "body": """Hey Hacker,

Welcome to Heckwhoop 2026! To confirm your track and claim your cloud API credits, your team lead must fill out the official verification form by Friday at 6:00 PM:

https://forms.gle/heckwhoop-team-registration-2026

Teams that fail to submit by Friday will forfeit their cloud token allowance.

Happy hacking!
Heckwhoop Organizing Team"""
    }
]

def get_send_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(SEND_TOKEN_FILE) and os.path.getsize(SEND_TOKEN_FILE) > 0:
        try:
            creds = Credentials.from_authorized_user_file(SEND_TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print("\n" + "=" * 60)
            print("Authorizing Gmail to send demo emails...")
            print("A browser window will open. Please click 'Allow'.")
            print("=" * 60 + "\n")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        with open(SEND_TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def main():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"[!] credentials.json not found in {BASE_DIR}")
        return

    try:
        service = get_send_service()
        profile = service.users().getProfile(userId='me').execute()
        my_email = profile.get('emailAddress')
        print(f"\nConnected to Gmail: {my_email}")
        print("Sending 3 demo emails directly to your inbox...\n")

        for idx, item in enumerate(DEMO_EMAILS, 1):
            msg = MIMEText(item["body"], "plain", "utf-8")
            msg["to"] = my_email
            msg["from"] = f'{item["sender_name"]} <{my_email}>'
            msg["subject"] = item["subject"]

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent = service.users().messages().send(userId='me', body={'raw': raw}).execute()
            print(f"[{idx}/3] Sent: \"{item['subject']}\" (ID: {sent['id']})")

        print("\n" + "=" * 60)
        print("✔ ALL 3 DEMO EMAILS SENT SUCCESSFULLY TO YOUR INBOX!")
        print("  1. Urgent: Passport Expiration Notice")
        print("  2. Flight Booking Confirmed: New Delhi to Tokyo (with ticket PDF)")
        print("  3. Action Required: Submit Your Hackathon Team Form (Heckwhoop)")
        print("=" * 60)
        print("\nNext step: Open http://localhost:5000, click [Reset Cache], then [Scan Inbox].")

    except Exception as e:
        print(f"[!] Error sending demo emails: {e}")
        print("\nTip: If you prefer, you can also copy and paste the email text directly into Gmail.")

if __name__ == "__main__":
    main()
