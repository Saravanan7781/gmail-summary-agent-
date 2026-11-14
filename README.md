# ⚡ Gmail Summary Agent (Powered by Groq LPUs)

An ultra-fast, intelligent Gmail executive assistant bot built with **Groq (Llama 3.3 70B Versatile)**, **Official Gmail API (OAuth 2.0)**, and **Telegram Bot**.

---

## 🌟 Key Features

- **⚡ Blazing Fast Inbox Summaries (`/summary` or `/digest`)**:
  Fetches recent unread emails, analyzes them with Groq's high-speed LPU inference, provides an executive overview, and categorizes messages:
  - 🔴 **URGENT**: Immediate reply or action required.
  - 🟡 **IMPORTANT**: Key account alerts, work items, bills.
  - 🔵 **UPDATES**: Status notifications and general updates.
  - ⚪ **NEWSLETTERS**: Concise TL;DRs of marketing and newsletters.
- **🎯 Action Item Extraction**: Automatically identifies deadlines and next steps required from you.
- **✉️ One-Click Actions (Inline Buttons)**:
  - `[✅ Mark as Read]`: Marks the email read in your Gmail inbox immediately.
  - `[✍️ Draft Reply]`: Uses Groq to draft a context-aware response and saves it in your Gmail Drafts folder.
  - `[📄 View Full Snippet]`: Expands full message preview directly in Telegram.
- **💬 Natural Language Inbox Q&A (`/ask` or direct message)**:
  Ask questions in plain English (e.g. *"Did I receive my flight tickets from United?"* or *"What did Alex say about tomorrow's schedule?"*).
- **🔎 Keyword & Query Search (`/search <query>`)**:
  Search your inbox using standard Gmail filters (e.g. `/search from:github`, `/search receipts`).
- **⏰ Scheduled Daily Briefings**:
  Automated morning or evening executive digests delivered to your Telegram chat at a configurable time (e.g., `08:30`).
- **🔒 Private & Secure**:
  Built-in user ID whitelisting ensures only authorized Telegram accounts can view or interact with your emails.

---

## 📂 Project Architecture

```
gmail-summary-agent/
├── .env.example              # Environment variables template
├── .gitignore                # Protects secrets, tokens & virtual environment
├── requirements.txt          # Python dependencies
├── credentials/
│   ├── credentials.json      # Your downloaded Google Cloud OAuth Client Secret (ignored by git)
│   └── token.json            # Auto-generated user token after first OAuth login (ignored by git)
├── src/
│   ├── config.py             # Configuration & environment loader
│   ├── gmail_service.py      # Gmail API integration (OAuth2, fetch, search, drafts, mark-read)
│   ├── groq_service.py       # Groq LPU integration (structured digest, Q&A, drafting)
│   ├── bot.py                # Telegram bot handlers & interactive inline keyboards
│   └── scheduler.py          # Scheduled daily morning digest job runner
└── main.py                   # Main application entrypoint
```

---

## 🚀 Setup Guide

### 1. Configure Python Environment

The virtual environment has already been set up in this repository. To activate it:

**On Windows (PowerShell):**
```powershell
cd C:\Users\ELCOT\gmail-summary-agent
.\.venv\Scripts\Activate.ps1
```

---

### 2. Configure Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, choose a name and username (e.g., `MyGmailAgent_bot`).
3. Copy the **HTTP API Bot Token** provided.
4. Next, find your own Telegram numeric User ID:
   - Search for [@userinfobot](https://t.me/userinfobot) on Telegram and send `/start`.
   - Copy your `Id` (e.g., `123456789`).

---

### 3. Configure Groq API Key

1. Go to [Groq Console](https://console.groq.com/keys).
2. Sign in and click **Create API Key**.
3. Copy your API key (starts with `gsk_...`).

---

### 4. Configure Google Gmail API (OAuth 2.0)

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `Gmail-Assistant`).
3. In the sidebar, navigate to **APIs & Services > Library**.
4. Search for **Gmail API** and click **Enable**.
5. Go to **APIs & Services > OAuth consent screen**:
   - Choose **External** (or Internal if using Google Workspace).
   - Fill in App Name (e.g., `Gmail Agent`) and your email.
   - In **Test users**, add your own Gmail address (this is required while the app is in Testing mode).
6. Go to **APIs & Services > Credentials**:
   - Click **Create Credentials > OAuth client ID**.
   - Application type: Select **Desktop app**.
   - Name: `Gmail Agent Desktop`.
   - Click **Create**.
7. Download the credentials JSON file.
8. Rename the downloaded file to `credentials.json` and place it in the `credentials/` folder:
   ```
   C:\Users\ELCOT\gmail-summary-agent\credentials\credentials.json
   ```

---

### 5. Configure `.env` File

Open [.env](file:///C:/Users/ELCOT/gmail-summary-agent/.env) and ensure your keys are set:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ALLOWED_TELEGRAM_USER_IDS=your_telegram_user_id

GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

GMAIL_CREDENTIALS_PATH=credentials/credentials.json
GMAIL_TOKEN_PATH=credentials/token.json

ENABLE_SCHEDULED_DIGEST=true
DAILY_DIGEST_TIME=08:30
DIGEST_CHAT_ID=your_telegram_user_id
```

---

### 6. One-Time Gmail Login

Run the authentication helper:

```powershell
python main.py --auth-only
```
*(Or double-click `auth.bat`)*

- A browser window will open automatically asking you to log in to your Google Account.
- If you see a *"Google hasn't verified this app"* warning screen, click **Advanced > Go to Gmail Agent (unsafe)** (this is standard for personal test apps).
- Grant the requested permissions (Read, Modify, and Compose drafts).
- Once completed, `credentials/token.json` will be saved automatically.

---

### 7. Run the Agent

Start the Telegram Bot:

```powershell
python main.py
```
*(Or double-click `run.bat`)*

Open Telegram, find your bot, and send `/start` or `/summary`!

---

## 💬 Bot Commands Cheatsheet

| Command | Description |
|---|---|
| `/summary` or `/digest` | Generates a lightning-fast AI executive briefing and prioritized list of unread emails. |
| `/unread [count]` | Quick list of unread message senders and subjects (e.g., `/unread 5`). |
| `/search <query>` | Search your Gmail inbox (e.g., `/search invoices`, `/search from:github`). |
| `/ask <question>` | Ask anything about your emails in plain English (e.g., `/ask Did I get the flight receipt?`). |
| `/status` | View system health, Groq model info, and scheduled digest settings. |
| *Direct text message* | Any normal text sent to the bot is automatically answered using relevant emails. |
