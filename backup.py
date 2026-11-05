import asyncio
import glob
import os
import sqlite3
import time

from aiogram.types import FSInputFile

import config


def _copy(dst):
    src = sqlite3.connect(config.DB_PATH)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close()
    src.close()


async def loop(bot):
    """Раз в BACKUP_HOURS часов делает копию базы (хранит 7 последних) и присылает её первому админу."""
    if config.BACKUP_HOURS <= 0:
        return
    folder = os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)), "backups")
    os.makedirs(folder, exist_ok=True)
    interval = config.BACKUP_HOURS * 3600
    while True:
        files = sorted(glob.glob(os.path.join(folder, "bot-*.db")))
        age = time.time() - os.path.getmtime(files[-1]) if files else interval
        await asyncio.sleep(max(0, interval - age))
        try:
            path = os.path.join(folder, time.strftime("bot-%Y%m%d-%H%M.db"))
            await asyncio.to_thread(_copy, path)
            if config.BACKUP_SEND and config.ADMIN_IDS:
                try:
                    await bot.send_document(sorted(config.ADMIN_IDS)[0], FSInputFile(path),
                                            caption="💾 Резервная копия базы")
                except Exception:
                    pass
            for old in sorted(glob.glob(os.path.join(folder, "bot-*.db")))[:-7]:
                os.remove(old)
        except Exception:
            pass
        await asyncio.sleep(5)
