"""Bilibili WBI signing (w_rid/wts).

算法来源为公开的 bilibili-API-collect 文档，非破解，仅正常请求所需的参数签名。
从 bilibili-compact-mcp 提炼，供 playurl 等接口使用。
"""

from __future__ import annotations

import logging
import time
import urllib.parse
from functools import reduce
from hashlib import md5

import requests

logger = logging.getLogger(__name__)

API_NAV = "https://api.bilibili.com/x/web-interface/nav"
_NAV_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

_CACHE_TTL = 6 * 3600
_cached_mixin_key: str | None = None
_cached_at = 0.0


class WbiError(Exception):
    """Raised when WBI key fetch / parse fails."""


def _get_mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], _MIXIN_KEY_ENC_TAB, "")[:32]


def _key_from_url(url: str) -> str:
    # .../xx/abcdef1234.png → abcdef1234
    name = url.rsplit("/", 1)[-1]
    return name.split(".", 1)[0]


def _fetch_mixin_key() -> str:
    try:
        resp = requests.get(API_NAV, headers=_NAV_HEADERS, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise WbiError("nav response missing data object")
        wbi_img = data.get("wbi_img")
        if not isinstance(wbi_img, dict):
            raise WbiError("nav response missing wbi_img")
        img_url = wbi_img.get("img_url") or ""
        sub_url = wbi_img.get("sub_url") or ""
        if not img_url or not sub_url:
            raise WbiError("nav response missing img_url/sub_url")
        img_key = _key_from_url(img_url)
        sub_key = _key_from_url(sub_url)
        if not img_key or not sub_key:
            raise WbiError("could not parse wbi keys from urls")
        return _get_mixin_key(img_key + sub_key)
    except requests.RequestException as e:
        raise WbiError(f"nav request failed: {e}") from e
    except (TypeError, ValueError, KeyError, IndexError) as e:
        raise WbiError(f"nav parse failed: {e}") from e


def _mixin_key() -> str:
    global _cached_mixin_key, _cached_at
    now = time.time()
    if _cached_mixin_key is None or now - _cached_at > _CACHE_TTL:
        _cached_mixin_key = _fetch_mixin_key()
        _cached_at = now
    return _cached_mixin_key


def sign(params: dict) -> dict:
    """Returns a copy of params with wts and w_rid added (WBI-signed).

    Raises WbiError if mixin key cannot be obtained.
    """
    signed = dict(params)
    signed["wts"] = round(time.time())
    signed = dict(sorted(signed.items()))
    signed = {
        k: "".join(c for c in str(v) if c not in "!'()*") for k, v in signed.items()
    }
    query = urllib.parse.urlencode(signed)
    signed["w_rid"] = md5((query + _mixin_key()).encode()).hexdigest()
    return signed


def clear_cache() -> None:
    """Test helper: drop cached mixin key."""
    global _cached_mixin_key, _cached_at
    _cached_mixin_key = None
    _cached_at = 0.0
