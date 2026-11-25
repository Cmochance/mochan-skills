"""Bilibili API helpers: view, playurl audio, subtitles.

从 bilibili-compact-mcp 提炼；字幕 lines 保留 from/to（秒）。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from . import wbi

logger = logging.getLogger(__name__)

API_GET_VIEW_INFO = "https://api.bilibili.com/x/web-interface/view"
API_GET_SUBTITLE = "https://api.bilibili.com/x/player/wbi/v2"
API_GET_PLAYURL = "https://api.bilibili.com/x/player/wbi/playurl"

REQUEST_TIMEOUT = 15

_SHORT_LINK_HOSTS = frozenset({"b23.tv", "www.b23.tv", "bili2233.cn", "www.bili2233.cn"})

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


def has_sessdata() -> bool:
    return bool(os.getenv("SESSDATA"))


def anonymous_headers() -> dict[str, str]:
    """UA + Referer only — for CDN / short-link resolve (no Cookie)."""
    return DEFAULT_HEADERS.copy()


def api_headers() -> dict[str, str]:
    """Headers for api.bilibili.com (includes SESSDATA when set)."""
    headers = DEFAULT_HEADERS.copy()
    sessdata = os.getenv("SESSDATA")
    if sessdata:
        headers["Cookie"] = f"SESSDATA={sessdata}"
    return headers


# Back-compat alias used in older call sites / tests
_get_headers = api_headers


def _payload(data: dict | None) -> dict:
    """Safe access to response JSON `data` field (may be null)."""
    if not isinstance(data, dict):
        return {}
    inner = data.get("data")
    return inner if isinstance(inner, dict) else {}


def extract_bvid(url_or_id: str) -> str | None:
    """Extract BV id from a full URL, short link, or bare BV string."""
    text = (url_or_id or "").strip()
    if not text:
        return None

    # Bare BV id (no scheme) — allow direct match
    bare = re.fullmatch(r"BV[a-zA-Z0-9_]+", text)
    if bare:
        return bare.group(0)

    # Prefer BV on known bilibili hosts first
    match = re.search(r"BV[a-zA-Z0-9_]+", text)
    if match:
        try:
            host = (urlparse(text).hostname or "").lower()
        except ValueError:
            host = ""
        # If input looks like a full URL to a non-b23 host, trust the BV in path
        if not host or host.endswith("bilibili.com") or "bilibili" in host:
            return match.group(0)
        # BV appears in a non-bilibili URL (e.g. attacker?ref=b23.tv&BV...) — still
        # return the BV token if present; do NOT follow as short link with cookie.
        if not _is_short_link_url(text):
            return match.group(0)

    if _is_short_link_url(text):
        return _resolve_short_link(text)

    return match.group(0) if match else None


def _is_short_link_url(text: str) -> bool:
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https", ""):
        return False
    host = (parsed.hostname or "").lower()
    return host in _SHORT_LINK_HOSTS


def _resolve_short_link(text: str) -> str | None:
    """HEAD short link without SESSDATA; extract BV from final URL."""
    url = text if "://" in text else f"https://{text}"
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        if (parsed.hostname or "").lower() not in _SHORT_LINK_HOSTS:
            return None
        response = requests.head(
            url,
            headers=anonymous_headers(),
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
        )
        final_url = response.url
        found = re.search(r"BV[a-zA-Z0-9_]+", final_url)
        if found:
            return found.group(0)
    except requests.RequestException as e:
        logger.warning("Error resolving short URL: %s", e)
    return None


def get_video_view(bvid: str) -> tuple[dict | None, dict | None]:
    """Fetches full view info for a bvid. Returns (data, error)."""
    try:
        response = requests.get(
            API_GET_VIEW_INFO,
            params={"bvid": bvid},
            headers=api_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            return None, {
                "error": (
                    f"Failed to get video info code={data.get('code')}: "
                    f"{data.get('message')}"
                ),
                "details": data,
            }
        payload = _payload(data)
        if not payload:
            return None, {"error": "video view returned empty data", "details": data}
        return payload, None
    except requests.RequestException as e:
        return None, {"error": f"Failed to fetch video details: {e}"}
    except (TypeError, ValueError) as e:
        return None, {"error": f"Failed to parse video details: {e}"}


def select_page_cid(video_data: dict, page: int = 1) -> tuple[int | None, dict | None]:
    """Resolves the cid of the given 1-based part number."""
    pages = video_data.get("pages") or []
    for p in pages:
        if p.get("page") == page:
            return p.get("cid"), None
    if page == 1:
        return video_data.get("cid"), None
    return None, {"error": f"分P {page} 不存在，该视频共 {len(pages)} 个分P"}


def page_meta(video_data: dict, page: int = 1) -> dict[str, Any]:
    """Return duration/part title for a page."""
    pages = video_data.get("pages") or []
    for p in pages:
        if p.get("page") == page:
            return {
                "page": page,
                "part": p.get("part") or "",
                "duration": p.get("duration") or video_data.get("duration"),
                "cid": p.get("cid"),
            }
    return {
        "page": page,
        "part": video_data.get("title") or "",
        "duration": video_data.get("duration"),
        "cid": video_data.get("cid"),
    }


def list_subtitle_tracks(aid: int, cid: int) -> tuple[list[dict], dict | None]:
    """List available subtitle tracks without downloading body.

    Returns (tracks[{lan, lan_doc, subtitle_url}], error).
    """
    try:
        params = wbi.sign({"aid": aid, "cid": cid})
        response = requests.get(
            API_GET_SUBTITLE,
            params=params,
            headers=api_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            return [], {
                "error": (
                    f"subtitle API code={data.get('code')}: {data.get('message')}"
                )
            }
        payload = _payload(data)
        tracks = (payload.get("subtitle") or {}).get("subtitles") or []
        if not isinstance(tracks, list):
            tracks = []
        result = [
            {
                "lan": t.get("lan"),
                "lan_doc": t.get("lan_doc"),
                "subtitle_url": t.get("subtitle_url") or "",
            }
            for t in tracks
            if isinstance(t, dict)
        ]
        return result, None
    except requests.RequestException as e:
        return [], {"error": f"Could not list subtitles: {e}"}
    except (TypeError, ValueError, KeyError, IndexError) as e:
        return [], {"error": f"Could not parse subtitle list: {e}"}
    except wbi.WbiError as e:
        return [], {"error": f"WBI sign failed: {e}"}


def get_subtitles(
    aid: int, cid: int, lang: str | None = None
) -> tuple[dict | None, list[str], dict | None]:
    """Fetch one subtitle track with from/to timestamps.

    Returns (result_dict, available_langs, error).
    result: {lan, lines: [{t, to, text}]}  t/to in seconds.
    """
    try:
        tracks, err = list_subtitle_tracks(aid, cid)
        if err:
            return None, [], err
        available = [t.get("lan") for t in tracks if t.get("lan")]
        if not tracks:
            return None, available, None

        selected = None
        if lang:
            selected = next((t for t in tracks if t.get("lan") == lang), None)
            if not selected:
                return None, available, {
                    "error": f"没有语言为 {lang} 的字幕，可用: {available}",
                    "lang_not_found": True,
                }
        else:
            selected = next(
                (t for t in tracks if "zh" in (t.get("lan") or "")), tracks[0]
            )

        subtitle_url = selected.get("subtitle_url") or ""
        if subtitle_url.startswith("//"):
            subtitle_url = f"https:{subtitle_url}"
        if not subtitle_url:
            return None, available, {"error": "selected subtitle has empty url"}

        response_content = requests.get(
            subtitle_url, headers=anonymous_headers(), timeout=REQUEST_TIMEOUT
        )
        response_content.raise_for_status()
        body = response_content.json().get("body", []) or []
        lines = []
        for item in body:
            if not isinstance(item, dict):
                continue
            text = (item.get("content") or "").strip()
            if not text:
                continue
            start = item.get("from")
            end = item.get("to")
            lines.append(
                {
                    "t": float(start) if start is not None else 0.0,
                    "to": float(end) if end is not None else None,
                    "text": text,
                }
            )
        return {"lan": selected.get("lan"), "lines": lines}, available, None
    except requests.RequestException as e:
        return None, [], {"error": f"Could not fetch subtitles: {e}"}
    except (ValueError, TypeError, KeyError) as e:
        return None, [], {"error": f"Could not parse subtitles: {e}"}


def get_audio_url(aid: int, cid: int) -> tuple[str | None, dict | None]:
    """Return best-bitrate DASH audio stream URL via WBI-signed playurl."""
    try:
        params = wbi.sign(
            {"avid": aid, "cid": cid, "qn": 0, "fnval": 16, "fourk": 1}
        )
        response = requests.get(
            API_GET_PLAYURL,
            params=params,
            headers=api_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            return None, {
                "error": f"playurl error {data.get('code')}: {data.get('message')}"
            }
        audios = (_payload(data).get("dash") or {}).get("audio") or []
        if not audios:
            return None, {"error": "no audio stream in playurl response"}
        best = max(audios, key=lambda a: a.get("bandwidth", 0))
        url = best.get("baseUrl") or best.get("base_url")
        if not url:
            return None, {"error": "audio stream missing baseUrl"}
        return url, None
    except requests.RequestException as e:
        return None, {"error": f"failed to fetch audio url: {e}"}
    except wbi.WbiError as e:
        return None, {"error": f"WBI sign failed: {e}"}
    except (TypeError, ValueError, KeyError) as e:
        return None, {"error": f"failed to parse playurl: {e}"}


def download_audio(url: str, dest_path: str | Path) -> dict | None:
    """Stream a DASH audio URL to dest_path (Referer defeats hotlink protection)."""
    dest = Path(dest_path)
    try:
        with requests.get(
            url, headers=anonymous_headers(), stream=True, timeout=120
        ) as response:
            response.raise_for_status()
            with dest.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
        return None
    except requests.RequestException as e:
        return {"error": f"audio download failed: {e}"}


def normalize_cover_url(pic: str | None) -> str | None:
    """Normalize view.pic to an absolute https URL."""
    if not pic:
        return None
    url = pic.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    if url.startswith("https://"):
        return url
    return None


def download_cover(pic: str | None) -> tuple[bytes | None, str | None, dict | None]:
    """Download cover image bytes from view.pic.

    Returns (data, mime, error). mime from Content-Type when present.
    """
    url = normalize_cover_url(pic)
    if not url:
        return None, None, {"error": "no cover url"}
    try:
        response = requests.get(
            url, headers=anonymous_headers(), timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.content
        if not data:
            return None, None, {"error": "empty cover response"}
        mime = (response.headers.get("Content-Type") or "").split(";")[0].strip()
        if not mime.startswith("image/"):
            mime = None
        return data, mime, None
    except requests.RequestException as e:
        return None, None, {"error": f"cover download failed: {e}"}


def resolve_video(
    url_or_id: str, page: int = 1
) -> tuple[dict | None, int | None, dict | None]:
    """url -> (video_data, cid, error_dict). error_dict has 'error' key."""
    bvid = extract_bvid(url_or_id)
    if not bvid:
        return None, None, {"error": f"无法从输入提取 BV 号: {url_or_id}"}
    video_data, error = get_video_view(bvid)
    if error:
        return None, None, error
    cid, error = select_page_cid(video_data, page)
    if error:
        return video_data, None, error
    return video_data, cid, None
