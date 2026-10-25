# LifeLocker — AI-Powered Personal Email Memory Vault

> **"Your entire inbox, finally understood."**  
> LifeLocker is a personal email intelligence platform that connects securely to your Gmail account and uses local Google Gemma 4 AI to extract dates, deadlines, job offers, payment amounts, and crucial links buried inside emails — with zero cloud data leaks.

---

## 🌟 Key Features

1. **Smart Natural Language Search**
   - Search by plain English queries:
     - *"Find emails mentioning me."*
     - *"Find emails from my college about examinations."*
     - *"Find the email containing my internship offer."*
     - *"Search for messages mentioning a payment deadline."*
     - *"Find the email where someone shared a website with me."*
     - *"Find emails about my project from last month."*
   - Automatic translation into native Gmail search filters (`from:`, `subject:`, `after:`, `has:attachment`).
   - Relevance ranking grounded in textual evidence.

2. **100% Local AI Intelligence (Google Gemma 4)**
   - Connects to your local Ollama server (`http://127.0.0.1:11434/api/chat`).
   - Structured JSON analysis: summaries, key takeaways, people, organizations, dates, deadlines, amounts, and action items.
   - Built-in prompt injection defense: emails are strictly treated as untrusted data.
   - Deterministic grounded fallback engine ensuring full functionality even if Ollama is temporarily offline.

3. **Accessible Color-Coded Email Highlighting**
   - 🟨 **Yellow**: Key facts and status updates
   - 🟦 **Cyan**: Websites, portals, and URLs
   - 🟪 **Purple**: People and organization names
   - 🟥 **Red**: Urgent deadlines and dates
   - 🟩 **Green**: Payment amounts, fee balances, and confirmations

4. **"Links Found in My Inbox" Catalog**
   - Automatically extracts and deduplicates all URLs and web links across messages.
   - Shows surrounding sentence context and source email.
   - Heuristic security analyzer flags raw IP addresses and suspicious TLDs with safety warning modals before opening.

5. **Saved Memories (Personal Knowledge Vault)**
   - Pin important facts, milestones, flight bookings, and compensation details as reference notes.
   - Tags, categorization, editing, and one-click JSON export.
   - Deep links directly back to the original Gmail message.

6. **Enterprise-Grade Privacy & Security**
   - **Zero Cloud AI Leakage**: Email bodies are NEVER sent to third-party AI APIs.
   - **AES-256-GCM Token Encryption**: OAuth refresh and access tokens encrypted at rest.
   - **Least-Privilege Scopes**: Read-only `gmail.readonly` scope; cannot send or delete emails.
   - **HTML Email Sanitizer**: Blocks XSS, `<iframe>`, `<script>`, and tracking pixels.

---

## 🚀 Quick Start Guide (Windows)

### Prerequisites

