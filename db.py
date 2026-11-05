import aiosqlite
import config
from pricing import DEFAULT_PRICES

async def init():
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ru', currency TEXT DEFAULT 'RUB');
        CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tag TEXT, name TEXT,
            price_rub REAL, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value REAL);
        CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, tag TEXT, name TEXT,
            price_rub REAL, price_txt TEXT, league TEXT, skins TEXT, rare INTEGER, prot TEXT, mail TEXT,
            status TEXT DEFAULT 'new', manager_id INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS banned(user_id INTEGER PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS rare_items(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, price_rub REAL);
        CREATE TABLE IF NOT EXISTS proofs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER, file_id TEXT);
        CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, tag TEXT, name TEXT, due REAL);
        CREATE TABLE IF NOT EXISTS referrals(
            user_id INTEGER PRIMARY KEY, referrer_id INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS promos(code TEXT PRIMARY KEY, bonus_pct REAL, uses_left INTEGER);
        CREATE TABLE IF NOT EXISTS promo_uses(code TEXT, user_id INTEGER, PRIMARY KEY(code, user_id));
        """)
        for col, typ in (("ask_rub", "REAL"), ("ask_txt", "TEXT"), ("buy_rub", "REAL"), ("sell_rub", "REAL"),
                         ("updated", "TEXT"), ("snap_trophies", "INTEGER"), ("snap_brawlers", "INTEGER"),
                         ("rare_names", "TEXT")):
            try:
                await d.execute(f"ALTER TABLE leads ADD COLUMN {col} {typ}")
            except Exception:
                pass
        try:
            await d.execute("ALTER TABLE users ADD COLUMN bonus_pct REAL DEFAULT 0")
        except Exception:
            pass
        await d.execute("PRAGMA journal_mode=WAL")
        await d.commit()

async def get_user(uid):
    async with aiosqlite.connect(config.DB_PATH) as d:
        d.row_factory = aiosqlite.Row
        cur = await d.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        row = await cur.fetchone()
        return dict(row) if row else None

async def set_lang(uid, lang):
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.execute("INSERT INTO users(user_id, lang) VALUES(?,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET lang=excluded.lang", (uid, lang))
        await d.commit()

async def set_currency(uid, cur_code):
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.execute("INSERT INTO users(user_id, currency) VALUES(?,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET currency=excluded.currency", (uid, cur_code))
        await d.commit()

async def add_history(uid, tag, name, price_rub):
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.execute("INSERT INTO history(user_id, tag, name, price_rub) VALUES(?,?,?,?)",
                        (uid, tag, name, price_rub))
        await d.commit()

async def get_history(uid, limit=10):
    async with aiosqlite.connect(config.DB_PATH) as d:
        cur = await d.execute("SELECT tag, name, price_rub, created FROM history "
                              "WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
        return await cur.fetchall()

async def get_prices():
    prices = dict(DEFAULT_PRICES)
    async with aiosqlite.connect(config.DB_PATH) as d:
        cur = await d.execute("SELECT key, value FROM settings")
        for k, v in await cur.fetchall():
            if k in prices:
                prices[k] = v
    return prices

async def set_price(key, value):
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.execute("INSERT INTO settings(key, value) VALUES(?,?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        await d.commit()

async def stats():
    async with aiosqlite.connect(config.DB_PATH) as d:
        u = await (await d.execute("SELECT COUNT(*) FROM users")).fetchone()
        h = await (await d.execute("SELECT COUNT(*) FROM history")).fetchone()
        return u[0], h[0]

async def user_stats(uid):
    async with aiosqlite.connect(config.DB_PATH) as d:
        row = await (await d.execute(
            "SELECT COUNT(*), AVG(price_rub) FROM history WHERE user_id=?", (uid,))).fetchone()
        best = await (await d.execute(
            "SELECT name, price_rub FROM history WHERE user_id=? ORDER BY price_rub DESC LIMIT 1", (uid,))).fetchone()
        return row[0], row[1], best

async def reset_prices():
    async with aiosqlite.connect(config.DB_PATH) as d:
        await d.execute("DELETE FROM settings")
        await d.commit()


# ---------- заявки ----------
async def add_lead(**k):
    cols = ", ".join(k)
    async with aiosqlite.connect(config.DB_PATH) as c:
        cur = await c.execute(f"INSERT INTO leads({cols}) VALUES({','.join('?' * len(k))})", tuple(k.values()))
        await c.commit()
        return cur.lastrowid

async def get_lead(lid):
    async with aiosqlite.connect(config.DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        row = await (await c.execute("SELECT * FROM leads WHERE id=?", (lid,))).fetchone()
        return dict(row) if row else None

async def set_lead_status(lid, status, manager_id):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("UPDATE leads SET status=?, manager_id=?, updated=datetime('now') WHERE id=?", (status, manager_id, lid))
        await c.commit()

async def list_leads(status=None, limit=12):
    async with aiosqlite.connect(config.DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        if status:
            cur = await c.execute("SELECT * FROM leads WHERE status=? ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            cur = await c.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in await cur.fetchall()]

async def lead_counts():
    async with aiosqlite.connect(config.DB_PATH) as c:
        rows = await (await c.execute("SELECT status, COUNT(*) FROM leads GROUP BY status")).fetchall()
        return {s: n for s, n in rows}

# ---------- пользователи, баны, статистика ----------
async def all_user_ids():
    async with aiosqlite.connect(config.DB_PATH) as c:
        return [r[0] for r in await (await c.execute("SELECT user_id FROM users")).fetchall()]

async def set_banned(uid, flag):
    async with aiosqlite.connect(config.DB_PATH) as c:
        if flag:
            await c.execute("INSERT OR IGNORE INTO banned(user_id) VALUES(?)", (uid,))
        else:
            await c.execute("DELETE FROM banned WHERE user_id=?", (uid,))
        await c.commit()

async def is_banned(uid):
    async with aiosqlite.connect(config.DB_PATH) as c:
        return await (await c.execute("SELECT 1 FROM banned WHERE user_id=?", (uid,))).fetchone() is not None

async def stats_full():
    async with aiosqlite.connect(config.DB_PATH) as c:
        users = (await (await c.execute("SELECT COUNT(*) FROM users")).fetchone())[0]
        appr = (await (await c.execute("SELECT COUNT(*) FROM history")).fetchone())[0]
        today = (await (await c.execute(
            "SELECT COUNT(*) FROM history WHERE date(created)=date('now')")).fetchone())[0]
        banned = (await (await c.execute("SELECT COUNT(*) FROM banned")).fetchone())[0]
    return dict(users=users, appr=appr, today=today, banned=banned, leads=await lead_counts())

async def export_rows(table):
    assert table in ("history", "leads")
    async with aiosqlite.connect(config.DB_PATH) as c:
        cur = await c.execute(f"SELECT * FROM {table} ORDER BY id")
        cols = [x[0] for x in cur.description]
        return cols, await cur.fetchall()

# ---------- этап 1-3: редкое, скрины, сделки, напоминания ----------
async def add_rare(name, price):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("INSERT INTO rare_items(name, price_rub) VALUES(?,?)", (name, price))
        await c.commit()

async def list_rare():
    async with aiosqlite.connect(config.DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        return [dict(r) for r in await (await c.execute("SELECT * FROM rare_items ORDER BY id")).fetchall()]

async def get_rare_by_ids(ids):
    if not ids:
        return []
    async with aiosqlite.connect(config.DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        q = f"SELECT * FROM rare_items WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id"
        return [dict(r) for r in await (await c.execute(q, tuple(ids))).fetchall()]

async def set_rare_price(rid, price):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("UPDATE rare_items SET price_rub=? WHERE id=?", (price, rid))
        await c.commit()

async def del_rare(rid):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("DELETE FROM rare_items WHERE id=?", (rid,))
        await c.commit()

async def add_proof(lead_id, file_id):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("INSERT INTO proofs(lead_id, file_id) VALUES(?,?)", (lead_id, file_id))
        await c.commit()

async def count_proofs(lead_id):
    async with aiosqlite.connect(config.DB_PATH) as c:
        return (await (await c.execute("SELECT COUNT(*) FROM proofs WHERE lead_id=?", (lead_id,))).fetchone())[0]

async def set_lead_field(lid, **fields):
    sets = ", ".join(f"{k}=?" for k in fields)
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute(f"UPDATE leads SET {sets}, updated=datetime('now') WHERE id=?", (*fields.values(), lid))
        await c.commit()

async def percentile(price):
    async with aiosqlite.connect(config.DB_PATH) as c:
        below = (await (await c.execute("SELECT COUNT(*) FROM history WHERE price_rub < ?", (price,))).fetchone())[0]
        total = (await (await c.execute("SELECT COUNT(*) FROM history")).fetchone())[0]
        return below, total

async def last_for_tag(uid, tag):
    async with aiosqlite.connect(config.DB_PATH) as c:
        return await (await c.execute(
            "SELECT price_rub, created FROM history WHERE user_id=? AND tag=? ORDER BY id DESC LIMIT 1",
            (uid, tag))).fetchone()

async def add_reminder(uid, tag, name, due):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("INSERT INTO reminders(user_id, tag, name, due) VALUES(?,?,?,?)", (uid, tag, name, due))
        await c.commit()

async def due_reminders(now):
    async with aiosqlite.connect(config.DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        return [dict(r) for r in await (await c.execute("SELECT * FROM reminders WHERE due<=?", (now,))).fetchall()]

async def delete_reminder(rid):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("DELETE FROM reminders WHERE id=?", (rid,))
        await c.commit()

async def deals_stats(days=None):
    q = ("SELECT COUNT(*), COALESCE(SUM(buy_rub),0), COALESCE(SUM(sell_rub),0) FROM leads "
         "WHERE status='done' AND buy_rub IS NOT NULL AND sell_rub IS NOT NULL")
    if days:
        q += f" AND date(updated) >= date('now','-{int(days)} day')"
    async with aiosqlite.connect(config.DB_PATH) as c:
        return await (await c.execute(q)).fetchone()


# ---------- рефералка и промокоды ----------
async def add_referral(uid, ref):
    if uid == ref:
        return False
    async with aiosqlite.connect(config.DB_PATH) as c:
        if not await (await c.execute("SELECT 1 FROM users WHERE user_id=?", (ref,))).fetchone():
            return False
        cur = await c.execute("INSERT OR IGNORE INTO referrals(user_id, referrer_id) VALUES(?,?)", (uid, ref))
        await c.commit()
        return cur.rowcount > 0

async def ref_count(uid):
    async with aiosqlite.connect(config.DB_PATH) as c:
        return (await (await c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,))).fetchone())[0]

async def get_bonus(uid, per, cap):
    """Бонус к оценке в %: лучшее из промокода и реферального бонуса (не суммируются)."""
    async with aiosqlite.connect(config.DB_PATH) as c:
        row = await (await c.execute("SELECT bonus_pct FROM users WHERE user_id=?", (uid,))).fetchone()
        promo = row[0] if row and row[0] else 0
        n = (await (await c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id=?", (uid,))).fetchone())[0]
    return max(promo, min(n * per, cap))

async def use_promo(code, uid):
    async with aiosqlite.connect(config.DB_PATH) as c:
        row = await (await c.execute("SELECT bonus_pct, uses_left FROM promos WHERE code=?", (code,))).fetchone()
        if not row:
            return "none", 0
        if await (await c.execute("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, uid))).fetchone():
            return "used", 0
        if row[1] == 0:
            return "empty", 0
        await c.execute("INSERT INTO promo_uses(code, user_id) VALUES(?,?)", (code, uid))
        if row[1] > 0:
            await c.execute("UPDATE promos SET uses_left=uses_left-1 WHERE code=?", (code,))
        await c.execute("UPDATE users SET bonus_pct=MAX(COALESCE(bonus_pct,0), ?) WHERE user_id=?", (row[0], uid))
        await c.commit()
        return "ok", row[0]

async def add_promo(code, pct, uses):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("INSERT OR REPLACE INTO promos(code, bonus_pct, uses_left) VALUES(?,?,?)", (code, pct, uses))
        await c.commit()

async def list_promos():
    async with aiosqlite.connect(config.DB_PATH) as c:
        return await (await c.execute("SELECT code, bonus_pct, uses_left FROM promos ORDER BY code")).fetchall()

async def del_promo(code):
    async with aiosqlite.connect(config.DB_PATH) as c:
        await c.execute("DELETE FROM promos WHERE code=?", (code,))
        await c.commit()
