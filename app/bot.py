import re
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from . import config, crud, models
from .db import SessionLocal
from .format import format_money
from .salary import describe_payout_type

router = Router()

EXPENSE_RE = re.compile(r"^[−\-–]\s*(\d[\d\s]*)\s*(.*)$")
KNOWN_CATEGORIES = ["еда", "транспорт", "жильё", "жилье", "кредит", "здоровье", "развлечения", "подписки"]


def _webapp_keyboard() -> InlineKeyboardMarkup | None:
    if not config.WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=config.WEBAPP_URL))]
        ]
    )


@router.message(CommandStart())
async def on_start(message: Message) -> None:
    db = SessionLocal()
    try:
        user = crud.get_or_create_user(db, message.from_user.id)
        user.started_bot = True
        db.commit()
    finally:
        db.close()

    text = (
        "Привет! Это трекер смен и денег.\n\n"
        "Открывай приложение кнопкой ниже — там календарь смен, авансы/зарплата, "
        "траты, прогноз баланса и копилки-цели.\n\n"
        "Трату можно записать прямо сюда сообщением: <code>-3500 еда</code> — "
        "сразу спишется со свободного баланса.\n\n"
        "25-го и 10-го напомню про выплату, а по понедельникам пришлю разбор недели."
    )
    await message.answer(text, reply_markup=_webapp_keyboard())


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer(
        "/start — открыть приложение и включить напоминания.\n"
        "Трата сообщением: <code>-3500 еда</code> или <code>-12000 кредит</code>."
    )


def _parse_expense(text: str) -> tuple[int, str, str] | None:
    """Parses `-3500 еда обед` -> (3500, category, note). Returns None if not an expense."""
    m = EXPENSE_RE.match((text or "").strip())
    if not m:
        return None
    amount = int(re.sub(r"\s+", "", m.group(1)))
    if amount <= 0:
        return None
    rest = (m.group(2) or "").strip()
    if not rest:
        return amount, "", ""
    first, _, tail = rest.partition(" ")
    if first.lower() in KNOWN_CATEGORIES:
        category = "Жильё" if first.lower() in ("жильё", "жилье") else first.capitalize()
        return amount, category, tail.strip()
    return amount, "Другое", rest


@router.message(F.text.regexp(r"^[−\-–]\s*\d"))
async def on_expense_message(message: Message) -> None:
    parsed = _parse_expense(message.text or "")
    if parsed is None:
        return
    amount, category, note = parsed
    db = SessionLocal()
    try:
        user = crud.get_or_create_user(db, message.from_user.id)
        user.started_bot = True
        crud.add_expense(db, user, amount, category, note, None)
        balance = user.unallocated_balance
        db.commit()
    except ValueError as exc:
        await message.answer(str(exc))
        return
    finally:
        db.close()
    label = f"{category}" + (f" · {note}" if note else "")
    await message.answer(
        f"Записал трату {format_money(amount)}" + (f" ({label})" if label else "") + f".\nСвободно осталось: {format_money(balance)}."
    )


def create_bot() -> Bot:
    return Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def send_reminders(bot: Bot) -> int:
    """Runs once/day off an external trigger (see .github/workflows).
    Only actually messages anyone on the 10th/25th, with today's real amount."""
    today = config.today()
    if today.day not in (10, 25):
        return 0

    db = SessionLocal()
    sent = 0
    try:
        users = db.query(models.User).filter(models.User.started_bot.is_(True)).all()
        for user in users:
            event = crud.next_payout_event(user)
            if event.date != today.isoformat():
                continue
            text = (
                f"Сегодня {today.day}-е — {describe_payout_type(event.type)}, "
                f"расчётная сумма {format_money(event.calculated_amount)}.\n"
                "Отметь в приложении, сколько пришло по факту."
            )
            try:
                await bot.send_message(chat_id=user.telegram_id, text=text)
                sent += 1
            except TelegramForbiddenError:
                user.started_bot = False
        db.commit()
    finally:
        db.close()
    return sent


def weekly_digest_text(user: models.User, today=None) -> str | None:
    """Monday разбор: траты за 7 дней, темп, отставание от целей, что делать."""
    from . import salary as salary_module

    today = today or config.today()
    week_start = today - timedelta(days=7)
    week_key = week_start.isoformat()
    week_expenses = [e for e in user.expenses if e.spent_at >= week_key]
    week_total = sum(e.amount for e in week_expenses)
    if not week_expenses and not user.goals:
        return None
    daily = week_total / 7
    lines = [f"Разбор недели · {format_money(week_total)} потрачено за 7 дней ({format_money(daily)}/день)."]
    if week_expenses:
        by_cat: dict[str, float] = {}
        for e in week_expenses:
            by_cat[e.category or "Другое"] = by_cat.get(e.category or "Другое", 0) + e.amount
        top = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)[:3]
        lines.append("Куда ушло: " + ", ".join(f"{k} — {format_money(v)}" for k, v in top) + ".")
    behind = []
    for g in user.goals:
        proj = crud.goal_projection(g)
        if not proj.reached and proj.on_track is False and proj.required_monthly:
            behind.append((g.name, proj.required_monthly, proj.pace_monthly))
    if behind:
        name, need, pace = behind[0]
        gap = max(need - pace, 0)
        lines.append(
            f"«{name}» отстаёт: нужно {format_money(need)}/мес, темп {format_money(pace)}/мес. "
            f"Чтобы вернуться в график — плюс {format_money(gap)}/мес: одна допсмена или минус столько из трат."
        )
    else:
        lines.append("Цели в графике — так держать.")
    event = crud.next_payout_event(user)
    lines.append(
        f"До выплаты ({describe_payout_type(event.type).lower()} {event.date}): свободно {format_money(user.unallocated_balance)}."
    )
    _ = salary_module  # keep import explicit for future pace tweaks
    return "\n".join(lines)


async def send_weekly_digest(bot: Bot) -> int:
    """Runs on Mondays off an external trigger; skips quiet users with no activity."""
    db = SessionLocal()
    sent = 0
    try:
        users = db.query(models.User).filter(models.User.started_bot.is_(True)).all()
        for user in users:
            text = weekly_digest_text(user)
            if text is None:
                continue
            try:
                await bot.send_message(chat_id=user.telegram_id, text=text)
                sent += 1
            except TelegramForbiddenError:
                user.started_bot = False
        db.commit()
    finally:
        db.close()
    return sent
