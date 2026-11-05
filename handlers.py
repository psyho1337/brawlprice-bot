import asyncio
import html
import time
from collections import defaultdict, deque

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (Message, CallbackQuery, FSInputFile, BufferedInputFile, InputMediaPhoto,
                           InlineQuery, InlineQueryResultArticle, InputTextMessageContent)

import admin, config, db, brawl_api, pricing, currency, cards
from i18n import t, WELCOME_MULTI, LANGS, verdict
import keyboards as kb

router = Router()

PATHS = {"logo": cards.LOGO, "example": cards.EXAMPLE}
_ids = {}     # кэш file_id, чтобы не загружать картинки заново
_shown = {}   # какое фото сейчас показано в сообщении
LAST = {}     # последняя оценка пользователя (для «Продать», «Поделиться», «Следить»)
_RATE = defaultdict(deque)
RU_ANS = {"yes": "да", "no": "нет", "unk": "не знаю"}


def _rate_ok(uid, limit=6, window=60):
    """Антиспам: не больше 6 запросов к API в минуту (админы без лимита)."""
    if uid in config.ADMIN_IDS:
        return True
    now = time.time()
    q = _RATE[uid]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True


class Form(StatesGroup):
    tag = State()
    skins = State()
    league = State()
    rare = State()


class Cmp(StatesGroup):
    first = State()
    second = State()


class Sell(StatesGroup):
    proof = State()
    ask = State()


class Promo(StatesGroup):
    code = State()


# ---------- экраны (плавная смена без мерцания) ----------
def _media(name):
    return _ids.get(name) or FSInputFile(PATHS[name])


def _remember(name, msg):
    if isinstance(msg, Message) and msg.photo:
        _ids[name] = msg.photo[-1].file_id


async def send_screen(message: Message, name, caption, markup):
    sent = await message.answer_photo(_media(name), caption=caption, reply_markup=markup)
    _remember(name, sent)
    if len(_shown) > 5000:
        _shown.clear()
    _shown[(sent.chat.id, sent.message_id)] = name
    return sent


async def screen(cb: CallbackQuery, name, caption, markup):
    msg = cb.message
    key = (msg.chat.id, msg.message_id)
    try:
        if _shown.get(key) == name:
            await msg.edit_caption(caption=caption, reply_markup=markup)
        else:
            res = await msg.edit_media(InputMediaPhoto(media=_media(name), caption=caption),
                                       reply_markup=markup)
            _remember(name, res)
        _shown[key] = name
    except TelegramBadRequest as e:
        if "not modified" in str(e).lower():
            return
        _ids.pop(name, None)
        try:
            await msg.delete()
        except Exception:
            pass
        await send_screen(msg, name, caption, markup)


