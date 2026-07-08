"""
Bilibili视频信息MCP服务器的核心模块
"""

import os
import tempfile

from mcp.server.fastmcp import FastMCP

from . import asr, bilibili_api

# 创建 FastMCP 服务器实例，命名为 BilibiliVideoInfo
mcp = FastMCP("BilibiliVideoInfo", dependencies=["requests"])


def _resolve_video(url: str, page: int = 1):
    """Resolves url -> (video_data, cid, error_message)."""
    bvid = bilibili_api.extract_bvid(url)
    if not bvid:
        return None, None, f"错误: 无法从 URL 提取 BV 号: {url}"
    video_data, error = bilibili_api.get_video_view(bvid)
    if error:
        return None, None, f"获取视频信息失败: {error['error']}"
    cid, error = bilibili_api.select_page_cid(video_data, page)
    if error:
        return video_data, None, error['error']
    return video_data, cid, None


@mcp.tool(
    annotations={
        "title": "获取视频信息",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_video_info(url: str) -> dict:
    """Get metadata of a Bilibili video: title, description, uploader, stats and part list

    Args:
        url: Bilibili video URL, e.g., https://www.bilibili.com/video/BV1x341177NN (b23.tv short links supported)

    Returns:
        Dict with bvid/aid, title, desc, dynamic, owner, duration (seconds), pubdate,
        stat (view/danmaku/reply/favorite/coin/share/like) and pages (part list, use
        the page number as the `page` argument of the other tools for multi-part videos)
    """
    video_data, _, error = _resolve_video(url)
    if error:
        return {"error": error}
    stat = video_data.get('stat', {})
    return {
        'bvid': video_data.get('bvid'),
        'aid': video_data.get('aid'),
        'title': video_data.get('title'),
        'desc': video_data.get('desc'),
        'dynamic': video_data.get('dynamic'),
        'owner': video_data.get('owner', {}).get('name'),
        'duration': video_data.get('duration'),
        'pubdate': video_data.get('pubdate'),
        'stat': {k: stat.get(k) for k in
                 ('view', 'danmaku', 'reply', 'favorite', 'coin', 'share', 'like')},
        'pages': [{'page': p.get('page'), 'part': p.get('part'), 'duration': p.get('duration')}
                  for p in video_data.get('pages') or []],
    }


@mcp.tool(
    annotations={
        "title": "获取视频字幕",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_subtitles(url: str, page: int = 1, lang: str | None = None) -> dict:
    """Get one subtitle track (with start timestamps in seconds) from a Bilibili video

    Note: listing subtitles requires the SESSDATA env var (a logged-in bilibili.com
    session cookie); without it Bilibili returns an empty subtitle list.

    Args:
        url: Bilibili video URL, e.g., https://www.bilibili.com/video/BV1x341177NN
        page: 1-based part number for multi-part (分P) videos, default 1
        lang: subtitle language code (e.g. zh-CN, ai-zh, en); default prefers a zh variant

    Returns:
        Dict with title, lan, available_languages and lines [{t: seconds, text}].
        If the video has no subtitles, returns title + description as fallback material.
    """
    video_data, cid, error = _resolve_video(url, page)
    if error:
        return {"error": error}

    result, available, error = bilibili_api.get_subtitles(video_data.get('aid'), cid, lang)
    if error:
        return {"error": f"获取字幕失败: {error['error']}", "available_languages": available}

    if not result:
        notice = "该视频没有CC字幕"
        if not bilibili_api.has_sessdata():
            notice += "（未配置 SESSDATA 环境变量：B站字幕列表需要登录态，匿名请求恒为空。"\
                      "如视频实际有字幕，请配置 SESSDATA 后重试）"
        return {
            'title': video_data.get('title'),
            'notice': notice,
            'description': f"{video_data.get('desc') or ''} {video_data.get('dynamic') or ''}".strip(),
        }

    return {
        'title': video_data.get('title'),
        'page': page,
        'lan': result['lan'],
        'available_languages': available,
        'lines': result['lines'],
    }


@mcp.tool(
    annotations={
        "title": "获取视频转录文本",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_transcript(url: str, page: int = 1, lang: str | None = None,
                         force_asr: bool = False) -> dict:
    """Get a spoken-content transcript, preferring CC subtitles and falling back to local ASR.

    对无 CC 字幕的视频,下载音频用本地 ASR 转写(默认 mlx-whisper via uvx,见 asr.py)。
    WARNING: ASR 路径较慢——需下载音频 + 转写,首次运行还会下载模型,可能耗时数分钟;
    调用方(MCP client)应容忍长耗时,或先用 get_subtitles 确认是否已有 CC 字幕。

    Args:
        url: Bilibili video URL, e.g., https://www.bilibili.com/video/BV1x341177NN
        page: 1-based part number for multi-part (分P) videos, default 1
        lang: language code; for CC 指定字幕轨,for ASR 指定识别语言(默认中文优先/zh)
        force_asr: 跳过 CC 字幕直接走音频转写(默认 False)

    Returns:
        Dict with title, source ('cc' = official subtitle | 'asr' = machine transcription)
        and lines [{t: seconds, text}]. source='asr' 的文本为语音识别结果,准确度略低于
        官方字幕,专有名词可能有误。
    """
    video_data, cid, error = _resolve_video(url, page)
    if error:
        return {"error": error}
    aid = video_data.get('aid')

    if not force_asr:
        result, _available, sub_err = bilibili_api.get_subtitles(aid, cid, lang)
        if result and not sub_err:
            return {'title': video_data.get('title'), 'page': page,
                    'source': 'cc', 'lan': result['lan'], 'lines': result['lines']}

    # 无 CC 字幕(或强制):音频 + 本地 ASR
    audio_url, err = bilibili_api.get_audio_url(aid, cid)
    if err:
        return {"error": f"获取音频流失败: {err['error']}"}

    audio_path = tempfile.mktemp(suffix='.m4a', prefix='bili_audio_')
    try:
        err = bilibili_api.download_audio(audio_url, audio_path)
        if err:
            return {"error": f"下载音频失败: {err['error']}"}
        lines, err = asr.transcribe(audio_path, language=lang)
        if err:
            return {"error": f"音频转写失败: {err['error']}"}
        return {'title': video_data.get('title'), 'page': page,
                'source': 'asr', 'lines': lines}
    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)


@mcp.tool(
    annotations={
        "title": "获取视频弹幕",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_danmaku(url: str, page: int = 1, limit: int = 1000) -> dict:
    """Get danmaku (bullet comments) from a Bilibili video

    Args:
        url: Bilibili video URL, e.g., https://www.bilibili.com/video/BV1x341177NN
        page: 1-based part number for multi-part (分P) videos, default 1
        limit: max danmaku returned; when the pool is larger, items are uniformly
               sampled across the timeline (total/returned/sampled are reported)

    Returns:
        Dict with title, total/returned/sampled, source (seg=full protobuf pool,
        xml=legacy capped API) and items [{t: video-time seconds, text, sent: unix
        send time, user: sender hash}]
    """
    video_data, cid, error = _resolve_video(url, page)
    if error:
        return {"error": error}

    page_duration = next((p.get('duration') for p in video_data.get('pages') or []
                          if p.get('page') == page), video_data.get('duration'))
    result, error = bilibili_api.get_danmaku(cid, duration=page_duration, limit=limit)
    if error:
        return {"error": f"获取弹幕失败: {error['error']}"}
    if not result['items']:
        return {"title": video_data.get('title'), "notice": "该视频没有弹幕"}

    return {'title': video_data.get('title'), 'page': page, **result}


@mcp.tool(
    annotations={
        "title": "获取视频评论",
        "readOnlyHint": True,
        "openWorldHint": False
    }
)
async def get_comments(url: str, limit: int = 20, mode: int = 3) -> list:
    """Get the top comments from a Bilibili video

    Returns the first page of comments (~20) sorted by heat or time. Bilibili
    caps this to roughly the top page; deep pagination is not supported.

    Args:
        url: Bilibili video URL, e.g., https://www.bilibili.com/video/BV1x341177NN
        limit: max comments to return (truncates the page), default 20
        mode: 3 = by heat (default), 2 = by time

    Returns:
        List of comments including content, user information, and like counts
    """
    video_data, _, error = _resolve_video(url)
    if error:
        return [error]

    comments, error = bilibili_api.get_comments(video_data.get('aid'), limit=limit, mode=mode)
    if error:
        return [f"获取评论失败: {error['error']}"]

    if not comments:
        return ["该视频没有热门评论"]

    return comments
