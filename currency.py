import time
import aiohttp

CURRENCIES = {"RUB": "₽", "USD": "$", "EUR": "€", "UAH": "₴", "KZT": "₸", "PLN": "zł", "TRY": "₺", "GBP": "£"}
_FALLBACK = {"RUB": 1, "USD": 0.011, "EUR": 0.010, "UAH": 0.46, "KZT": 5.6, "PLN": 0.044, "TRY": 0.45, "GBP": 0.0085}
_cache = {"t": 0, "rates": dict(_FALLBACK)}

async def get_rates():
    if time.time() - _cache["t"] < 3600:
        return _cache["rates"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://open.er-api.com/v6/latest/RUB",
                             timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
                rates = {c: data["rates"][c] for c in CURRENCIES}
                _cache.update(t=time.time(), rates=rates)
    except Exception:
        pass
    return _cache["rates"]

async def fmt(rub: float, cur: str) -> str:
    v = rub * (await get_rates()).get(cur, 1)
    s = f"{v:,.0f}" if v >= 100 else f"{v:,.2f}"
    return f"{s.replace(',', ' ')} {CURRENCIES[cur]}"
