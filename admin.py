import asyncio
import csv
import html
import io

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

import brawl_api, config, db
from i18n import t
from pricing import DEFAULT_PRICES

router = Router()

STATUS = {"new": "🆕 Новая", "work": "🛠 В работе", "done": "✅ Куплено", "rej": "❌ Отказ"}
ANS = {"yes": "да", "no": "нет", "unk": "не знаю"}
LABELS = {
    "markup": "Наценка (x)", "trophies_per_1000": "Кубки за 1000", "brawler": "Боец",
    "power11": "Боец 11 ур.", "star_power": "Звёздная сила", "gadget": "Гаджет",
    "hypercharge": "Гиперзаряд", "gear": "Устройство", "skins_1_25": "Скины 1–25",
    "skins_26_75": "Скины 26–75", "skins_76_150": "Скины 76–150", "skins_151_300": "Скины 151–300",
    "skins_300_plus": "Скины 300+", "league_bronze": "Лига бронза", "league_silver": "Лига серебро",
    "league_gold": "Лига золото", "league_diamond": "Лига алмаз", "league_mythic": "Лига мифик",
    "league_legendary": "Лига легенда", "league_masters": "Лига мастер", "league_pro": "Лига Про",
    "bargain_start": "Торг: старт (доля)", "ref_bonus_per": "Бонус за друга (%)", "ref_bonus_max": "Макс. бонус рефералов (%)",
}
KEYS = list(DEFAULT_PRICES)
PER = 8


class AdminForm(StatesGroup):
    price = State()
    broadcast = State()
    ban = State()
    rare_add = State()
    rare_price = State()
    promo_add = State()


def is_admin(uid):
    return uid in config.ADMIN_IDS


def can_manage(uid):
    return is_admin(uid) or uid in config.MANAGER_IDS or (config.MANAGER_CHAT_ID and uid == config.MANAGER_CHAT_ID)


class BanMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and not is_admin(user.id) and await db.is_banned(user.id):
            return
        return await handler(event, data)


# ================= заявки (админ и менеджеры) =================
def _rub(v):
    return "—" if v is None else f"{v:,.0f} ₽".replace(",", " ")


def lead_text(l, proofs=0):
    if l["username"]:
        who = f"@{html.escape(l['username'])}"
    else:
        who = f'<a href="tg://user?id={l["user_id"]}">id {l["user_id"]}</a>'
    lines = [f"<b>Заявка #{l['id']}</b> · {STATUS.get(l['status'], l['status'])}",
             f"👤 {who}", f"🎮 {html.escape(l['name'] or '?')} · #{l['tag']}",
             f"💵 Оценка бота: <b>{html.escape(l['price_txt'])}</b>"]
    extra = []
    if l["league"]:
        extra.append(t("ru", "lg_" + l["league"]))
    if l["skins"] and l["skins"] != "none":
        extra.append("скины " + t("ru", "sk_" + l["skins"]))
    if extra:
        lines.append(" · ".join(extra))
    if l.get("rare_names"):
        lines.append("⭐ Редкое: " + html.escape(l["rare_names"]))
    elif l["rare"]:
        lines.append("⭐ Есть редкое (нужна ручная оценка)")
    if l.get("ask_txt") and l.get("ask_rub") and l["price_rub"]:
        pct = (l["ask_rub"] / l["price_rub"] - 1) * 100
        lines.append(f"💬 Цена продавца: <b>{html.escape(l['ask_txt'])}</b> ({pct:+.0f}% к оценке)")
    lines.append(f"🔐 Защита: {ANS.get(l['prot'], '-')} · 📧 Перепривязка почты: {ANS.get(l['mail'], '-')}")
    if proofs:
        lines.append(f"📎 Скриншотов: {proofs}")
    if l.get("buy_rub") is not None or l.get("sell_rub") is not None:
        profit = (l["sell_rub"] - l["buy_rub"]) if l.get("buy_rub") is not None and l.get("sell_rub") is not None else None
        lines.append(f"💼 Закупка: {_rub(l.get('buy_rub'))} · Продажа: {_rub(l.get('sell_rub'))} · Прибыль: {_rub(profit)}")
    if l["manager_id"]:
        lines.append(f"Ведёт: <code>{l['manager_id']}</code>")
    return "\n".join(lines)


