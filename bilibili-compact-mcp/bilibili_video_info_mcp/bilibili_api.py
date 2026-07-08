import logging
import math
import os
import re
import xml.etree.ElementTree as ET

import requests

from . import wbi

logger = logging.getLogger(__name__)

# Bilibili API endpoints
API_GET_VIEW_INFO = "https://api.bilibili.com/x/web-interface/view"
API_GET_SUBTITLE = "https://api.bilibili.com/x/player/wbi/v2"
API_GET_DANMAKU_XML = "https://api.bilibili.com/x/v1/dm/list.so"
API_GET_DANMAKU_SEG = "https://api.bilibili.com/x/v2/dm/web/seg.so"
API_GET_COMMENTS = "https://api.bilibili.com/x/v2/reply/wbi/main"
API_GET_PLAYURL = "https://api.bilibili.com/x/player/wbi/playurl"

REQUEST_TIMEOUT = 15
DANMAKU_SEG_DURATION = 360  # seg.so serves danmaku in 6-minute segments

# Default Headers for requests
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/'
}


def has_sessdata() -> bool:
    return bool(os.getenv("SESSDATA"))


def _get_headers():
    # SESSDATA is optional: only the subtitle list requires a logged-in
    # session; view/danmaku/comments work anonymously.
    headers = DEFAULT_HEADERS.copy()
    sessdata = os.getenv("SESSDATA")
    if sessdata:
        headers['Cookie'] = f'SESSDATA={sessdata}'
    return headers


