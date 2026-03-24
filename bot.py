"""Telegram bot entrypoint for Shadow Stress MVP."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, TypedDict

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ai_engine import (
    clean_response,
    generate_hr_advice,
    generate_session_summary,
    get_ai_response,
    parse_meta,
)
from config import (
    ANTHROPIC_API_KEY,
    REPORT_INTERVAL_DAYS,
    SESSION_TIMEOUT,
    TELEGRAM_TOKEN,
)
from db import (
    bind_chat_to_user,
    company_exists,
    create_user,
    get_all_companies,
    get_company,
    get_company_stats,
    get_personal_stats,
    get_user_by_chat_id,
    get_user_history_context,
    logout_user,
    save_session,
    user_exists,
    validate_credential,
    verify_user,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

REG_COMPANY, REG_LOGIN, REG_PASSWORD = range(3)
AUTH_COMPANY, AUTH_LOGIN, AUTH_PASSWORD = range(3, 6)

UNKNOWN_META_VALUES = {"", "unknown"}


class SessionState(TypedDict):
    """In-memory state for one active chat session."""

    started_at: datetime
    last_activity: datetime
    conversation: list[dict[str, Any]]
    message_count: int
    meta: dict[str, str]


active_sessions: dict[int, SessionState] = {}


def _returning_user_text() -> str:
    """Build message for already authorized users."""
    return (
        "Welcome back.\n\n"
        "Tell me what is happening, and I will help you break it down.\n\n"
        "Commands:\n"
        "/stats - your personal statistics\n"
        "/end - end current session\n"
        "/logout - sign out\n"
        "/help - quick help"
    )


def _registration_success_text() -> str:
    """Build message after successful registration."""
    return (
        "Account created successfully.\n\n"
        "Send a message whenever you need support.\n\n"
        "/stats - personal statistics\n"
        "/end - end current session\n"
        "/logout - sign out\n"
        "/help - quick help"
    )


def _format_metric_block(
    title: str,
    data: dict[str, int],
    *,
    limit: int | None = None,
    with_percentage: bool = False,
) -> str:
    """Render a formatted section for counters in stats/report messages."""
    if not data:
        return ""

    items = list(data.items())
    if limit is not None:
        items = items[:limit]

    lines = [f"{title}:"]
    total = sum(data.values()) if with_percentage else 0
    for label, count in items:
        if with_percentage and total > 0:
            pct = round(count / total * 100)
            lines.append(f"  {label}: {pct}% ({count})")
        else:
            lines.append(f"  {label}: {count}")

    return "\n".join(lines) + "\n\n"


def _is_meaningful_meta(value: str) -> bool:
    """Return True for metadata values that are not placeholders."""
    return value.strip() not in UNKNOWN_META_VALUES


def _build_initial_session() -> SessionState:
    """Create initial in-memory session state."""
    now = datetime.now()
    return {
        "started_at": now,
        "last_activity": now,
        "conversation": [],
        "message_count": 0,
        "meta": {},
    }


# /start registration flow


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start registration flow or greet returning user."""
    if not update.effective_chat or not update.message:
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    user = get_user_by_chat_id(chat_id)

    if user:
        company_code = user.get("company")
        if company_code and company_exists(company_code):
            await update.message.reply_text(_returning_user_text())
            return ConversationHandler.END
        logout_user(chat_id)

    await update.message.reply_text(
        "Shadow Stress is a workplace stress-support tool.\n\n"
        "Everything is anonymous. Team leads only receive aggregated statistics.\n\n"
        "Enter your company code:"
    )
    return REG_COMPANY


async def reg_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate company code during registration."""
    if not update.message:
        return REG_COMPANY

    code = update.message.text.strip().lower()
    if not company_exists(code):
        await update.message.reply_text("Company not found. Please check the code with your team lead:")
        return REG_COMPANY

    company = get_company(code)
    context.user_data["reg_company"] = code
    await update.message.reply_text(
        f"Company: {company['name']}\n\n"
        "Create a login (one word, no spaces):"
    )
    return REG_LOGIN


async def reg_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collect and validate login during registration."""
    if not update.message:
        return REG_LOGIN

    login = update.message.text.strip()
    company_code = context.user_data.get("reg_company", "")

    error = validate_credential(login)
    if error:
        await update.message.reply_text(f"{error} Try again:")
        return REG_LOGIN

    if user_exists(login, company_code):
        await update.message.reply_text("This login is already taken. Choose another one:")
        return REG_LOGIN

    context.user_data["reg_login"] = login
    await update.message.reply_text("Create a password (one word, minimum 3 characters):")
    return REG_PASSWORD


