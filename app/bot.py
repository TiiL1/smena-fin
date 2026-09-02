from aiogram import Bot, Dispatcher, Router
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
        "Привет! Это трекер смен и зарплаты.\n\n"
        "Открывай приложение кнопкой ниже — там календарь смен, авансы/зарплата "
        "и копилки-цели. Раз в день, 25-го и 10-го, буду сюда писать с напоминанием "
        "и расчётной суммой."
    )
    await message.answer(text, reply_markup=_webapp_keyboard())


@router.message(Command("help"))
async def on_help(message: Message) -> None:
    await message.answer("/start — открыть приложение и включить напоминания 25-го/10-го числа.")


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
