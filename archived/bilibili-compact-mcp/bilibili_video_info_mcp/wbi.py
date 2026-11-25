"""Bilibili WBI signing (w_rid/wts).

新版接口（如评论 x/v2/reply/wbi/main）要求 WBI 签名，否则返回 -403。签名算法：
从 nav 接口取 img_key+sub_key，按固定 mixinKeyEncTab 打乱重排取前 32 位得 mixin_key，
再对 (排序后的 query + mixin_key) 做 md5 得 w_rid。算法来源为公开的
bilibili-API-collect 文档，非破解，仅正常请求所需的参数签名。
"""

import logging
import time
import urllib.parse
from functools import reduce
from hashlib import md5

import requests

logger = logging.getLogger(__name__)

API_NAV = "https://api.bilibili.com/x/web-interface/nav"
_NAV_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
}

# mixinKeyEncTab: 官方公开的字符重排表
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

# mixin_key 每日轮换，缓存一段时间避免每次调用都打 nav 接口
_CACHE_TTL = 6 * 3600
_cached_mixin_key = None
_cached_at = 0.0


def _get_mixin_key(orig: str) -> str:
    return reduce(lambda s, i: s + orig[i], _MIXIN_KEY_ENC_TAB, '')[:32]


def _fetch_mixin_key() -> str:
    resp = requests.get(API_NAV, headers=_NAV_HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json().get('data', {})
    img_url = data['wbi_img']['img_url']
    sub_url = data['wbi_img']['sub_url']
    img_key = img_url.rsplit('/', 1)[1].split('.')[0]
    sub_key = sub_url.rsplit('/', 1)[1].split('.')[0]
    return _get_mixin_key(img_key + sub_key)


def _mixin_key() -> str:
    global _cached_mixin_key, _cached_at
    now = time.time()
    if _cached_mixin_key is None or now - _cached_at > _CACHE_TTL:
        _cached_mixin_key = _fetch_mixin_key()
        _cached_at = now
    return _cached_mixin_key


def sign(params: dict) -> dict:
    """Returns a copy of params with wts and w_rid added (WBI-signed)."""
    signed = dict(params)
    signed['wts'] = round(time.time())
    signed = dict(sorted(signed.items()))
    signed = {k: ''.join(c for c in str(v) if c not in "!'()*") for k, v in signed.items()}
    query = urllib.parse.urlencode(signed)
    signed['w_rid'] = md5((query + _mixin_key()).encode()).hexdigest()
    return signed
