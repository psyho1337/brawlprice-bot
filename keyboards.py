from urllib.parse import quote
from aiogram.utils.keyboard import InlineKeyboardBuilder

import config
from i18n import t, LANGS
from currency import CURRENCIES
from pricing import LEAGUES, SKIN_BRACKETS


def manager_url(text=None):
    base = f"https://t.me/{config.MANAGER_USERNAME}"
    return base + (f"?text={quote(text)}" if text else "")


def lang_kb():
    b = InlineKeyboardBuilder()
    for code, name in LANGS.items():
        b.button(text=name, callback_data=f"lang:{code}")
    b.adjust(1)
    return b.as_markup()


def currency_kb(lang):
    b = InlineKeyboardBuilder()
    for code, sym in CURRENCIES.items():
        b.button(text=f"{sym} {code}", callback_data=f"cur:{code}")
    b.button(text=t(lang, "btn_back"), callback_data="menu:settings")
    b.adjust(3, 3, 2, 1)
    return b.as_markup()


def settings_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_lang"), callback_data="menu:lang")
    b.button(text=t(lang, "btn_currency"), callback_data="menu:currency")
    b.button(text=t(lang, "btn_back"), callback_data="menu:main")
    b.adjust(2, 1)
    return b.as_markup()


def back_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_back"), callback_data="menu:main")
    return b.as_markup()


# ---- мастер оценки: каждый шаг одним нажатием ----
def skins_kb(lang):
    b = InlineKeyboardBuilder()
    for br in SKIN_BRACKETS:
        b.button(text=t(lang, "sk_" + br), callback_data=f"sk:{br}")
    b.adjust(3, 3)
    return b.as_markup()


def league_kb(lang):
    b = InlineKeyboardBuilder()
    for name in LEAGUES:
        b.button(text=t(lang, "lg_" + name), callback_data=f"lg:{name}")
    b.button(text=t(lang, "lg_skip"), callback_data="lg:none")
    b.adjust(2, 2, 2, 2, 1)
    return b.as_markup()


# ---- продажа ----
def prot_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_yes"), callback_data="sell:prot:yes")
    b.button(text=t(lang, "btn_no"), callback_data="sell:prot:no")
    b.button(text=t(lang, "btn_unknown"), callback_data="sell:prot:unk")
    b.adjust(2, 1)
    return b.as_markup()


def mail_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_mail_yes"), callback_data="sell:mail:yes")
    b.button(text=t(lang, "btn_mail_no"), callback_data="sell:mail:no")
    b.button(text=t(lang, "btn_unknown"), callback_data="sell:mail:unk")
    b.adjust(2, 1)
    return b.as_markup()


def contact_kb(lang, url):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_contact"), url=url)
    b.button(text=t(lang, "btn_menu"), callback_data="menu:main")
    b.adjust(1, 1)
    return b.as_markup()


def result_kb(lang, url, rare=False):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_sell"), callback_data="sell:start")
    b.button(text=t(lang, "btn_rare_manager" if rare else "btn_manager"), url=url)
    b.button(text=t(lang, "btn_share"), callback_data="share:last")
    b.button(text=t(lang, "btn_watch"), callback_data="watch:last")
    b.button(text=t(lang, "btn_new"), callback_data="menu:appraise")
    b.button(text=t(lang, "btn_menu"), callback_data="menu:main")
    b.adjust(1, 1, 2, 2)
    return b.as_markup()


def rare_kb(lang, items, selected, other):
    b = InlineKeyboardBuilder()
    shown = items[:12]
    for it in shown:
        mark = "✅ " if it["id"] in selected else ""
        b.button(text=f"{mark}{it['name']}", callback_data=f"rr:t:{it['id']}")
    b.button(text=t(lang, "btn_rare_other_on" if other else "btn_rare_other"), callback_data="rr:o")
    b.button(text=t(lang, "btn_rare_ok"), callback_data="rr:ok")
    b.button(text=t(lang, "btn_rare_none"), callback_data="rr:none")
    n = len(shown)
    b.adjust(*([2] * (n // 2) + ([1] if n % 2 else [])), 1, 2)
    return b.as_markup()


def sell_done_kb(lang, url):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_contact"), url=url)
    b.button(text=t(lang, "btn_proof"), callback_data="sell:proof")
    b.button(text=t(lang, "btn_ask"), callback_data="sell:ask")
    b.button(text=t(lang, "btn_check"), callback_data="sell:check")
    b.button(text=t(lang, "btn_menu"), callback_data="menu:main")
    b.adjust(1, 2, 1, 1)
    return b.as_markup()


def sell_back_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_back_ready"), callback_data="sell:ready")
    return b.as_markup()


def proof_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_proof_done"), callback_data="sell:ready")
    return b.as_markup()


def recalc_kb(lang, tag):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_recalc"), callback_data=f"rw:{tag}")
    return b.as_markup()


def main_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_appraise"), callback_data="menu:appraise")
    b.button(text=t(lang, "btn_compare"), callback_data="menu:compare")
    b.button(text=t(lang, "btn_history"), callback_data="menu:history")
    b.button(text=t(lang, "btn_stats"), callback_data="menu:stats")
    b.button(text=t(lang, "btn_bonus"), callback_data="menu:bonus")
    b.button(text=t(lang, "btn_manager"), url=manager_url())
    b.button(text=t(lang, "btn_help"), callback_data="menu:help")
    b.button(text=t(lang, "btn_settings"), callback_data="menu:settings")
    b.adjust(1, 2, 2, 2, 1)
    return b.as_markup()


def sub_kb(lang, url):
    b = InlineKeyboardBuilder()
    if url:
        b.button(text=t(lang, "btn_subscribe"), url=url)
    b.button(text=t(lang, "btn_subscribed"), callback_data="sub:check")
    b.adjust(1)
    return b.as_markup()


def bonus_kb(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_promo"), callback_data="bonus:promo")
    b.button(text=t(lang, "btn_back"), callback_data="menu:main")
    b.adjust(1)
    return b.as_markup()
