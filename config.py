"""Runtime configuration for Shadow Stress."""

import os

TELEGRAM_TOKEN: str = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
MODEL: str = "claude-haiku-4-5-20251001"
SESSION_TIMEOUT: int = 20 * 60
ADMIN_CHAT_ID: str = os.getenv("ADMIN_CHAT_ID", "")
REPORT_INTERVAL_DAYS: int = 3
MAX_CONTEXT_MESSAGES: int = 12

DATA_DIR: str = "data"
USERS_DB: str = f"{DATA_DIR}/users.json"
SESSIONS_DB: str = f"{DATA_DIR}/sessions.json"
COMPANIES_DB: str = f"{DATA_DIR}/companies.json"