def lead_kb(l):
    b = InlineKeyboardBuilder()
    names = {"work": "🛠 Взял в работу", "done": "✅ Куплено", "rej": "❌ Отказ", "new": "↩️ В новые"}
    n_st = 0
    for st in ("work", "done", "rej", "new"):
        if st != l["status"]:
            b.button(text=names[st], callback_data=f"ld:{l['id']}:{st}")
            n_st += 1
    b.button(text="💵 Закупка", callback_data=f"dl:{l['id']}:buy")
    b.button(text="💰 Продажа", callback_data=f"dl:{l['id']}:sell")
    b.button(text="🔄 Перепроверить", callback_data=f"vf:{l['id']}")
    sizes = [2] * (n_st // 2) + ([1] if n_st % 2 else []) + [2]
    if l["username"]:
        b.button(text="💬 Клиенту", url=f"https://t.me/{l['username']}")
        sizes.append(2)
    else:
        sizes.append(1)
    b.button(text="📋 К списку", callback_data="lf:all")
    sizes.append(1)
    b.adjust(*sizes)
    return b.as_markup()


def _recipients():
    return (set(config.MANAGER_IDS) | set(config.ADMIN_IDS) | {config.MANAGER_CHAT_ID}) - {0}


async def notify_managers(bot: Bot, lead_id: int):
    lead = await db.get_lead(lead_id)
    proofs = await db.count_proofs(lead_id)
    for rid in _recipients():
        try:
            await bot.send_message(rid, "🔔 " + lead_text(lead, proofs), reply_markup=lead_kb(lead))
        except Exception:
            pass


async def notify_text(bot: Bot, text: str):
    for rid in _recipients():
        try:
            await bot.send_message(rid, text)
        except Exception:
            pass


async def notify_photo(bot: Bot, file_id: str, caption: str):
    for rid in _recipients():
        try:
            await bot.send_photo(rid, file_id, caption=caption)
        except Exception:
            pass


async def leads_view(status, admin):
    leads = await db.list_leads(None if status == "all" else status)
    counts = await db.lead_counts()
    head = ["<b>Заявки</b>",
            " · ".join(f"{STATUS[s]} {counts.get(s, 0)}" for s in STATUS)]
    if not leads:
        head.append("\nПока пусто.")
    b = InlineKeyboardBuilder()
    for l in leads:
        b.button(text=f"#{l['id']} · {(l['name'] or '?')[:14]} · {l['price_txt']}", callback_data=f"ld:open:{l['id']}")
    for st, label in (("all", "Все"), ("new", "🆕"), ("work", "🛠"), ("done", "✅"), ("rej", "❌")):
        b.button(text=label, callback_data=f"lf:{st}")
    sizes = [1] * len(leads) + [5]
    if admin:
        b.button(text="⬅️ Панель", callback_data="ad:home")
        sizes.append(1)
    b.adjust(*sizes)
    return "\n".join(head), b.as_markup()


@router.message(Command("leads"))
async def cmd_leads(m: Message):
    if not can_manage(m.from_user.id):
        return
    text, markup = await leads_view("new", is_admin(m.from_user.id))
    await m.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("lf:"))
