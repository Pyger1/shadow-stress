"""Data storage helpers for Shadow Stress."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from config import COMPANIES_DB, DATA_DIR, SESSIONS_DB, USERS_DB

JsonDict = dict[str, Any]
CounterMap = dict[str, int]

UNKNOWN_TRIGGER = "unknown"
UNKNOWN_CATEGORY = "unknown"
UNKNOWN_TECHNIQUE = "unknown"
UNKNOWN_BUCKET = "other"


def _ensure_dirs() -> None:
    """Create local data directory if it does not exist yet."""
    Path(DATA_DIR).mkdir(exist_ok=True)


def _load(path: str) -> JsonDict:
    """Load JSON from disk, returning an empty dict for missing files."""
    _ensure_dirs()
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _save(path: str, data: JsonDict) -> None:
    """Persist JSON to disk with readable formatting."""
    _ensure_dirs()
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with per-user salt."""
    secure_salt = salt or secrets.token_hex(16)
    hashed = hashlib.sha256((secure_salt + password).encode()).hexdigest()
    return hashed, secure_salt


def _build_user_key(company_code: str, login: str) -> str:
    """Build a stable user key for user storage."""
    return f"{company_code.lower()}:{login}"


def _increment_counter(counter: CounterMap, key: str) -> None:
    """Increment simple string-key counter."""
    counter[key] = counter.get(key, 0) + 1


def validate_credential(value: str) -> str | None:
    """Validate login/password shape: one token, 3-30 chars."""
    normalized = value.strip() if value else ""
    if not normalized:
        return "This field cannot be empty."
    if " " in normalized:
        return "Use one word only, without spaces."
    if len(normalized) < 3:
        return "Minimum length is 3 characters."
    if len(normalized) > 30:
        return "Maximum length is 30 characters."
    if not re.match(r"^[a-zA-Z0-9_\-]+$", normalized):
        return "Only letters, digits, underscore and hyphen are allowed."
    return None


# Companies


def company_exists(company_code: str) -> bool:
    """Return True when company code is registered."""
    companies = _load(COMPANIES_DB)
    return company_code.lower() in companies


def get_company(company_code: str) -> JsonDict | None:
    """Fetch company by code."""
    companies = _load(COMPANIES_DB)
    return companies.get(company_code.lower())


def get_all_companies() -> JsonDict:
    """Return full companies map."""
    return _load(COMPANIES_DB)


# Users


def user_exists(login: str, company_code: str) -> bool:
    """Check whether login is already used inside company namespace."""
    users = _load(USERS_DB)
    key = _build_user_key(company_code, login)
    return key in users


def create_user(login: str, password: str, chat_id: int, company_code: str) -> bool:
    """Create a new user with anonymous identifier."""
    users = _load(USERS_DB)
    key = _build_user_key(company_code, login)
    if key in users:
        return False

    hashed, salt = _hash_password(password)
    users[key] = {
        "password_hash": hashed,
        "salt": salt,
        "chat_id": chat_id,
        "company": company_code.lower(),
        "anon_id": secrets.token_hex(4),
        "created_at": datetime.now().isoformat(),
        "session_count": 0,
    }
    _save(USERS_DB, users)
    return True


def verify_user(login: str, password: str, company_code: str) -> bool:
    """Validate credentials against stored password hash."""
    users = _load(USERS_DB)
    key = _build_user_key(company_code, login)
    user = users.get(key)
    if not user:
        return False

    hashed, _ = _hash_password(password, user["salt"])
    return hashed == user["password_hash"]


def bind_chat_to_user(login: str, company_code: str, chat_id: int) -> bool:
    """Attach Telegram chat id to an existing user after successful login."""
    users = _load(USERS_DB)
    key = _build_user_key(company_code, login)
    user = users.get(key)
    if not user:
        return False

    user["chat_id"] = chat_id
    _save(USERS_DB, users)
    return True


def get_user_by_chat_id(chat_id: int) -> JsonDict | None:
    """Find user record by Telegram chat id."""
    users = _load(USERS_DB)
    for key, data in users.items():
        if data.get("chat_id") == chat_id:
            login = key.split(":", 1)[1] if ":" in key else key
            return {"login": login, **data}
    return None


def get_anon_id(chat_id: int) -> str | None:
    """Get anonymous user id for a chat id."""
    user = get_user_by_chat_id(chat_id)
    return user["anon_id"] if user else None


