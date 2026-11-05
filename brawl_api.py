import re
import time

import aiohttp

import config

class PlayerNotFound(Exception): ...
class ApiError(Exception): ...

_cache = {}   # tag -> (время, данные)


def normalize_tag(raw: str):
    tag = raw.strip().upper().replace("O", "0").lstrip("#")
    return tag if re.fullmatch(r"[0289PYLQGRJCUV]{3,15}", tag) else None


async def get_player(tag: str, fresh: bool = False) -> dict:
    now = time.time()
    if not fresh:
        hit = _cache.get(tag)
        if hit and now - hit[0] < config.API_CACHE_SECONDS:
            return hit[1]
    url = f"https://api.brawlstars.com/v1/players/%23{tag}"
    headers = {"Authorization": f"Bearer {config.BS_API_KEY}"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 404:
                    raise PlayerNotFound
                if r.status != 200:
                    raise ApiError(f"HTTP {r.status}")
                data = await r.json()
    except aiohttp.ClientError as e:
        raise ApiError(str(e))
    if len(_cache) > 2000:
        for k in sorted(_cache, key=lambda x: _cache[x][0])[:1000]:
            _cache.pop(k, None)
    _cache[tag] = (now, data)
    return data