def extract_bvid(url):
    # 先尝试直接从URL中提取BV号
    match = re.search(r'BV[a-zA-Z0-9_]+', url)
    if match:
        return match.group(0)

    # 如果是短链接（如b23.tv），则跟踪重定向获取完整URL
    if 'b23.tv' in url:
        try:
            response = requests.head(url, headers=_get_headers(), allow_redirects=True,
                                     timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                # 获取最终重定向后的URL
                final_url = response.url
                match = re.search(r'BV[a-zA-Z0-9_]+', final_url)
                if match:
                    return match.group(0)
        except requests.RequestException as e:
            logger.warning("Error resolving short URL: %s", e)

    return None


def get_video_view(bvid):
    """Fetches the full view info (title, desc, stat, pages, ...) for a bvid."""
    try:
        response = requests.get(API_GET_VIEW_INFO, params={'bvid': bvid},
                                headers=_get_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if data['code'] != 0:
            return None, {'error': 'Failed to get video info', 'details': data}
        return data['data'], None
    except requests.RequestException as e:
        return None, {'error': f'Failed to fetch video details: {e}'}


def select_page_cid(video_data, page=1):
    """Resolves the cid of the given 1-based part (分P) number."""
    pages = video_data.get('pages') or []
    for p in pages:
        if p.get('page') == page:
            return p.get('cid'), None
    if page == 1:
        return video_data.get('cid'), None
    return None, {'error': f'分P {page} 不存在，该视频共 {len(pages)} 个分P'}


def get_subtitles(aid, cid, lang=None):
    """Fetches one subtitle track (with timestamps) for a given aid and cid.

    Prefers the requested lang, otherwise a zh variant, otherwise the first
    track. Returns (result_dict, available_langs, error).
    """
    headers = _get_headers()
    try:
        params = {'aid': aid, 'cid': cid}
        response = requests.get(API_GET_SUBTITLE, params=params, headers=headers,
                                timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        tracks = (data.get('data', {}).get('subtitle', {}) or {}).get('subtitles') or []
        available = [t.get('lan') for t in tracks]
        if not tracks:
            return None, available, None

        selected = None
        if lang:
            selected = next((t for t in tracks if t.get('lan') == lang), None)
            if not selected:
                return None, available, {'error': f'没有语言为 {lang} 的字幕，可用: {available}'}
        else:
            # 默认中文优先（zh-CN / zh-Hans / ai-zh 等），否则取第一条
            selected = next((t for t in tracks if 'zh' in (t.get('lan') or '')), tracks[0])

        subtitle_url = selected.get('subtitle_url') or ''
        if subtitle_url.startswith('//'):
            subtitle_url = f'https:{subtitle_url}'
        response_content = requests.get(subtitle_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response_content.raise_for_status()
        body = response_content.json().get('body', [])
        lines = [{'t': item.get('from'), 'text': item.get('content', '')} for item in body]
        return {'lan': selected.get('lan'), 'lines': lines}, available, None
    except requests.RequestException as e:
        return None, [], {'error': f'Could not fetch subtitles: {e}'}


# --- danmaku: protobuf seg.so (primary) with XML list.so fallback ---

def _pb_read_varint(buf, i):
    result = 0
    shift = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, i
        shift += 7


def _pb_fields(buf):
    """Yields (field_no, wire_type, value) over a protobuf message buffer."""
    i = 0
    n = len(buf)
    while i < n:
        key, i = _pb_read_varint(buf, i)
        fno, wt = key >> 3, key & 7
        if wt == 0:
            val, i = _pb_read_varint(buf, i)
        elif wt == 2:
            ln, i = _pb_read_varint(buf, i)
            val = buf[i:i + ln]
            i += ln
        elif wt == 5:
            val = buf[i:i + 4]
            i += 4
        elif wt == 1:
            val = buf[i:i + 8]
            i += 8
        else:
            raise ValueError(f'unsupported wire type {wt}')
        yield fno, wt, val


def _parse_danmaku_elem(buf):
    """Parses one DanmakuElem: progress(2, ms) midHash(6) content(7) ctime(8)."""
    item = {'t': None, 'text': '', 'sent': None, 'user': None}
    for fno, wt, val in _pb_fields(buf):
        if fno == 2 and wt == 0:
            item['t'] = round(val / 1000, 2)
        elif fno == 6 and wt == 2:
            item['user'] = val.decode('utf-8', errors='ignore')
        elif fno == 7 and wt == 2:
            item['text'] = val.decode('utf-8', errors='ignore')
        elif fno == 8 and wt == 0:
            item['sent'] = val
    return item


def _get_danmaku_seg(cid, duration):
    """Fetches all danmaku via the segmented protobuf API (DmSegMobileReply)."""
    headers = _get_headers()
    segments = max(1, math.ceil((duration or 0) / DANMAKU_SEG_DURATION))
    items = []
    for seg_index in range(1, segments + 1):
        params = {'type': 1, 'oid': cid, 'segment_index': seg_index}
        response = requests.get(API_GET_DANMAKU_SEG, params=params, headers=headers,
                                timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        if 'octet-stream' not in response.headers.get('Content-Type', ''):
            raise ValueError(f'unexpected content type for seg {seg_index}: '
                             f'{response.headers.get("Content-Type")}')
        for fno, wt, val in _pb_fields(response.content):
            if fno == 1 and wt == 2:  # repeated DanmakuElem elems = 1
                items.append(_parse_danmaku_elem(val))
    return items


def _get_danmaku_xml(cid):
    """Legacy XML API (returns the most recent danmaku, capped)."""
    response = requests.get(API_GET_DANMAKU_XML, params={'oid': cid},
                            headers=_get_headers(), timeout=REQUEST_TIMEOUT)
    content = response.content.decode('utf-8', errors='ignore')
    root = ET.fromstring(content)
    items = []
    for d in root.findall('d'):
        p = (d.get('p') or '').split(',')
        items.append({
            't': round(float(p[0]), 2) if p and p[0] else None,
            'text': d.text or '',
            'sent': int(p[4]) if len(p) > 4 else None,
            'user': p[6] if len(p) > 6 else None,
        })
    return items


def get_danmaku(cid, duration=None, limit=1000):
    """Fetches danmaku from BOTH the segmented protobuf API and the legacy XML
    API, merged and deduplicated.

    实测（2026-07）两个接口返回的都是服务端筛选后的不同子集：seg 按权重精选、
    XML 偏最近且有条数上限，交集极小，并集覆盖面明显更大，故双源合并。

    Returns ({'source', 'total', 'returned', 'sampled', 'items'}, error).
    Items over `limit` are uniformly sampled across the timeline.
    """
    items, sources, errors = [], [], []
    seen = set()
    for name, fetch in (('seg', lambda: _get_danmaku_seg(cid, duration)),
                        ('xml', lambda: _get_danmaku_xml(cid))):
        try:
            fetched = fetch()
        except (requests.RequestException, ET.ParseError, ValueError) as e:
            logger.warning('%s danmaku fetch failed: %s', name, e)
            errors.append(f'{name}: {e}')
            continue
        sources.append(name)
        for it in fetched:
            key = (it['text'], it['sent'], it['user'])
            if key not in seen:
                seen.add(key)
                items.append(it)
    if not sources:
        return None, {'error': 'Failed to get danmaku: ' + '; '.join(errors)}
    items.sort(key=lambda x: x['t'] if x['t'] is not None else 0)
    source = '+'.join(sources)

    total = len(items)
    sampled = False
    if limit and total > limit:
        stride = total / limit
        items = [items[int(i * stride)] for i in range(limit)]
        sampled = True
    return {'source': source, 'total': total, 'returned': len(items),
            'sampled': sampled, 'items': items}, None


def get_comments(aid, limit=20, mode=3):
    """Fetches the top hot comments for a given aid via the WBI-signed API.

    mode=3 按热度、mode=2 按时间。B站已把旧 x/v2/reply 降级为仅返回 3 条预览，
    需走 WBI 签名的 reply/wbi/main 才能拿到完整首页（约 20 条）。更深翻页需 buvid
    激活反爬处理，本 compact 版不做，仅返回热度最高的首页并按 limit 截断。
    """
    headers = _get_headers()
    comments_list = []
    try:
        params = wbi.sign({'type': 1, 'oid': aid, 'mode': mode})
        response = requests.get(API_GET_COMMENTS, params=params, headers=headers,
                                timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        comments_data = response.json()
        if comments_data.get('code') != 0:
            return [], {'error': f"API error {comments_data.get('code')}: {comments_data.get('message')}"}

        for comment in comments_data.get('data', {}).get('replies') or []:
            if comment.get('content', {}).get('message'):
                comments_list.append({
                    'user': comment.get('member', {}).get('uname', 'Unknown User'),
                    'content': comment['content']['message'],
                    'likes': comment.get('like', 0)
                })
        return comments_list[:limit] if limit else comments_list, None
    except requests.RequestException as e:
        return [], {'error': f'Failed to get comments: {e}'}


def get_audio_url(aid, cid):
    """Returns the best-bitrate DASH audio stream URL via the WBI-signed playurl.

    yt-dlp 的 B站 提取器过不了 WBI 风控(412),这里用自带 WBI 签名器直接取流。
    """
    try:
        params = wbi.sign({'avid': aid, 'cid': cid, 'qn': 0, 'fnval': 16, 'fourk': 1})
        response = requests.get(API_GET_PLAYURL, params=params, headers=_get_headers(),
                                timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if data.get('code') != 0:
            return None, {'error': f"playurl error {data.get('code')}: {data.get('message')}"}
        audios = (data.get('data', {}).get('dash', {}) or {}).get('audio') or []
        if not audios:
            return None, {'error': 'no audio stream in playurl response'}
        best = max(audios, key=lambda a: a.get('bandwidth', 0))
        return best['baseUrl'], None
    except requests.RequestException as e:
        return None, {'error': f'failed to fetch audio url: {e}'}


def download_audio(url, dest_path):
    """Streams a DASH audio URL to dest_path (referer header defeats 防盗链)."""
    try:
        with requests.get(url, headers=_get_headers(), stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        return None
    except requests.RequestException as e:
        return {'error': f'audio download failed: {e}'}