async def reg_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finalize registration by creating user account."""
    if not update.message or not update.effective_chat:
        return ConversationHandler.END

    password = update.message.text.strip()
    chat_id = update.effective_chat.id

    error = validate_credential(password)
    if error:
        await update.message.reply_text(f"{error} Try again:")
        return REG_PASSWORD

    login = context.user_data.get("reg_login", "")
    company_code = context.user_data.get("reg_company", "")
    create_user(login, password, chat_id, company_code)

    try:
        await update.message.delete()
    except Exception:
        pass

    await context.bot.send_message(chat_id=chat_id, text=_registration_success_text())
    return ConversationHandler.END


# /login flow


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start explicit login flow."""
    if update.message:
        await update.message.reply_text("Company code:")
    return AUTH_COMPANY


async def auth_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collect company code in login flow."""
    if not update.message:
        return AUTH_COMPANY

    code = update.message.text.strip().lower()
    if not company_exists(code):
        await update.message.reply_text("Company not found:")
        return AUTH_COMPANY

    context.user_data["auth_company"] = code
    await update.message.reply_text("Login:")
    return AUTH_LOGIN


async def auth_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collect login in login flow."""
    if not update.message:
        return AUTH_LOGIN

    context.user_data["auth_login"] = update.message.text.strip()
    await update.message.reply_text("Password:")
    return AUTH_PASSWORD


async def auth_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate credentials and bind current chat to account."""
    if not update.message or not update.effective_chat:
        return ConversationHandler.END

    password = update.message.text.strip()
    login = context.user_data.get("auth_login", "")
    company_code = context.user_data.get("auth_company", "")
    chat_id = update.effective_chat.id

    try:
        await update.message.delete()
    except Exception:
        pass

    if verify_user(login, password, company_code):
        bind_chat_to_user(login, company_code, chat_id)
        await context.bot.send_message(chat_id=chat_id, text="Login successful. Tell me what is happening.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Invalid credentials. Use /login to try again.")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel active conversation handler."""
    if update.message:
        await update.message.reply_text("Canceled.")
    return ConversationHandler.END


# /logout


async def logout_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logout user and clear active in-memory session if present."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    if active_sessions.pop(chat_id, None):
        for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
            job.schedule_removal()

    if logout_user(chat_id):
        await update.message.reply_text(
            "You are logged out.\n\n"
            "/start - register again\n"
            "/login - sign into an existing account"
        )
    else:
        await update.message.reply_text("You are not authorized. Use /start")


# Message processing


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process regular user message in active support flow."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    user = get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("Please run /start first.")
        return

    company_code = user.get("company")
    if not company_code or not company_exists(company_code):
        await update.message.reply_text("Company not found. Use /logout and then /start again.")
        return

    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    session = active_sessions.get(chat_id)
    if session is None:
        session = _build_initial_session()
        active_sessions[chat_id] = session

    session["last_activity"] = datetime.now()
    session["message_count"] += 1

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        raw_response = get_ai_response(
            user_message=user_text,
            conversation_history=session["conversation"],
            user_history=get_user_history_context(chat_id),
        )

        meta = parse_meta(raw_response)
        session["meta"].update({k: v for k, v in meta.items() if _is_meaningful_meta(v)})
        session["conversation"].append({"role": "user", "content": user_text})
        session["conversation"].append({"role": "assistant", "content": raw_response})

        await update.message.reply_text(clean_response(raw_response))

        job_name = f"timeout_{chat_id}"
        for job in context.job_queue.get_jobs_by_name(job_name):
            job.schedule_removal()
        context.job_queue.run_once(
            session_timeout_callback,
            when=SESSION_TIMEOUT,
            data=chat_id,
            name=job_name,
        )

    except Exception as exc:
        logger.error("AI error for %s: %s", chat_id, exc)
        await update.message.reply_text("Technical error. Please try again.")