- **Node.js**: v20+ or v24+ (Node 24 tested with native `node:sqlite`)
- **Git**: Installed
- **Ollama** (for local Gemma 4): [https://ollama.ai](https://ollama.ai)

---

### Step 1: Clone and Install Dependencies

```powershell
cd d:\antigravity\pojects\lifelocker
npm install
```

---

### Step 2: Configure Environment Variables

Copy `.env.example` to `.env.local`:

```powershell
Copy-Item .env.example .env.local
```

Edit `.env.local` to configure your keys:

```env
# Application URL
NEXT_PUBLIC_APP_URL=http://localhost:3000

# Cryptographic secret for signing sessions and AES-256-GCM token encryption
SESSION_SECRET=your_secure_random_32_byte_secret_key_here

# Local Ollama AI settings
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4

# Google OAuth 2.0 Credentials (Optional for instant Demo Mode)
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REDIRECT_URI=http://localhost:3000/api/auth/callback
```

---

### Step 3: Set Up Local Google Gemma 4 via Ollama

1. Install Ollama from [ollama.ai](https://ollama.ai).
2. Open PowerShell and pull Gemma 4:
   ```powershell
   ollama run gemma4
   ```
   *(For lower-resource PCs, you can use `ollama run gemma2:2b` and set `OLLAMA_MODEL=gemma2:2b`)*
3. Verify Ollama is running at `http://127.0.0.1:11434`.

---

### Step 4: Configure Google Cloud Console (For Real Gmail Access)

To connect your real Gmail mailbox:

1. Visit [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g. `LifeLocker`).
3. Navigate to **APIs & Services > Library** and enable **Gmail API**.
4. Navigate to **APIs & Services > OAuth consent screen**:
   - Choose **External** (or Internal for Google Workspace).
   - Add scope: `https://www.googleapis.com/auth/gmail.readonly`.
   - Add your test Google account email under **Test users**.
5. Navigate to **APIs & Services > Credentials > Create Credentials > OAuth client ID**:
   - Application type: **Web application**
   - Name: `LifeLocker Web Client`
   - Authorized JavaScript origins: `http://localhost:3000`
   - Authorized redirect URIs: `http://localhost:3000/api/auth/callback`
6. Copy the **Client ID** and **Client Secret** into your `.env.local`.

> 💡 **No credentials yet?** No problem! Click **"Launch Demo Sandbox"** on the landing page or sign-in page to immediately test the entire application with realistic simulated Gmail data.

---

### Step 5: Run the Automated Verification Suite

Run the 21 built-in unit and integration tests:

```powershell
npm test
```

Expected output:
```
======================================================
   LIFELOCKER PRODUCTION VERIFICATION TEST SUITE
======================================================
--- 1. Security & HTML Sanitizer Tests ---
  ✓ strips dangerous <script> tags from email HTML
  ✓ blocks malicious onload/onclick inline handlers
  ✓ drops 1x1 or 0x0 tracking pixels
  ✓ forces rel="noopener noreferrer nofollow" and target="_blank" on links
  ✓ converts HTML into clean plain text
--- 2. Natural Language Query Translation Tests ---
  ✓ translates internship offer queries correctly
  ✓ translates examination queries correctly
  ✓ translates payment deadline queries correctly
  ✓ translates shared website queries correctly
--- 3. Gemma 4 AI Schema Validation Tests ---
  ✓ validates valid AI JSON schema
  ✓ extractAndValidateJson cleans markdown fences and conversational LLM text
--- 4. Link Extraction & Safety Analysis Tests ---
  ✓ extracts deduplicated links from email text
  ✓ identifies raw IP address links as suspicious
  ✓ identifies spam top-level domains as suspicious
  ✓ marks trusted standard domains as safe
--- 5. AES-256-GCM Encryption Tests ---
  ✓ encrypts and decrypts OAuth tokens accurately
  ✓ detects tampered ciphertext
  ✓ redacts sensitive tokens from log outputs
--- 6. SQLite Database Persistence Tests ---
  ✓ creates, retrieves, updates, and deletes saved memory notes
  ✓ logs and clears search history items in SQLite
--- 7. Mock Mailbox Verification Tests ---
  ✓ provides realistic mock emails for all required query scenarios
======================================================
   TEST RESULTS: 21/21 PASSED
======================================================
```

---

### Step 6: Start the Development Server

```powershell
npm run dev
```

Open your browser at: **[http://localhost:3000](http://localhost:3000)**

---

## 🏗️ Architecture & Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                       LifeLocker UI                         │
│   Next.js 16 + React 19 + Tailwind CSS + Framer Motion      │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
               │ HTTPS (OAuth 2.0 SSL)        │ HTTP JSON (127.0.0.1:11434)
               ▼                              ▼
  ┌───────────────────────────┐  ┌────────────────────────────┐
  │     Google Gmail API      │  │     Local Ollama Engine    │
  │  (Fetch messages/queries) │  │  (Google Gemma 4 LLM)      │
  │   Read-only least-priv    │  │   Zero cloud AI leak       │
  └───────────────────────────┘  └────────────────────────────┘
               │
               ▼
  ┌───────────────────────────────────────────────────────────┐
  │             Local Storage & Security Layer                │
  │  - AES-256-GCM Token Encryption                           │
  │  - Strict HTML Email Sanitizer (XSS & Pixel Defense)     │
  │  - Persistent SQLite Database (data/lifelocker.db)        │
  │  - Saved Memories & Search Audit Log                      │
  └───────────────────────────────────────────────────────────┘
```

---

## 🛠️ Troubleshooting & FAQs

### 1. "Ollama is not running at 127.0.0.1:11434"
- Start the Ollama service:
  ```powershell
  ollama serve
  ```
- In another terminal, verify the model is pulled:
  ```powershell
  ollama list
  ```
- If you don't have Gemma 4, run `ollama pull gemma4`.
- LifeLocker automatically falls back to grounded heuristic extraction if Ollama is temporarily offline, ensuring uninterrupted use.

### 2. "Google OAuth redirect_uri_mismatch"
- Ensure that the redirect URI in your Google Cloud Console **exactly** matches:
  `http://localhost:3000/api/auth/callback`

### 3. "How do I wipe all local data?"
- Navigate to **Settings > Danger Zone** and click **"Wipe All Local LifeLocker Data"**.
- This will revoke sessions, delete your SQLite notes, and reset all stored preferences.

---

## 🔒 Security Statement

- LifeLocker only requests the `https://www.googleapis.com/auth/gmail.readonly` scope.
- It will **never** send, delete, or alter any emails.
- Email contents are analyzed **strictly locally on your computer**. No email text is sent to third-party cloud AI vendors.