async def _step(cb: CallbackQuery, text, markup):
    """Смена шага мастера в том же сообщении."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass
    await cb.answer()


async def _user(uid):
    return await db.get_user(uid) or {"lang": "ru", "currency": "RUB"}


def _n(x):
    return f"{x:,}".replace(",", " ")


def _settings_text(lang, cur):
    return (t(lang, "settings").replace("%LANG%", LANGS[lang])
            .replace("%CUR%", f"{currency.CURRENCIES[cur]} {cur}"))


# ---------- обязательная подписка ----------
_SUB_OK = {}


async def _subscribed(bot, uid):
    ch = config.REQUIRED_CHANNEL
    if not ch or admin.can_manage(uid):
        return True
    if time.time() - _SUB_OK.get(uid, 0) < 600:
        return True
    try:
        member = await bot.get_chat_member(ch, uid)
        ok = member.status in ("member", "administrator", "creator")
    except Exception:
        return True   # если бот не может проверить (не админ канала), пользователей не блокируем
    if ok:
        _SUB_OK[uid] = time.time()
    return ok


# ---------- анимация ----------
STAGES = [(10, "st1"), (35, "st2"), (60, "st3"), (85, "st4"), (100, "st5")]


def _stage_text(lang, p, key):
    n = p // 10
    return f"{t(lang, key)}\n\n<code>{'▰' * n}{'▱' * (10 - n)} {p}%</code>"


async def animate(status: Message, lang):
    for p, key in STAGES[1:]:
        await asyncio.sleep(0.7)
        try:
            await status.edit_text(_stage_text(lang, p, key))
        except Exception:
            pass
    await asyncio.sleep(0.4)


async def _fetch(m: Message, tag, lang):
    status = await m.answer(t(lang, "searching"))
    try:
        player = await brawl_api.get_player(tag)
    except brawl_api.PlayerNotFound:
        await status.edit_text(t(lang, "not_found"))
        return None
    except brawl_api.ApiError:
        await status.edit_text(t(lang, "api_error"))
        return None
    await status.delete()
    return player


# ---------- старт, язык, валюта ----------
@router.message(CommandStart())
async def start(m: Message, state: FSMContext, command: CommandObject):
    await state.clear()
    u = await db.get_user(m.from_user.id)
    if not u:
        arg = command.args or ""
        if arg.startswith("ref_") and arg[4:].isdigit():
            ref = int(arg[4:])
            if await db.add_referral(m.from_user.id, ref):
                try:
                    rl = (await db.get_user(ref) or {"lang": "ru"})["lang"]
                    await m.bot.send_message(ref, t(rl, "ref_new"))
                except Exception:
                    pass
        await send_screen(m, "logo", WELCOME_MULTI, kb.lang_kb())
    else:
        await send_screen(m, "logo", t(u["lang"], "welcome"), kb.main_kb(u["lang"]))


@router.callback_query(F.data.startswith("lang:"))
async def set_lang(cb: CallbackQuery):
    lang = cb.data.split(":")[1]
    await db.set_lang(cb.from_user.id, lang)
    await screen(cb, "logo", t(lang, "welcome"), kb.main_kb(lang))
    await cb.answer()


@router.callback_query(F.data.startswith("cur:"))
async def set_cur(cb: CallbackQuery):
    code = cb.data.split(":")[1]
    await db.set_currency(cb.from_user.id, code)
    lang = (await _user(cb.from_user.id))["lang"]
    await screen(cb, "logo", _settings_text(lang, code), kb.settings_kb(lang))
    await cb.answer(t(lang, "saved"))


# ---------- меню ----------
@router.callback_query(F.data.startswith("menu:"))
async def menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    action = cb.data.split(":")[1]
    u = await _user(cb.from_user.id)
    lang, cur = u["lang"], u["currency"]
    if action in ("appraise", "compare") and not await _subscribed(cb.bot, cb.from_user.id):
        await screen(cb, "logo", t(lang, "sub_required"), kb.sub_kb(lang, config.CHANNEL_URL))
        return await cb.answer()
    if action == "main":
        await screen(cb, "logo", t(lang, "welcome"), kb.main_kb(lang))
    elif action == "settings":
        await screen(cb, "logo", _settings_text(lang, cur), kb.settings_kb(lang))
    elif action == "lang":
        await screen(cb, "logo", t(lang, "choose_lang"), kb.lang_kb())
    elif action == "currency":
        await screen(cb, "logo", t(lang, "choose_currency"), kb.currency_kb(lang))
    elif action == "help":
        await screen(cb, "logo", t(lang, "help"), kb.back_kb(lang))
    elif action == "stats":
        count, avg, best = await db.user_stats(cb.from_user.id)
        if not count:
            text = f"{t(lang, 'stats_title')}\n{t(lang, 'stats_empty')}"
        else:
            text = (f"{t(lang, 'stats_title')}\n"
                    f"🧮 {t(lang, 'stats_count')}: <b>{count}</b>\n"
                    f"📊 {t(lang, 'stats_avg')}: <b>{await currency.fmt(avg, cur)}</b>\n"
                    f"💎 {t(lang, 'stats_best')}: <b>{html.escape(best[0])}</b> · "
                    f"{await currency.fmt(best[1], cur)}")
        await screen(cb, "logo", text, kb.back_kb(lang))
    elif action == "history":
        rows = await db.get_history(cb.from_user.id)
        if not rows:
            text = t(lang, "history_empty")
        else:
            lines = [t(lang, "history_title")]
            for i, (tag, name, rub, created) in enumerate(rows, 1):
                date = f"{created[8:10]}.{created[5:7]}"
                lines.append(f"<b>{i}.</b> {html.escape(name)} · #{tag}\n"
                             f"      💵 {await currency.fmt(rub, cur)} · 🗓 {date}")
            text = "\n".join(lines)
        await screen(cb, "logo", text, kb.back_kb(lang))
    elif action == "bonus":
        prices = await db.get_prices()
        me = await cb.bot.me()
        n = await db.ref_count(cb.from_user.id)
        bonus = await db.get_bonus(cb.from_user.id, prices["ref_bonus_per"], prices["ref_bonus_max"])
        text = (t(lang, "bonus_text").replace("%LINK%", f"https://t.me/{me.username}?start=ref_{cb.from_user.id}")
                .replace("%N%", str(n)).replace("%B%", f"{bonus:g}"))
        await screen(cb, "logo", text, kb.bonus_kb(lang))
    elif action == "appraise":
        await state.set_state(Form.tag)
        await screen(cb, "example", t(lang, "ask_tag"), kb.back_kb(lang))
    elif action == "compare":
        await state.set_state(Cmp.first)
        await screen(cb, "logo", t(lang, "cmp_first"), kb.back_kb(lang))
    await cb.answer()


# ---------- оценка: тег → скины → лига → редкое ----------
async def _begin(message: Message, state: FSMContext, tag, player, lang):
    await state.update_data(player=player, tag=tag, skins=None, league=None, rare_ids=[], rare_other=False)
    await state.set_state(Form.skins)
    await message.answer(t(lang, "step_skins"), reply_markup=kb.skins_kb(lang))


@router.message(Form.tag)
async def got_tag(m: Message, state: FSMContext):
    lang = (await _user(m.from_user.id))["lang"]
    tag = brawl_api.normalize_tag(m.text or "")
    if not tag:
        return await m.answer(t(lang, "bad_tag"))
    if not _rate_ok(m.from_user.id):
        return await m.answer(t(lang, "slow_down"))
    player = await _fetch(m, tag, lang)
    if not player:
        return
    await _begin(m, state, tag, player, lang)


@router.callback_query(F.data.startswith("rw:"))
async def recalc(cb: CallbackQuery, state: FSMContext):
    lang = (await _user(cb.from_user.id))["lang"]
    tag = cb.data.split(":", 1)[1]
    await cb.answer()
    if not await _subscribed(cb.bot, cb.from_user.id):
        return await cb.message.answer(t(lang, "sub_required"), reply_markup=kb.sub_kb(lang, config.CHANNEL_URL))
    if not _rate_ok(cb.from_user.id):
        return await cb.message.answer(t(lang, "slow_down"))
    player = await _fetch(cb.message, tag, lang)
    if player:
        await _begin(cb.message, state, tag, player, lang)


@router.callback_query(F.data.startswith("sk:"), Form.skins)
async def step_skins(cb: CallbackQuery, state: FSMContext):
    lang = (await _user(cb.from_user.id))["lang"]
    val = cb.data.split(":", 1)[1]
    await state.update_data(skins=val if val in pricing.SKIN_BRACKETS else None)
    await state.set_state(Form.league)
    await _step(cb, t(lang, "step_league"), kb.league_kb(lang))


@router.callback_query(F.data.startswith("lg:"), Form.league)
async def step_league(cb: CallbackQuery, state: FSMContext):
    lang = (await _user(cb.from_user.id))["lang"]
    val = cb.data.split(":", 1)[1]
    await state.update_data(league=val if val in pricing.LEAGUES else None)
    await state.set_state(Form.rare)
    await _step(cb, t(lang, "step_rare"), kb.rare_kb(lang, await db.list_rare(), [], False))


@router.callback_query(F.data.startswith("rr:"), Form.rare)
async def step_rare(cb: CallbackQuery, state: FSMContext):
    lang = (await _user(cb.from_user.id))["lang"]
    parts = cb.data.split(":")
    data = await state.get_data()
    sel = list(data.get("rare_ids", []))
    other = data.get("rare_other", False)
    act = parts[1]
    if act in ("t", "o"):
        if act == "t":
            rid = int(parts[2])
            sel = [x for x in sel if x != rid] if rid in sel else sel + [rid]
        else:
            other = not other
        await state.update_data(rare_ids=sel, rare_other=other)
        try:
            await cb.message.edit_reply_markup(reply_markup=kb.rare_kb(lang, await db.list_rare(), sel, other))
        except TelegramBadRequest:
            pass
        return await cb.answer()
    if act == "none":
        await state.update_data(rare_ids=[], rare_other=False)
    await cb.answer()
    msg = cb.message
    try:
        await msg.delete()
    except Exception:
        pass
    await _finish(cb.from_user.id, msg, state)


def _lead_text(d, answers=None):
    lines = ["Здравствуйте! Хочу продать аккаунт Brawl Stars.",
             f"Тег: #{d['tag']}", f"Оценка бота: {d['total_txt']}"]
    if d.get("league"):
        lines.append(f"Лига: {t('ru', 'lg_' + d['league'])}")
    if d.get("skins") and d["skins"] != "none":
        lines.append(f"Скины: {t('ru', 'sk_' + d['skins'])}")
    lines.append("Редкое: " + (d["rare_names"] if d.get("rare_names") else "нет"))
    if d.get("ask_txt"):
        lines.append(f"Моя цена: {d['ask_txt']}")
    if answers:
        lines.append(f"Доп. защита: {RU_ANS.get(answers.get('prot'), '-')}")
        lines.append(f"Перепривязка почты: {RU_ANS.get(answers.get('mail'), '-')}")
    return "\n".join(lines)


async def _finish(user_id, message: Message, state: FSMContext):
    u = await _user(user_id)
    lang, cur = u["lang"], u["currency"]
    data = await state.get_data()
    player, tag = data["player"], data["tag"]
    skins, league = data.get("skins"), data.get("league")
    rare_other = data.get("rare_other", False)
    items = await db.get_rare_by_ids(data.get("rare_ids", []))
    rare_sum = sum(i["price_rub"] for i in items)
    await state.clear()

    status = await message.answer(_stage_text(lang, *STAGES[0]))
    await animate(status, lang)

    prices = await db.get_prices()
    res = pricing.calculate(player, prices, skins, league, rare_sum=rare_sum)
    bonus = await db.get_bonus(user_id, prices["ref_bonus_per"], prices["ref_bonus_max"])
    res = pricing.apply_bonus(res, bonus)
    name = player.get("name", "?")
    highest = player.get("highestTrophies", 0)
    idx, emoji = pricing.tier(highest)
    tier_name = t(lang, f"tier_{idx}")
    total_txt = await currency.fmt(res["total"], cur)
    range_txt = f"{await currency.fmt(res['low'], cur)} – {await currency.fmt(res['high'], cur)}"
    rare_names = [i["name"] for i in items] + (["Другое редкое"] if rare_other else [])

    LAST[user_id] = dict(tag=tag, name=name, total_txt=total_txt, total_rub=res["total"],
                         league=league, skins=skins, rare=bool(rare_names), rare_names=", ".join(rare_names),
                         snap_trophies=highest, snap_brawlers=len(player.get("brawlers", [])))
    url = kb.manager_url(_lead_text(LAST[user_id]))

    # сравнение с другими оценками и с прошлой оценкой этого аккаунта
    below, total_n = await db.percentile(res["total"])
    pct_line = t(lang, "res_pct").replace("%P%", str(round(below / total_n * 100))) if total_n >= 10 else None
    prev = await db.last_for_tag(user_id, tag)
    change_line = None
    if prev and abs(res["total"] - prev[0]) >= 1:
        diff = res["total"] - prev[0]
        sign = "+" if diff > 0 else "−"
        change_line = (t(lang, "res_change").replace("%DATE%", f"{prev[1][8:10]}.{prev[1][5:7]}")
                       .replace("%DIFF%", sign + await currency.fmt(abs(diff), cur)))

    # подпись к карточке (лимит Telegram: 1024 символа)
    cap = [t(lang, "res_title"), "", f"👤 <b>{html.escape(name)}</b> · #{tag}",
           f"{emoji} {t(lang, 'res_tier')}: <b>{tier_name}</b>"]
    if league:
        cap.append(f"🏅 {t(lang, 'res_league')}: <b>{t(lang, 'lg_' + league)}</b>")
    if skins and skins != "none":
        cap.append(f"🎨 {t(lang, 'res_skins')}: <b>{t(lang, 'sk_' + skins)}</b>")
    if rare_names:
        cap.append(f"⭐ {t(lang, 'res_rare_cnt')}: <b>{len(rare_names)}</b>")
    cap += ["", f"💬 <i>{verdict(lang, idx)}</i>", ""]
    top = pricing.top_brawlers(player)
    if top:
        cap.append(t(lang, "res_top") + " " + ", ".join(f"{html.escape(n)} ({_n(tr)})" for n, tr in top))
    if pct_line:
        cap.append(pct_line)
    if change_line:
        cap.append(change_line)
    if bonus:
        cap.append(t(lang, "res_bonus").replace("%B%", f"{bonus:g}"))
    cap += ["", f"{t(lang, 'res_total')}: <b>{total_txt}</b>", f"{t(lang, 'res_range')}: {range_txt}",
            f"{t(lang, 'res_bargain')}: {await currency.fmt(res['offer'], cur)} → {total_txt}"]
    if rare_other:
        cap += ["", t(lang, "res_rare")]

    # подробная разбивка отдельным сообщением
    det = []
    for key, qty, rub in res["rows"]:
        price_txt = await currency.fmt(rub, cur)
        if key == "league":
            det.append(f"🏅 {t(lang, 'res_league')}: {t(lang, 'lg_' + league)} — {price_txt}")
        elif key.startswith("skins_"):
            det.append(f"🎨 {t(lang, 'lbl_' + key)} — {price_txt}")
        elif key == "rare_items":
            for it in items:
                det.append(f"⭐ {html.escape(it['name'])} — {await currency.fmt(it['price_rub'], cur)}")
        else:
            det.append(f"• {t(lang, 'lbl_' + key)}: {_n(qty)} — {price_txt}")

    if bonus:
        det.append("🎁 " + t(lang, "res_bonus").replace("%B%", f"{bonus:g}").replace("<b>", "").replace("</b>", ""))
    tips = pricing.upgrade_tips(player, prices)
    up = []
    if tips["not11"] and tips["p11"] >= 1:
        up.append("• " + t(lang, "up_p11").replace("%N%", str(tips["not11"]))
                  .replace("%X%", await currency.fmt(tips["p11"], cur)))
    if (tips["gadgets"] + tips["sps"]) and (tips["g"] + tips["s"]) >= 1:
        up.append("• " + t(lang, "up_gear").replace("%N%", str(tips["gadgets"] + tips["sps"]))
                  .replace("%X%", await currency.fmt(tips["g"] + tips["s"], cur)))
    parts = [t(lang, "res_details"), "<blockquote expandable>" + "\n".join(det) + "</blockquote>"]
    if up:
        parts += ["", t(lang, "up_title"), "\n".join(up)]
    parts += ["", t(lang, "rare_cta") if rare_other else t(lang, "note_manager")]

    qty = {k: q for k, q, _ in res["rows"]}
    if league:
        second = (t(lang, "lbl_league"), t(lang, "lg_" + league).split(" ", 1)[-1])
    else:
        second = (t(lang, "lbl_current"), _n(player.get("trophies", 0)))
    skins_cell = t(lang, "sk_" + skins) if skins and skins != "none" else "—"
    stats = [(t(lang, "lbl_trophies"), _n(highest)), second,
             (t(lang, "lbl_brawler"), _n(qty["brawler"])), (t(lang, "lbl_power11"), _n(qty["power11"])),
             (t(lang, "lbl_star_power"), _n(qty["star_power"])), (t(lang, "lbl_gadget"), _n(qty["gadget"])),
             (t(lang, "lbl_hypercharge"), _n(qty["hypercharge"])),
             (t(lang, "lbl_wins"), _n(player.get("3vs3Victories", 0))),
             (t(lang, "lbl_skins_total"), skins_cell)]
    card_range = f"{t(lang, 'res_range').split(' ', 1)[-1]}: {range_txt}"
    LAST[user_id]["share"] = dict(title=t(lang, "card_title"), name=name, tag=tag, total_txt=total_txt,
                                  range_txt=card_range, stats=stats, badge=tier_name)
    png = cards.render_card(t(lang, "card_title"), name, tag, total_txt, card_range, stats, badge=tier_name)

    await db.add_history(user_id, tag, name, res["total"])
    try:
        await status.delete()
    except Exception:
        pass
    await message.answer_photo(BufferedInputFile(png.read(), "card.png"), caption="\n".join(cap))
    await message.answer("\n".join(parts), reply_markup=kb.result_kb(lang, url, rare_other))


# ---------- «Поделиться» и «Следить» ----------
@router.callback_query(F.data == "share:last")
async def share(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    d = LAST.get(cb.from_user.id)
    if not d or "share" not in d:
        return await cb.answer(t(lang, "sell_no_data"), show_alert=True)
    await cb.answer()
    me = await cb.bot.me()
    s = d["share"]
    png = cards.render_card(s["title"], s["name"], s["tag"], s["total_txt"], s["range_txt"], s["stats"],
                            badge=s["badge"], show_tag=False, watermark=f"PRICE BRAWL · t.me/{me.username}")
    await cb.message.answer_photo(BufferedInputFile(png.read(), "share.png"),
                                  caption=t(lang, "share_caption").replace("%LINK%", f"https://t.me/{me.username}"))


@router.callback_query(F.data == "watch:last")
async def watch(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    d = LAST.get(cb.from_user.id)
    if not d:
        return await cb.answer(t(lang, "sell_no_data"), show_alert=True)
    await db.add_reminder(cb.from_user.id, d["tag"], d["name"], time.time() + 7 * 86400)
    await cb.answer(t(lang, "watch_on"), show_alert=True)


# ---------- продажа ----------
def _ready(lang, d):
    text = (t(lang, "sell_ready").replace("%NAME%", html.escape(d["name"]))
            .replace("%TAG%", d["tag"]).replace("%PRICE%", d["total_txt"]))
    if "unk" in (d.get("prot"), d.get("mail")):
        text += t(lang, "sell_unknown")
    if d.get("ask_txt"):
        text += f"\n\n💰 {t(lang, 'ask_yours')}: <b>{d['ask_txt']}</b>"
    return text, kb.sell_done_kb(lang, kb.manager_url(_lead_text(d, d)))


@router.callback_query(F.data == "sell:start")
async def sell_start(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    if cb.from_user.id not in LAST:
        await screen(cb, "logo", t(lang, "sell_no_data"), kb.back_kb(lang))
    else:
        LAST[cb.from_user.id].pop("prot", None)
        LAST[cb.from_user.id].pop("mail", None)
        await screen(cb, "logo", t(lang, "sell_prot"), kb.prot_kb(lang))
    await cb.answer()


@router.callback_query(F.data.startswith("sell:prot:"))
async def sell_prot(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    d = LAST.get(cb.from_user.id)
    if not d:
        await screen(cb, "logo", t(lang, "sell_no_data"), kb.back_kb(lang))
        return await cb.answer()
    ans = cb.data.split(":")[2]
    d["prot"] = ans
    if ans == "yes":
        await screen(cb, "logo", t(lang, "sell_prot_block"), kb.contact_kb(lang, kb.manager_url()))
    else:
        await screen(cb, "logo", t(lang, "sell_mail"), kb.mail_kb(lang))
    await cb.answer()


@router.callback_query(F.data.startswith("sell:mail:"))
async def sell_mail(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    d = LAST.get(cb.from_user.id)
    if not d:
        await screen(cb, "logo", t(lang, "sell_no_data"), kb.back_kb(lang))
        return await cb.answer()
    ans = cb.data.split(":")[2]
    d["mail"] = ans
    if ans == "no":
        await screen(cb, "logo", t(lang, "sell_mail_block"), kb.contact_kb(lang, kb.manager_url()))
        return await cb.answer()
    if not d.get("lead_id"):  # одна заявка на одну оценку
        user = cb.from_user
        d["lead_id"] = await db.add_lead(
            user_id=user.id, username=user.username or "", tag=d["tag"], name=d["name"],
            price_rub=d["total_rub"], price_txt=d["total_txt"], league=d.get("league") or "",
            skins=d.get("skins") or "", rare=int(bool(d.get("rare"))), rare_names=d.get("rare_names", ""),
            prot=d.get("prot", ""), mail=d.get("mail", ""),
            snap_trophies=d.get("snap_trophies"), snap_brawlers=d.get("snap_brawlers"))
        await admin.notify_managers(cb.bot, d["lead_id"])
    text, markup = _ready(lang, d)
    await screen(cb, "logo", text, markup)
    await cb.answer()


@router.callback_query(F.data == "sell:ready")
async def sell_ready(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    lang = (await _user(cb.from_user.id))["lang"]
    d = LAST.get(cb.from_user.id)
    if not d or not d.get("lead_id"):
        await screen(cb, "logo", t(lang, "sell_no_data"), kb.back_kb(lang))
    else:
        text, markup = _ready(lang, d)
        await screen(cb, "logo", text, markup)
    await cb.answer()


@router.callback_query(F.data == "sell:check")
async def sell_check(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    await screen(cb, "logo", t(lang, "checklist"), kb.sell_back_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "sell:proof")
async def sell_proof(cb: CallbackQuery, state: FSMContext):
    lang = (await _user(cb.from_user.id))["lang"]
    d = LAST.get(cb.from_user.id)
    if not d or not d.get("lead_id"):
        await screen(cb, "logo", t(lang, "sell_no_data"), kb.back_kb(lang))
    else:
        await state.set_state(Sell.proof)
        await screen(cb, "logo", t(lang, "proof_prompt"), kb.proof_kb(lang))
    await cb.answer()


@router.message(Sell.proof, F.photo)
async def got_proof(m: Message, state: FSMContext):
    lang = (await _user(m.from_user.id))["lang"]
    d = LAST.get(m.from_user.id)
    if not d or not d.get("lead_id"):
        await state.clear()
        return await m.answer(t(lang, "sell_no_data"))
    file_id = m.photo[-1].file_id
    await db.add_proof(d["lead_id"], file_id)
    await admin.notify_photo(m.bot, file_id, f"📎 Скриншот к заявке #{d['lead_id']} · {d['name']} · #{d['tag']}")
    n = await db.count_proofs(d["lead_id"])
    await m.answer(t(lang, "proof_got").replace("%N%", str(n)), reply_markup=kb.proof_kb(lang))


@router.message(Sell.proof)
async def proof_hint(m: Message):
    lang = (await _user(m.from_user.id))["lang"]
    await m.answer(t(lang, "proof_prompt"), reply_markup=kb.proof_kb(lang))


@router.callback_query(F.data == "sell:ask")
async def sell_ask(cb: CallbackQuery, state: FSMContext):
    u = await _user(cb.from_user.id)
    lang = u["lang"]
    d = LAST.get(cb.from_user.id)
    if not d or not d.get("lead_id"):
        await screen(cb, "logo", t(lang, "sell_no_data"), kb.back_kb(lang))
    else:
        await state.set_state(Sell.ask)
        text = t(lang, "ask_prompt").replace("%CUR%", f"{currency.CURRENCIES[u['currency']]} {u['currency']}")
        await screen(cb, "logo", text, kb.sell_back_kb(lang))
    await cb.answer()


@router.message(Sell.ask)
async def got_ask(m: Message, state: FSMContext):
    u = await _user(m.from_user.id)
    lang, cur = u["lang"], u["currency"]
    d = LAST.get(m.from_user.id)
    if not d or not d.get("lead_id"):
        await state.clear()
        return await m.answer(t(lang, "sell_no_data"))
    try:
        val = float((m.text or "").replace(" ", "").replace(",", "."))
        assert val > 0
    except (ValueError, AssertionError):
        return await m.answer(t(lang, "ask_bad"))
    rub = val / (await currency.get_rates()).get(cur, 1)
    ask_txt = await currency.fmt(rub, cur)
    pct = (rub / d["total_rub"] - 1) * 100
    key = "ask_low" if rub <= d["total_rub"] else ("ask_mid" if rub <= d["total_rub"] * 1.1 else "ask_high")
    d["ask_txt"], d["ask_rub"] = ask_txt, rub
    await db.set_lead_field(d["lead_id"], ask_rub=rub, ask_txt=ask_txt)
    await state.clear()
    await admin.notify_text(m.bot, f"💬 Заявка #{d['lead_id']}: продавец просит <b>{ask_txt}</b> "
                                   f"({pct:+.0f}% к оценке бота)")
    text = (t(lang, "ask_result").replace("%ASK%", ask_txt).replace("%PRICE%", d["total_txt"])
            .replace("%V%", t(lang, key).replace("%P%", f"{abs(pct):.0f}")))
    await send_screen(m, "logo", text, kb.sell_back_kb(lang))


# ---------- сравнение ----------
@router.message(Cmp.first)
async def cmp_first(m: Message, state: FSMContext):
    lang = (await _user(m.from_user.id))["lang"]
    tag = brawl_api.normalize_tag(m.text or "")
    if not tag:
        return await m.answer(t(lang, "bad_tag"))
    if not _rate_ok(m.from_user.id):
        return await m.answer(t(lang, "slow_down"))
    player = await _fetch(m, tag, lang)
    if not player:
        return
    await state.update_data(p1=player, t1=tag)
    await state.set_state(Cmp.second)
    await m.answer(t(lang, "cmp_second"))


@router.message(Cmp.second)
async def cmp_second(m: Message, state: FSMContext):
    u = await _user(m.from_user.id)
    lang, cur = u["lang"], u["currency"]
    tag = brawl_api.normalize_tag(m.text or "")
    if not tag:
        return await m.answer(t(lang, "bad_tag"))
    p2 = await _fetch(m, tag, lang)
    if not p2:
        return
    data = await state.get_data()
    await state.clear()
    prices = await db.get_prices()
    items = [(data["p1"], data["t1"], "1️⃣"), (p2, tag, "2️⃣")]
    results = [pricing.calculate(p, prices) for p, _, _ in items]
    lines = [t(lang, "cmp_title")]
    for (p, tg, num), r in zip(items, results):
        lines.append(f"{num} <b>{html.escape(p.get('name', '?'))}</b> · #{tg}")
        lines.append(f"      🏆 {_n(p.get('highestTrophies', 0))} · 🧩 {len(p.get('brawlers', []))}"
                     f" · 💵 <b>{await currency.fmt(r['total'], cur)}</b>")
    diff = results[0]["total"] - results[1]["total"]
    lines.append("")
    if abs(diff) < 1:
        lines.append(f"🤝 {t(lang, 'cmp_equal')}")
    else:
        winner = items[0][2] if diff > 0 else items[1][2]
        lines.append(f"📊 {t(lang, 'cmp_diff')}: <b>{await currency.fmt(abs(diff), cur)}</b> · "
                     f"{winner} {t(lang, 'cmp_better')}")
    await send_screen(m, "logo", "\n".join(lines), kb.back_kb(lang))


# ---------- подписка, промокоды, inline ----------
@router.callback_query(F.data == "sub:check")
async def sub_check(cb: CallbackQuery):
    lang = (await _user(cb.from_user.id))["lang"]
    _SUB_OK.pop(cb.from_user.id, None)
    if await _subscribed(cb.bot, cb.from_user.id):
        await screen(cb, "logo", t(lang, "welcome"), kb.main_kb(lang))
        await cb.answer()
    else:
        await cb.answer(t(lang, "sub_no"), show_alert=True)


@router.callback_query(F.data == "bonus:promo")
async def bonus_promo(cb: CallbackQuery, state: FSMContext):
    lang = (await _user(cb.from_user.id))["lang"]
    await state.set_state(Promo.code)
    await screen(cb, "logo", t(lang, "promo_prompt"), kb.back_kb(lang))
    await cb.answer()


@router.message(Promo.code)
async def got_promo(m: Message, state: FSMContext):
    lang = (await _user(m.from_user.id))["lang"]
    status, pct = await db.use_promo((m.text or "").strip().upper(), m.from_user.id)
    if status == "none":
        return await m.answer(t(lang, "promo_bad"))
    await state.clear()
    text = {"ok": t(lang, "promo_ok").replace("%B%", f"{pct:g}"),
            "used": t(lang, "promo_used"), "empty": t(lang, "promo_empty")}[status]
    await send_screen(m, "logo", text, kb.back_kb(lang))


@router.inline_query()
async def inline(q: InlineQuery):
    u = await db.get_user(q.from_user.id) or {"lang": "ru", "currency": "RUB"}
    lang, cur = u["lang"], u["currency"]

    def art(rid, title, desc, text):
        return InlineQueryResultArticle(id=rid, title=title, description=desc,
                                        input_message_content=InputTextMessageContent(message_text=text, parse_mode="HTML"))

    tag = brawl_api.normalize_tag(q.query or "")
    if not tag:
        hint = t(lang, "inline_hint")
        return await q.answer([art("hint", "Price Brawl", hint, hint)], cache_time=5, is_personal=True)
    if not _rate_ok(q.from_user.id, limit=10):
        msg = t(lang, "slow_down")
        return await q.answer([art("slow", "⏳", msg, msg)], cache_time=5, is_personal=True)
    try:
        player = await brawl_api.get_player(tag)
    except (brawl_api.PlayerNotFound, brawl_api.ApiError):
        msg = t(lang, "inline_notfound")
        return await q.answer([art("nf", "❌", msg, msg)], cache_time=5, is_personal=True)
    res = pricing.calculate(player, await db.get_prices())
    name = player.get("name", "?")
    highest = player.get("highestTrophies", 0)
    idx, emoji = pricing.tier(highest)
    total_txt = await currency.fmt(res["total"], cur)
    me = await q.bot.me()
    text = "\n".join([f"<b>{html.escape(name)}</b> · #{tag}", f"{emoji} {t(lang, 'tier_' + str(idx))}",
                      f"🏆 {_n(highest)} · 🧩 {len(player.get('brawlers', []))}",
                      f"{t(lang, 'res_total')}: <b>{total_txt}</b>",
                      f"{t(lang, 'res_range')}: {await currency.fmt(res['low'], cur)} – {await currency.fmt(res['high'], cur)}",
                      "", f"👉 @{me.username}"])
    await q.answer([art(f"r{tag}", f"{name} · {total_txt}", t(lang, "inline_desc"), text)],
                   cache_time=30, is_personal=True)
