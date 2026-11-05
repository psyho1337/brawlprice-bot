import config

SKIN_BRACKETS = ["none", "1_25", "26_75", "76_150", "151_300", "300_plus"]
LEAGUES = ["bronze", "silver", "gold", "diamond", "mythic", "legendary", "masters", "pro"]

# Базовые цены в рублях. Это стартовые значения: сверь с реальным рынком
# и поправь командой /setprice (только для админов).
DEFAULT_PRICES = {
    "markup": config.MARKUP,   # общая наценка (1.10 = +10%)
    "trophies_per_1000": 17,   # за каждые 1000 рекордных кубков
    "brawler": 2,
    "power11": 2.5,            # бонус за бойца 11 уровня силы
    "star_power": 1.2,
    "gadget": 0.9,
    "hypercharge": 2,
    "gear": 0.3,
    # скины: небольшая прибавка по диапазону (редкое оценивает менеджер вручную)
    "skins_1_25": 10, "skins_26_75": 30, "skins_76_150": 70, "skins_151_300": 130, "skins_300_plus": 200,
    # бонус за максимальную лигу: всё ниже легендарной почти ничего не стоит
    "league_bronze": 0, "league_silver": 0, "league_gold": 0, "league_diamond": 0,
    "league_mythic": 0, "league_legendary": 80, "league_masters": 350, "league_pro": 900,
    # с какой доли оценки начинать торг
    "bargain_start": 0.85,
    # реферальный бонус к оценке: за каждого друга и потолок (в процентах; 0 = выключить)
    "ref_bonus_per": 0.5, "ref_bonus_max": 3,
}

# Класс аккаунта считается ТОЛЬКО по рекордным кубкам (это не лига из игры)
TIERS = [(0, "🌱"), (10000, "⚔️"), (25000, "🛡️"), (40000, "💠"), (60000, "🔱")]

def tier(trophies: int):
    idx = max(i for i, (lim, _) in enumerate(TIERS) if trophies >= lim)
    return idx, TIERS[idx][1]

def top_brawlers(player: dict, n: int = 3):
    brs = sorted(player.get("brawlers", []), key=lambda b: b.get("trophies", 0), reverse=True)[:n]
    return [(str(b.get("name", "?")).title(), b.get("trophies", 0)) for b in brs]

def calculate(player: dict, prices: dict, skins: str = None, league: str = None, markup: float = None, rare_sum: float = 0):
    markup = prices.get("markup", config.MARKUP) if markup is None else markup
    brs = player.get("brawlers", [])
    trophies = player.get("highestTrophies", 0)
    rows = [("trophies", trophies, trophies / 1000 * prices["trophies_per_1000"])]
    counts = {
        "brawler": len(brs),
        "power11": sum(1 for b in brs if b.get("power", 0) >= 11),
        "star_power": sum(len(b.get("starPowers", [])) for b in brs),
        "gadget": sum(len(b.get("gadgets", [])) for b in brs),
        "hypercharge": sum(len(b.get("hyperCharges", [])) for b in brs),
        "gear": sum(len(b.get("gears", [])) for b in brs),
    }
    for key, n in counts.items():
        rows.append((key, n, n * prices[key]))
    if skins in SKIN_BRACKETS and skins != "none":
        rows.append(("skins_" + skins, 1, prices["skins_" + skins]))
    if league in LEAGUES:
        rows.append(("league", 1, prices["league_" + league]))
    base = sum(r[2] for r in rows)
    total = base * markup + rare_sum
    if rare_sum:
        rows.append(("rare_items", 1, rare_sum))
    return {"rows": rows, "base": base, "total": total, "low": total * 0.9,
            "high": total * 1.1, "offer": total * prices["bargain_start"]}


def upgrade_tips(player: dict, prices: dict):
    """Сколько примерно можно добавить к цене прокачкой (грубая оценка: по 2 гаджета и 2 звёздные силы на бойца)."""
    m = prices.get("markup", config.MARKUP)
    brs = player.get("brawlers", [])
    not11 = sum(1 for b in brs if b.get("power", 0) < 11)
    gad = sum(max(0, 2 - len(b.get("gadgets", []))) for b in brs)
    sps = sum(max(0, 2 - len(b.get("starPowers", []))) for b in brs)
    return {"not11": not11, "p11": not11 * prices["power11"] * m,
            "gadgets": gad, "sps": sps, "g": gad * prices["gadget"] * m, "s": sps * prices["star_power"] * m}


def apply_bonus(res: dict, pct: float):
    """Бонус к оценке в процентах (промокод или рефералы)."""
    if not pct:
        return res
    k = 1 + pct / 100
    out = dict(res)
    for key in ("total", "low", "high", "offer"):
        out[key] = res[key] * k
    return out