def get_user_company(chat_id: int) -> str | None:
    """Get company code for a chat id."""
    user = get_user_by_chat_id(chat_id)
    return user.get("company") if user else None


def logout_user(chat_id: int) -> bool:
    """Unbind chat id from user account."""
    users = _load(USERS_DB)
    for _, data in users.items():
        if data.get("chat_id") == chat_id:
            data["chat_id"] = None
            _save(USERS_DB, users)
            return True
    return False


def increment_session_count(chat_id: int) -> None:
    """Increment stored session counter for user linked to chat id."""
    users = _load(USERS_DB)
    for _, data in users.items():
        if data.get("chat_id") == chat_id:
            data["session_count"] = data.get("session_count", 0) + 1
            _save(USERS_DB, users)
            return


# Sessions


def save_session(chat_id: int, session_data: JsonDict) -> None:
    """Persist single completed chat session for anonymized analytics."""
    sessions = _load(SESSIONS_DB)
    anon_id = get_anon_id(chat_id)
    company = get_user_company(chat_id)
    if not anon_id:
        return

    sessions.setdefault(anon_id, [])
    sessions[anon_id].append(
        {
            "timestamp": datetime.now().isoformat(),
            "company": company or "unknown",
            "trigger": session_data.get("trigger", UNKNOWN_TRIGGER),
            "category": session_data.get("category", UNKNOWN_CATEGORY),
            "technique_used": session_data.get("technique", UNKNOWN_TECHNIQUE),
            "message_count": session_data.get("message_count", 0),
            "summary": session_data.get("summary", ""),
        }
    )

    _save(SESSIONS_DB, sessions)
    increment_session_count(chat_id)


def get_user_sessions(chat_id: int) -> list[JsonDict]:
    """Return all stored sessions for user linked to chat id."""
    sessions = _load(SESSIONS_DB)
    anon_id = get_anon_id(chat_id)
    if not anon_id:
        return []
    return sessions.get(anon_id, [])


def get_user_history_context(chat_id: int) -> str:
    """Build compact context from previous sessions for LLM prompt."""
    past = get_user_sessions(chat_id)
    if not past:
        return "First session. No prior history."

    lines: list[str] = []
    for i, session in enumerate(past[-5:], 1):
        lines.append(
            (
                f"Session {i}: trigger={session['trigger']}, "
                f"category={session['category']}, "
                f"technique={session['technique_used']}"
            )
        )
    return "\n".join(lines)


# Aggregated statistics


def get_company_stats(company_code: str) -> JsonDict:
    """Compute aggregated statistics for one company."""
    sessions = _load(SESSIONS_DB)
    users = _load(USERS_DB)
    code = company_code.lower()

    total_users = sum(1 for user in users.values() if user.get("company") == code)
    total_sessions = 0
    active_users = 0
    categories: CounterMap = {}
    triggers: CounterMap = {}
    techniques: CounterMap = {}

    for user_sessions in sessions.values():
        company_sessions = [s for s in user_sessions if s.get("company") == code]
        if not company_sessions:
            continue

        active_users += 1
        total_sessions += len(company_sessions)
        for session in company_sessions:
            _increment_counter(categories, session.get("category", UNKNOWN_BUCKET))
            _increment_counter(triggers, session.get("trigger", UNKNOWN_BUCKET))
            _increment_counter(techniques, session.get("technique_used", UNKNOWN_BUCKET))

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_sessions": total_sessions,
        "categories": dict(sorted(categories.items(), key=lambda x: -x[1])),
        "triggers": dict(sorted(triggers.items(), key=lambda x: -x[1])),
        "techniques": dict(sorted(techniques.items(), key=lambda x: -x[1])),
    }


def get_personal_stats(chat_id: int) -> JsonDict:
    """Compute personal statistics for one user."""
    sessions_list = get_user_sessions(chat_id)
    if not sessions_list:
        return {"total": 0}

    categories: CounterMap = {}
    triggers: CounterMap = {}
    techniques: CounterMap = {}

    for session in sessions_list:
        _increment_counter(categories, session.get("category", UNKNOWN_BUCKET))
        _increment_counter(triggers, session.get("trigger", UNKNOWN_BUCKET))
        _increment_counter(techniques, session.get("technique_used", UNKNOWN_BUCKET))

    return {
        "total": len(sessions_list),
        "categories": categories,
        "triggers": triggers,
        "techniques": techniques,
        "last_session": sessions_list[-1].get("timestamp"),
    }
