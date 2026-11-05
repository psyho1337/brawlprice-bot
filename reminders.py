import asyncio
import html
import time

import db
import keyboards as kb
from i18n import t


async def loop(bot):
    """Раз в 10 минут рассылает напоминания «пересчитать аккаунт»."""
    while True:
        try:
            for r in await db.due_reminders(time.time()):
                lang = (await db.get_user(r["user_id"]) or {"lang": "ru"})["lang"]
                try:
                    text = t(lang, "watch_msg").replace("%NAME%", html.escape(r["name"] or "?")).replace("%TAG%", r["tag"])
                    await bot.send_message(r["user_id"], text, reply_markup=kb.recalc_kb(lang, r["tag"]))
                except Exception:
                    pass
                await db.delete_reminder(r["id"])
        except Exception:
            pass
        await asyncio.sleep(600)
