#!/usr/bin/env python3
"""
LIFELOCKER Database Reset Utility
Use this script to clear processed email history so you can re-test inbox scans multiple times.

Usage:
  python reset_db.py              # Interactive prompt / standard reset
  python reset_db.py --emails     # Clears scanned email cache & email tasks (keeps manual tasks)
  python reset_db.py --cache      # Only clears scanned email cache (allows re-scanning)
  python reset_db.py --all        # Complete factory reset (clears all tasks & cache)
"""

import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "todos.db")

def get_counts(conn):
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM scanned_messages")
    scanned_count = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM todos WHERE source_type = 'email'")
    email_todos = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM todos WHERE source_type = 'manual'")
    manual_todos = c.fetchone()[0]

    return scanned_count, email_todos, manual_todos

def reset_cache_only(conn):
    c = conn.cursor()
    c.execute("DELETE FROM scanned_messages")
    conn.commit()
    print("✔ Cleared scanned_messages table (All emails can now be re-evaluated).")

def reset_emails_and_cache(conn):
    c = conn.cursor()
    c.execute("DELETE FROM scanned_messages")
    c.execute("DELETE FROM todos WHERE source_type = 'email'")
    c.execute("DELETE FROM system_state WHERE key = 'consequence_alert'")
    conn.commit()
    print("✔ Cleared scanned email cache.")
    print("✔ Cleared extracted email tasks (Ready for a fresh full inbox scan).")
    print("✔ Preserved all your manual custom tasks.")

def reset_all(conn):
    c = conn.cursor()
    c.execute("DELETE FROM scanned_messages")
    c.execute("DELETE FROM todos")
    c.execute("DELETE FROM system_state")
    conn.commit()
    print("✔ Complete factory reset: all tasks, cache, and alerts cleared.")

def main():
    if not os.path.exists(DB_FILE):
        print(f"[!] Database file not found at: {DB_FILE}")
        return

    conn = sqlite3.connect(DB_FILE)
    scanned_count, email_todos, manual_todos = get_counts(conn)

    print("=" * 60)
    print("           LIFELOCKER DATABASE RESET TOOL")
    print("=" * 60)
    print(f"Current State in {os.path.basename(DB_FILE)}:")
    print(f"  - Scanned emails recorded:  {scanned_count}")
    print(f"  - Email tasks in to-do list: {email_todos}")
    print(f"  - Manual user tasks:         {manual_todos}")
    print("-" * 60)

    # Check CLI arguments
    if "--all" in sys.argv:
        reset_all(conn)
        conn.close()
        return
    elif "--cache" in sys.argv:
        reset_cache_only(conn)
        conn.close()
        return
    elif "--emails" in sys.argv:
        reset_emails_and_cache(conn)
        conn.close()
        return

    # If running interactively
    if sys.stdin.isatty():
        print("Choose an option:")
        print("  [1] Reset scan cache & email tasks (Recommended for re-testing demo emails)")
        print("  [2] Reset scan cache only (Keep current tasks, but re-evaluate emails)")
        print("  [3] Complete factory reset (Wipe everything)")
        print("  [Q] Cancel")
        choice = input("\nEnter choice [1/2/3/Q] (default 1): ").strip().lower()

        if choice in ("", "1"):
            reset_emails_and_cache(conn)
        elif choice == "2":
            reset_cache_only(conn)
        elif choice == "3":
            reset_all(conn)
        else:
            print("Cancelled. No changes made.")
    else:
        # Default automated mode
        reset_emails_and_cache(conn)

    conn.close()
    print("\nDone! Start your Flask app and click 'Scan Inbox' to re-test.")

if __name__ == "__main__":
    main()
