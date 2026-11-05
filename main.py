import asyncio
import html
import logging
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

import admin, backup, config, db, handlers, reminders

_last_error = {"t": 0.0}


async def main():
    logging.basicConfig(level=logging.INFO)
    await db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.outer_middleware(admin.BanMiddleware())
    dp.include_router(admin.router)
    dp.include_router(handlers.router)

    @dp.error()
    async def on_error(event: ErrorEvent):
        logging.error("Unhandled error", exc_info=event.exception)
        if time.time() - _last_error["t"] > 60:   # не чаще раза в минуту
            _last_error["t"] = time.time()
            e = event.exception
            text = f"⚠️ <b>Ошибка в боте</b>\n<code>{html.escape(f'{type(e).__name__}: {e}')[:800]}</code>"
            for aid in config.ADMIN_IDS:
                try:
                    await bot.send_message(aid, text)
                except Exception:
                    pass
        return True

    tasks = [asyncio.create_task(reminders.loop(bot)), asyncio.create_task(backup.loop(bot))]
    try:
        await dp.start_polling(bot)
    finally:
        for task in tasks:
            task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
