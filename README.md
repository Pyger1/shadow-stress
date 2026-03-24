# Shadow Stress

Shadow Stress is a Telegram assistant for workplace stress support.
It helps employees unpack a difficult situation, get one practical regulation technique, and keep sessions anonymous for internal trend analysis.

This repository contains an MVP that was built to validate three things:
- people are willing to ask for support in chat,
- practical short responses work better than long theory,
- HR teams benefit from aggregated stress-pattern signals.

## What It Does

- Anonymous employee onboarding (`company code -> login -> password`)
- Guided stress-support chat powered by Anthropic Claude Haiku
- Per-session metadata extraction (`trigger`, `category`, `technique`)
- Session auto-close after inactivity timeout
- Personal stats via `/stats`
- Company-level HR report via `/hr` (only for configured HR chat IDs)

## Tech Stack

- Python 3.12
- `python-telegram-bot` (async handlers + job queue)
- Anthropic API (`claude-haiku-4-5-20251001`)
- Lightweight JSON storage (no external DB required)
- Docker

## Project Structure

```text
shadow-stress/
  bot.py              # Telegram handlers, session lifecycle, command routing
  ai_engine.py        # Claude integration, response cleanup, metadata parsing
  db.py               # JSON persistence for companies/users/sessions/stats
  config.py           # environment-based config and constants
  data/
    companies.json    # company registry + hr_chat_id mapping
  requirements.txt
  Dockerfile
```

## Quick Start

### 1. Create a Telegram bot

1. Open `@BotFather`
2. Run `/newbot`
3. Copy the bot token
4. Disable Group Privacy in bot settings (if needed)

### 2. Get Anthropic API key

1. Open [console.anthropic.com](https://console.anthropic.com)
2. Create an API key

### 3. Configure environment

Copy and fill `.env` in project root:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
ANTHROPIC_API_KEY=your_anthropic_api_key
ADMIN_CHAT_ID=optional_admin_chat_id
```

```bash
cp .env.example .env
```

### 4. Install and run

```bash
pip install -r requirements.txt
export $(cat .env | xargs)
python bot.py
```

## Docker

```bash
docker build -t shadow-stress .
docker run --env-file .env shadow-stress
```

## Bot Commands

| Command | Who can use | Purpose |
|---|---|---|
| `/start` | everyone | Register or continue as an existing user |
| `/login` | everyone | Login from another device/chat |
| `/logout` | everyone | Disconnect current chat session |
| `/stats` | authorized users | View personal aggregated stats |
| `/end` | authorized users | End active session manually |
| `/help` | everyone | Show quick usage guide |
| `/hr` | configured HR chat IDs | Show aggregated company report |

## Data Model and Privacy

- Each user gets an `anon_id`
- Session stats are linked to `anon_id`, not real identity
- HR report contains only aggregated numbers
- Conversation content is not included in HR output
- Data is stored in local JSON files under `data/`

> Important: this MVP uses local files and simple auth logic. For production use, add encrypted storage, hardened auth, and stricter access controls.

## Portfolio Context

Shadow Stress is one of my portfolio projects focused on practical AI in real organizational workflows.
The core idea is simple: move from generic “feel better” chatbot responses to concise, situation-aware, actionable support that people can apply immediately.