async def session_timeout_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-close inactive session after timeout."""
    chat_id = context.job.data
    await _end_session(chat_id, context, auto=True)


async def _end_session(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    auto: bool = False,
) -> None:
    """Persist and close active session."""
    session = active_sessions.pop(chat_id, None)
    if not session or session["message_count"] == 0:
        if not auto:
            await context.bot.send_message(chat_id=chat_id, text="No active session.")
        return

    session_data = {
        "trigger": session["meta"].get("trigger", "unknown"),
        "category": session["meta"].get("category", "unknown"),
        "technique": session["meta"].get("technique", "unknown"),
        "message_count": session["message_count"],
        "summary": "",
    }

    if session["message_count"] >= 2:
        try:
            session_data["summary"] = generate_session_summary(
                session["conversation"],
                get_user_history_context(chat_id),
            )
        except Exception as exc:
            logger.error("Summary error: %s", exc)

    save_session(chat_id, session_data)
    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()

    msg = "Session closed."
    if not auto:
        msg += " Data saved."
    msg += "\n\n/stats - personal statistics"
    await context.bot.send_message(chat_id=chat_id, text=msg)


# Commands


async def end_session_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """End active session manually by user command."""
    if not update.effective_chat:
        return
    await _end_session(update.effective_chat.id, context, auto=False)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show personal aggregated statistics for current user."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id
    user = get_user_by_chat_id(chat_id)
    if not user:
        await update.message.reply_text("Use /start to register.")
        return

    stats = get_personal_stats(chat_id)
    if stats["total"] == 0:
        await update.message.reply_text("No data yet. It will appear after your first session.")
        return

    text = f"Personal statistics\n{'=' * 30}\n\n"
    text += f"Total sessions: {stats['total']}\n\n"
    text += _format_metric_block("Categories", stats.get("categories", {}), with_percentage=True)
    text += _format_metric_block("Triggers", stats.get("triggers", {}), limit=5)
    text += _format_metric_block("Techniques", stats.get("techniques", {}))

    await update.message.reply_text(text.rstrip())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show short usage help."""
    if not update.message:
        return

    await update.message.reply_text(
        "Shadow Stress - help\n"
        f"{'=' * 30}\n\n"
        "Just describe what is happening.\n\n"
        "/stats - personal statistics\n"
        "/end - end current session\n"
        "/logout - sign out\n"
        "/help - this message\n\n"
        "Sessions auto-close after 20 minutes of inactivity.\n"
        "All data is anonymous."
    )


async def hr_report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate and send company-level HR report to allowed HR chat IDs."""
    if not update.effective_chat or not update.message:
        return

    chat_id = update.effective_chat.id

    companies = get_all_companies()
    user_company: str | None = None
    for code, data in companies.items():
        if data.get("hr_chat_id") == chat_id:
            user_company = code
            break

    if not user_company:
        await update.message.reply_text("This command is available only to company HR/team lead.")
        return

    company = get_company(user_company)
    stats = get_company_stats(user_company)

    if stats["total_sessions"] == 0:
        await update.message.reply_text(f"Report for {company['name']}: no data yet.")
        return

    text = "SHADOW STRESS REPORT\n"
    text += f"Company: {company['name']}\n{'=' * 30}\n\n"
    text += f"Registered users: {stats['total_users']}\n"
    text += f"Active users: {stats['active_users']}\n"
    text += f"Support sessions: {stats['total_sessions']}\n\n"
    text += _format_metric_block(
        "Top issue categories",
        stats.get("categories", {}),
        limit=7,
        with_percentage=True,
    )
    text += _format_metric_block("Top triggers", stats.get("triggers", {}), limit=5)

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        advice = generate_hr_advice(stats)
        text += f"Recommendations:\n{advice}\n"
    except Exception as exc:
        logger.error("HR advice error: %s", exc)

    text += f"\n{'=' * 30}\nAll data is anonymous."
    await context.bot.send_message(chat_id=chat_id, text=text)


# App bootstrap


def main() -> None:
    """Run Telegram polling application."""
    if not TELEGRAM_TOKEN:
        print("Error: TELEGRAM_TOKEN is not set")
        return
    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY is not set")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            REG_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_company)],
            REG_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_login)],
            REG_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    auth_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            AUTH_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_company)],
            AUTH_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_login)],
            AUTH_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(reg_handler)
    app.add_handler(auth_handler)
    app.add_handler(CommandHandler("logout", logout_cmd))
    app.add_handler(CommandHandler("end", end_session_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("hr", hr_report_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(
        lambda ctx: None,
        interval=timedelta(days=REPORT_INTERVAL_DAYS),
        first=timedelta(hours=1),
    )

    print("Shadow Stress started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
