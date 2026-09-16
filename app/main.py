import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import api, bot as bot_module, config
from .db import init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smena-fin")

bot = bot_module.create_bot() if config.BOT_TOKEN else None
dp = bot_module.create_dispatcher()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if bot and config.WEBAPP_URL:
        webhook_url = f"{config.WEBAPP_URL}/api/telegram/webhook"
        try:
            await bot.set_webhook(
                url=webhook_url,
                secret_token=config.TELEGRAM_WEBHOOK_SECRET or None,
                drop_pending_updates=True,
            )
            log.info("Telegram webhook set to %s", webhook_url)
        except Exception:
            log.exception("Could not set Telegram webhook (will keep serving the API/app anyway)")
    else:
        log.warning("BOT_TOKEN or WEBAPP_URL not set — bot features are disabled")
    yield
    if bot:
        await bot.session.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api.router)


@app.post("/api/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not bot:
        raise HTTPException(status_code=503, detail="Bot is not configured")
    if config.TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != config.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Bad secret token")
    update = Update.model_validate(await request.json())
    await dp.feed_update(bot=bot, update=update)
    return {"ok": True}


@app.post("/api/cron/reminders")
async def cron_reminders(token: str | None = None):
    if not config.CRON_SECRET or token != config.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Bad token")
    if not bot:
        raise HTTPException(status_code=503, detail="Bot is not configured")
    sent = await bot_module.send_reminders(bot)
    return {"sent": sent}


@app.post("/api/cron/weekly")
async def cron_weekly(token: str | None = None):
    if not config.CRON_SECRET or token != config.CRON_SECRET:
        raise HTTPException(status_code=401, detail="Bad token")
    if not bot:
        raise HTTPException(status_code=503, detail="Bot is not configured")
    sent = await bot_module.send_weekly_digest(bot)
    return {"sent": sent}


static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