async def leads_filter(cb: CallbackQuery):
    if not can_manage(cb.from_user.id):
        return await cb.answer()
    text, markup = await leads_view(cb.data.split(":")[1], is_admin(cb.from_user.id))
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data.startswith("ld:"))
async def lead_action(cb: CallbackQuery):
    if not can_manage(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    parts = cb.data.split(":")
    if parts[1] == "open":
        lead = await db.get_lead(int(parts[2]))
    else:
        lead = await db.get_lead(int(parts[1]))
        if lead and parts[2] in STATUS:
            await db.set_lead_status(lead["id"], parts[2], cb.from_user.id)
            lead = await db.get_lead(lead["id"])
    if not lead:
        return await cb.answer("Заявка не найдена")
    try:
        await cb.message.edit_text(lead_text(lead, await db.count_proofs(lead["id"])), reply_markup=lead_kb(lead))
    except TelegramBadRequest:
        pass
    await cb.answer()


# ================= админ-панель (только ADMIN_IDS) =================
def panel_kb():
    b = InlineKeyboardBuilder()
    for text, data in (("📊 Статистика", "ad:stats"), ("📥 Заявки", "lf:new"), ("💰 Цены", "ad:prices:0"), ("⭐ Редкое", "ad:rare"), ("🎟 Промокоды", "ad:promo"),
                       ("📣 Рассылка", "ad:bc"), ("🚫 Баны", "ad:ban"), ("📤 Экспорт", "ad:export")):
        b.button(text=text, callback_data=data)
    b.adjust(2)
    return b.as_markup()


def back_panel():
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Панель", callback_data="ad:home")
    return b.as_markup()


PANEL_TEXT = "<b>Админ-панель</b>\n\nВыбери раздел. Эта панель доступна только владельцу бота."


@router.message(Command("admin"))
async def cmd_admin(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    await m.answer(PANEL_TEXT, reply_markup=panel_kb())


async def _edit(cb: CallbackQuery, text, markup):
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


async def _prices_view(page):
    prices = await db.get_prices()
    b = InlineKeyboardBuilder()
    chunk = KEYS[page * PER:(page + 1) * PER]
    for k in chunk:
        b.button(text=f"{LABELS.get(k, k)}: {prices[k]:g}", callback_data=f"ad:pk:{KEYS.index(k)}")
    nav = 0
    if page > 0:
        b.button(text="◀️", callback_data=f"ad:prices:{page - 1}")
        nav += 1
    if (page + 1) * PER < len(KEYS):
        b.button(text="▶️", callback_data=f"ad:prices:{page + 1}")
        nav += 1
    b.button(text="♻️ Сбросить всё", callback_data="ad:reset")
    b.button(text="⬅️ Панель", callback_data="ad:home")
    sizes = [2] * (len(chunk) // 2) + ([1] if len(chunk) % 2 else []) + ([nav] if nav else []) + [2]
    b.adjust(*sizes)
    return "<b>Цены (в ₽)</b>\nНажми на пункт, чтобы изменить значение.", b.as_markup()


@router.callback_query(F.data.startswith("ad:"))
async def admin_cb(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    parts = cb.data.split(":")
    action = parts[1]
    if action == "home":
        await state.clear()
        await _edit(cb, PANEL_TEXT, panel_kb())
    elif action == "stats":
        s = await db.stats_full()
        L = s["leads"]
        total = sum(L.values())
        conv = f"{L.get('done', 0) / total * 100:.0f}%" if total else "—"
        text = (f"<b>Статистика</b>\n\n👥 Пользователей: <b>{s['users']}</b>\n"
                f"📊 Оценок: <b>{s['appr']}</b> (сегодня {s['today']})\n"
                f"🚫 В бане: {s['banned']}\n\n<b>Заявки</b>: {total}\n"
                + "\n".join(f"{STATUS[k]}: {L.get(k, 0)}" for k in STATUS)
                + f"\n\nДошло до покупки: <b>{conv}</b>" + await _deals_text())
        await _edit(cb, text, back_panel())
    elif action == "prices":
        text, markup = await _prices_view(int(parts[2]))
        await _edit(cb, text, markup)
    elif action == "pk":
        key = KEYS[int(parts[2])]
        cur = (await db.get_prices())[key]
        await state.set_state(AdminForm.price)
        await state.update_data(key=key)
        await _edit(cb, f"Новое значение для <b>{LABELS.get(key, key)}</b>\nСейчас: <code>{cur:g}</code>\n\n"
                        "Отправь число (можно с точкой).", back_panel())
    elif action == "reset":
        await db.reset_prices()
        text, markup = await _prices_view(0)
        await _edit(cb, "♻️ Цены сброшены к стандартным.\n\n" + text, markup)
    elif action == "bc":
        await state.set_state(AdminForm.broadcast)
        await _edit(cb, "<b>Рассылка</b>\n\nПришли текст сообщения (можно с HTML-разметкой). "
                        "Перед отправкой я покажу, как оно выглядит.", back_panel())
    elif action == "bcgo":
        data = await state.get_data()
        await state.clear()
        text = data.get("bc_text")
        if not text:
            return await cb.answer("Нет текста", show_alert=True)
        await _edit(cb, "📣 Отправляю...", None)
        ok = fail = 0
        for uid in await db.all_user_ids():
            try:
                await cb.bot.send_message(uid, text)
                ok += 1
            except Exception:
                fail += 1
            await asyncio.sleep(0.05)
        await cb.message.answer(f"Готово. Доставлено: <b>{ok}</b>, не дошло: {fail}", reply_markup=back_panel())
    elif action == "ban":
        await state.set_state(AdminForm.ban)
        await _edit(cb, "<b>Баны</b>\n\nПришли ID пользователя, чтобы забанить.\n"
                        "Чтобы разбанить: <code>unban 123456</code>", back_panel())
    elif action == "promo":
        text, markup = await _promo_view()
        await _edit(cb, text, markup)
    elif action == "pi":
        code = parts[2]
        b = InlineKeyboardBuilder()
        b.button(text="🗑 Удалить", callback_data=f"ad:pdel:{code}")
        b.button(text="⬅️ К списку", callback_data="ad:promo")
        b.adjust(2)
        await _edit(cb, f"Промокод <code>{html.escape(code)}</code>", b.as_markup())
    elif action == "pdel":
        await db.del_promo(parts[2])
        text, markup = await _promo_view()
        await _edit(cb, "🗑 Удалено.\n\n" + text, markup)
    elif action == "pa":
        await state.set_state(AdminForm.promo_add)
        await _edit(cb, "Пришли промокод так: <code>КОД | процент | сколько раз можно использовать</code>\n"
                        "Например: <code>FRIEND | 3 | 50</code>. Лимит 0 = без ограничений.", back_panel())
    elif action == "rare":
        text, markup = await _rare_view()
        await _edit(cb, text, markup)
    elif action == "ri":
        it = (await db.get_rare_by_ids([int(parts[2])]))[0]
        b = InlineKeyboardBuilder()
        b.button(text="💰 Изменить цену", callback_data=f"ad:rp:{it['id']}")
        b.button(text="🗑 Удалить", callback_data=f"ad:rd:{it['id']}")
        b.button(text="⬅️ К списку", callback_data="ad:rare")
        b.adjust(2, 1)
        await _edit(cb, f"<b>{html.escape(it['name'])}</b>\nЦена: <b>{_rub(it['price_rub'])}</b>", b.as_markup())
    elif action == "ra":
        await state.set_state(AdminForm.rare_add)
        await _edit(cb, "Пришли название и цену в ₽ через вертикальную черту, например:\n"
                        "<code>Пин 35 ранга | 1500</code>", back_panel())
    elif action == "rp":
        await state.set_state(AdminForm.rare_price)
        await state.update_data(rid=int(parts[2]))
        await _edit(cb, "Пришли новую цену в ₽ (число).", back_panel())
    elif action == "rd":
        await db.del_rare(int(parts[2]))
        text, markup = await _rare_view()
        await _edit(cb, "🗑 Удалено.\n\n" + text, markup)
    elif action == "export":
        for table, name in (("history", "appraisals.csv"), ("leads", "leads.csv")):
            cols, rows = await db.export_rows(table)
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            w.writerows(rows)
            await cb.message.answer_document(BufferedInputFile(buf.getvalue().encode("utf-8-sig"), name))
    await cb.answer()


@router.message(AdminForm.price)
async def admin_price(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    try:
        val = float((m.text or "").replace(",", "."))
    except ValueError:
        return await m.answer("Нужно число, например <code>2.5</code>")
    key = (await state.get_data())["key"]
    await db.set_price(key, val)
    await state.clear()
    text, markup = await _prices_view(KEYS.index(key) // PER)
    await m.answer(f"✅ {LABELS.get(key, key)} = {val:g}\n\n{text}", reply_markup=markup)


@router.message(AdminForm.broadcast)
async def admin_broadcast(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    text = m.html_text or m.text or ""
    await state.update_data(bc_text=text)
    b = InlineKeyboardBuilder()
    b.button(text="🚀 Отправить всем", callback_data="ad:bcgo")
    b.button(text="Отмена", callback_data="ad:home")
    b.adjust(1)
    await m.answer("Так увидят пользователи:\n\n" + text, reply_markup=b.as_markup())


@router.message(AdminForm.ban)
async def admin_ban(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    parts = (m.text or "").split()
    unban = bool(parts) and parts[0].lower() == "unban"
    ids = parts[1:] if unban else parts
    if not ids or not ids[0].isdigit():
        return await m.answer("Пришли числовой ID.")
    uid = int(ids[0])
    if uid in config.ADMIN_IDS:
        return await m.answer("Себя банить не надо.")
    await db.set_banned(uid, not unban)
    await state.clear()
    await m.answer(("✅ Разбанен: " if unban else "🚫 Забанен: ") + str(uid), reply_markup=back_panel())


# ================= старые команды (владелец) =================
@router.message(Command("prices"))
async def prices(m: Message):
    if not is_admin(m.from_user.id):
        return
    p = await db.get_prices()
    await m.answer("💰 Цены (₽):\n" + "\n".join(f"<code>{k}</code> = {v:g}" for k, v in p.items()))


@router.message(Command("setprice"))
async def setprice(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id):
        return
    try:
        key, val = command.args.split()
        assert key in DEFAULT_PRICES
        await db.set_price(key, float(val))
        await m.answer(f"✅ {key} = {val}")
    except Exception:
        await m.answer("Использование: /setprice ключ значение\nКлючи: " + ", ".join(DEFAULT_PRICES))


@router.message(Command("resetprices"))
async def resetprices(m: Message):
    if not is_admin(m.from_user.id):
        return
    await db.reset_prices()
    await m.answer("♻️ Цены сброшены к стандартным из pricing.py")


# ================= каталог редкого, сделки, проверка =================
class Deal(StatesGroup):
    buy = State()
    sell = State()


async def _rare_view():
    items = await db.list_rare()
    b = InlineKeyboardBuilder()
    for it in items:
        b.button(text=f"{it['name']} · {_rub(it['price_rub'])}", callback_data=f"ad:ri:{it['id']}")
    b.button(text="➕ Добавить", callback_data="ad:ra")
    b.button(text="⬅️ Панель", callback_data="ad:home")
    b.adjust(*([1] * len(items)), 2)
    text = ("<b>Каталог редкого</b>\nПродавец отмечает эти пункты в боте, цена добавляется к оценке сразу."
            + ("" if items else "\n\nПока пусто, добавь первый пункт."))
    return text, b.as_markup()


async def _deals_text():
    rows = []
    for label, days in (("всего", None), ("7 дней", 7), ("30 дней", 30)):
        n, buy, sell = await db.deals_stats(days)
        rows.append(f"{label}: сделок {n} · закупка {_rub(buy)} · продажа {_rub(sell)} · прибыль <b>{_rub(sell - buy)}</b>")
    return "\n\n<b>Сделки</b> (где указаны обе цены)\n" + "\n".join(rows)


def _num(text):
    try:
        v = float((text or "").replace(" ", "").replace(",", "."))
        return v if v >= 0 else None
    except ValueError:
        return None


@router.message(AdminForm.rare_add)
async def rare_add(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    if "|" not in (m.text or ""):
        return await m.answer("Нужен формат: <code>Название | цена</code>")
    name, price = (m.text or "").rsplit("|", 1)
    v = _num(price)
    if not name.strip() or v is None:
        return await m.answer("Не разобрал цену. Пример: <code>Пин 35 ранга | 1500</code>")
    await db.add_rare(name.strip()[:40], v)
    await state.clear()
    text, markup = await _rare_view()
    await m.answer("✅ Добавлено.\n\n" + text, reply_markup=markup)


@router.message(AdminForm.rare_price)
async def rare_price(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    v = _num(m.text)
    if v is None:
        return await m.answer("Нужно число.")
    await db.set_rare_price((await state.get_data())["rid"], v)
    await state.clear()
    text, markup = await _rare_view()
    await m.answer("✅ Цена обновлена.\n\n" + text, reply_markup=markup)


@router.callback_query(F.data.startswith("dl:"))
async def deal_cb(cb: CallbackQuery, state: FSMContext):
    if not can_manage(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    _, lid, kind = cb.data.split(":")
    await state.set_state(Deal.buy if kind == "buy" else Deal.sell)
    await state.update_data(lid=int(lid))
    await cb.message.answer("Пришли сумму " + ("закупки" if kind == "buy" else "продажи") + " в ₽ (число).")
    await cb.answer()


@router.message(Deal.buy)
@router.message(Deal.sell)
async def deal_value(m: Message, state: FSMContext):
    if not can_manage(m.from_user.id):
        return
    v = _num(m.text)
    if v is None:
        return await m.answer("Нужно число, например <code>1500</code>")
    lid = (await state.get_data())["lid"]
    field = "buy_rub" if await state.get_state() == Deal.buy.state else "sell_rub"
    await db.set_lead_field(lid, **{field: v})
    await state.clear()
    lead = await db.get_lead(lid)
    await m.answer(lead_text(lead, await db.count_proofs(lid)), reply_markup=lead_kb(lead))


@router.callback_query(F.data.startswith("vf:"))
async def verify_cb(cb: CallbackQuery):
    if not can_manage(cb.from_user.id):
        return await cb.answer("Нет доступа", show_alert=True)
    lead = await db.get_lead(int(cb.data.split(":")[1]))
    if not lead:
        return await cb.answer("Заявка не найдена")
    await cb.answer("Проверяю...")
    try:
        p = await brawl_api.get_player(lead["tag"], fresh=True)
    except brawl_api.PlayerNotFound:
        return await cb.message.answer(f"⚠️ Заявка #{lead['id']}: игрока #{lead['tag']} больше нет по этому тегу.")
    except brawl_api.ApiError:
        return await cb.message.answer("⚠️ Brawl Stars не ответил, попробуй позже.")
    tr_now, br_now = p.get("highestTrophies", 0), len(p.get("brawlers", []))
    tr_was, br_was = lead.get("snap_trophies"), lead.get("snap_brawlers")
    bad = []
    if tr_was is not None and tr_now != tr_was:
        bad.append("рекордные кубки")
    if br_was is not None and br_now != br_was:
        bad.append("число бойцов")
    if (lead["name"] or "") != p.get("name", ""):
        bad.append("ник")
    verdict_line = "✅ Всё совпадает с оценкой." if not bad else "⚠️ Есть расхождения: " + ", ".join(bad)
    await cb.message.answer(
        f"🔍 <b>Проверка заявки #{lead['id']}</b>\n"
        f"Ник: {html.escape(lead['name'] or '?')} → {html.escape(p.get('name', '?'))}\n"
        f"Рекордные кубки: {tr_was} → {tr_now}\nБойцов: {br_was} → {br_now}\n\n{verdict_line}")


# ================= промокоды =================
async def _promo_view():
    promos = await db.list_promos()
    b = InlineKeyboardBuilder()
    for code, pct, left in promos:
        lim = "без лимита" if left < 0 else f"осталось {left}"
        b.button(text=f"{code} · +{pct:g}% · {lim}", callback_data=f"ad:pi:{code}")
    b.button(text="➕ Создать", callback_data="ad:pa")
    b.button(text="⬅️ Панель", callback_data="ad:home")
    b.adjust(*([1] * len(promos)), 2)
    text = ("<b>Промокоды</b>\nДают пользователю бонус к оценке в процентах."
            + ("" if promos else "\n\nПока нет ни одного."))
    return text, b.as_markup()


@router.message(AdminForm.promo_add)
async def promo_add(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    parts = [x.strip() for x in (m.text or "").split("|")]
    try:
        code = parts[0].upper().replace(" ", "")
        pct = float(parts[1].replace(",", "."))
        uses = int(parts[2]) if len(parts) > 2 and parts[2] else 0
        assert code and 0 < pct <= 50 and uses >= 0
    except (IndexError, ValueError, AssertionError):
        return await m.answer("Не разобрал. Пример: <code>FRIEND | 3 | 50</code> (процент от 0 до 50)")
    await db.add_promo(code, pct, uses if uses > 0 else -1)
    await state.clear()
    text, markup = await _promo_view()
    await m.answer("✅ Готово.\n\n" + text, reply_markup=markup)
