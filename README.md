# LIFELOCKER

> **Autonomous Email Intelligence & Consequence Reasoning Engine**  
> Built for Heckwhoop 2026. Converts noisy Gmail inboxes into a prioritized, actionable command center.

---

## The Problem

Every day, people receive dozens of emails: fee notices, hackathon team forms, flight confirmations, and appointment reminders.
- **Traditional To-Do Apps (Todoist, Notion):** Completely manual. You have to read the email, figure out the date yourself, switch tabs, type out the task, and set the reminder.
- **Generic AI Chatbots (ChatGPT, Copilot):** Only read emails one-by-one in isolation. They summarize what happened, but they don't understand dependencies, resolve relative calendar dates, or enforce accountability.
- **The Result:** Missed deadlines, late fees, and blind-spot disasters (e.g. booking an international flight while forgetting your passport renewal takes 4 weeks).

---

## The Solution: What Makes LifeLocker Different?

LifeLocker shifts AI from **passive summarization** to **proactive life defense**:

1. **Cross-Task Consequence Reasoning (Blind-Spot Detection):**  
   Cross-examines your entire inbox and personal tasks to identify hidden dependency conflicts. If you have an international flight to Tokyo on Dec 10 and an expiring passport notice, LifeLocker deduces that entry requires 6 months validity, recognizes renewal takes 3–4 weeks, warns you with an urgent amber conflict alert, and elevates the passport renewal to **Priority 1**.

2. **Temporal Grounding & Fuzzy Date Resolution:**  
   When emails mention relative dates (*"by Friday at 6:00 PM"*, *"next Wednesday at 2:30 PM"*, *"tomorrow at 5 PM"*), LifeLocker grounds the model in today's live calendar reference and computes the exact real-world calendar timestamp (`YYYY-MM-DDTHH:MM`), backed by a Python fallback resolver.

3. **Actionable Link & Form Vault:**  
   Scrapes and isolates direct actionable URLs into high-visibility CTA buttons (e.g. `[Fill Form]`, `[Download Ticket]`, `[Pay Invoice]`) so you never have to hunt through long emails.

4. **1-Click Google Calendar Sync:**  
   Calculated dates and details automatically generate pre-filled Google Calendar event templates with zero manual typing.

5. **Obsidian Focus UI & Gemini Active State Glow:**  
   Designed with an ultra-dark obsidian void (`#030406`) for laser focus, animated Gemini-style conic-gradient border during scans, smooth hover elevation physics, and a built-in **Messages Tab** with sub-second AI summarization.

---

## Tech Architecture

```
[Gmail API (OAuth 2.0)] ──> [Stage 1: Smart Filter & Ingest]
                                      │
                                      ▼
[Gemini 3.8 Flash / Groq] ──> [Stage 2: Temporal Grounding & Date Calculation]
                                      │
                                      ▼
[SQLite State Machine]   ──> [Stage 3: Cross-Task Consequence Graph]
                                      │
                                      ▼
[Web UI / EventSource]   ──> [Stage 4: Dynamic Priority Engine & 1-Click Sync]
```

- **Backend:** Python Flask, Google OAuth 2.0, Gmail REST API
- **AI Models:** Google Gemini 3.8 Flash (primary) with Groq LLaMA (high-availability fallback)
- **Data & State:** SQLite (`todos.db`) with cached message tracking to eliminate redundant calls
- **Real-Time Streaming:** Server-Sent Events (SSE) streaming token logs to the terminal box
- **Frontend:** Vanilla HTML5, modern CSS3 (`@property`, conic-gradients, hardware-accelerated transforms), and ES6 JavaScript

---

## Getting Started

### 1. Prerequisites
- Python 3.10+
- Google Cloud OAuth credentials (`credentials.json`) with Gmail API enabled
- Gemini API key (`GEMINI_API_KEY`) and/or Groq API key (`GROQ_API_KEY`)

### 2. Setup
```bash
# Clone the repository
git clone https://github.com/toshit-code/Heckwhoop.git
cd Heckwhoop/code

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment
Create a `.env.local` file inside `code/`:
```env
GEMINI_API_KEY="your-gemini-api-key"
GROQ_API_KEY="your-groq-api-key"
```
Place your Google Cloud `credentials.json` inside `code/`.

### 4. Run the Engine
```bash
python app.py
```
Open **`http://localhost:5000`** in your browser.

---

## Utilities

- **Reset Scan Cache:**
  ```bash
  python reset_db.py --emails    # Clears scan cache and email tasks, keeps manual tasks
  python reset_db.py --all       # Complete factory reset
  ```
- **Send Demo Emails:**
  ```bash
  python send_demo_emails.py     # Dispatches the 3 official demo emails to test your setup
  ```

---

## License
MIT License.
