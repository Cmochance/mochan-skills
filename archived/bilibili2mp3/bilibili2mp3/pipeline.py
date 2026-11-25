"""End-to-end: Bilibili URL → MP3 (+ LRC) with embedded lyrics."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import asr, bilibili, convert, embed
from .asr import DEFAULT_LANG as ASR_DEFAULT_LANG
from .convert import BITRATE_PRESETS, DEFAULT_BITRATE, resolve_bitrate
from .subtitle_fmt import safe_filename, to_lrc, to_srt

logger = logging.getLogger(__name__)

DEFAULT_OUT_ENV = "BILIBILI2MP3_OUT"


def default_output_dir() -> Path:
    env = os.getenv(DEFAULT_OUT_ENV)
    if env:
        return Path(env).expanduser()
    return Path.home() / "Downloads" / "bilibili2mp3"


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}_{int(time.time())}{suffix}"


def _year_from_pubdate(pubdate: Any) -> str | None:
    if pubdate is None:
        return None
    try:
        ts = int(pubdate)
        return str(datetime.fromtimestamp(ts, tz=timezone.utc).year)
    except (TypeError, ValueError, OSError):
        return None


def _cc_lang_to_asr_lang(lang: str | None) -> str | None:
    """Map CC language codes to whisper language codes."""
    if not lang:
        return None
    if lang.startswith("ai-"):
        lang = lang[3:]
    if lang in ("zh-CN", "zh-Hans", "zh-Hant", "zh"):
        return "zh"
    if lang.startswith("zh"):
        return "zh"
    # en, ja, ... pass through if short enough for whisper
    return lang


def _id3_title(title: str, part: str) -> str:
    if part and part != title:
        return f"{title} - {part}"
    return title


def probe_video(url: str, page: int = 1) -> dict:
    """Resolve metadata + subtitle availability without downloading audio."""
    video_data, cid, err = bilibili.resolve_video(url, page)
    if err:
        return {"ok": False, "error": err.get("error", str(err))}
    assert video_data is not None

    pm = bilibili.page_meta(video_data, page)
    pages = [
        {
            "page": p.get("page"),
            "part": p.get("part"),
            "duration": p.get("duration"),
        }
        for p in (video_data.get("pages") or [])
    ]

    available: list[str] = []
    tracks_detail: list[dict] = []
    subtitle_notice = None
    if cid is not None:
        tracks, list_err = bilibili.list_subtitle_tracks(video_data.get("aid"), cid)
        if list_err:
            subtitle_notice = list_err.get("error")
        else:
            tracks_detail = [
                {"lan": t.get("lan"), "lan_doc": t.get("lan_doc")} for t in tracks
            ]
            available = [t["lan"] for t in tracks_detail if t.get("lan")]
            if not available and not bilibili.has_sessdata():
                subtitle_notice = (
                    "未配置 SESSDATA：B站字幕列表需要登录态，匿名请求恒为空。"
                    "若视频实际有字幕，请配置 SESSDATA 后重试。"
                )
            elif not available:
                subtitle_notice = "该分P无可用CC字幕"

    return {
        "ok": True,
        "bvid": video_data.get("bvid"),
        "aid": video_data.get("aid"),
        "title": video_data.get("title"),
        "owner": (video_data.get("owner") or {}).get("name"),
        "duration": pm.get("duration") or video_data.get("duration"),
        "page": page,
        "part": pm.get("part"),
        "pages": pages,
        "cover": bilibili.normalize_cover_url(video_data.get("pic")),
        "subtitle_languages": available,
        "subtitle_tracks": tracks_detail,
        "has_sessdata": bilibili.has_sessdata(),
        "ffmpeg_ok": convert.ffmpeg_available(),
        "bitrate_presets": dict(BITRATE_PRESETS),
        "notice": subtitle_notice,
    }


def list_subtitle_langs(url: str, page: int = 1) -> dict:
    """List available CC subtitle languages for a part (needs SESSDATA)."""
    video_data, cid, err = bilibili.resolve_video(url, page)
    if err or video_data is None or cid is None:
        return {"ok": False, "error": (err or {}).get("error", "resolve failed")}

    tracks, list_err = bilibili.list_subtitle_tracks(video_data.get("aid"), cid)
    if list_err:
        return {
            "ok": False,
            "error": list_err.get("error"),
            "bvid": video_data.get("bvid"),
            "page": page,
            "has_sessdata": bilibili.has_sessdata(),
        }

    available = [
        {"lan": t.get("lan"), "lan_doc": t.get("lan_doc")}
        for t in tracks
        if t.get("lan")
    ]
    notice = None
    if not available and not bilibili.has_sessdata():
        notice = (
            "未配置 SESSDATA：B站字幕列表需要登录态，匿名请求恒为空。"
            "配置后重试。"
        )
    elif not available:
        notice = "该分P无可用CC字幕"

    return {
        "ok": True,
        "bvid": video_data.get("bvid"),
        "title": video_data.get("title"),
        "page": page,
        "languages": available,
        "has_sessdata": bilibili.has_sessdata(),
        "notice": notice,
    }


def convert_to_mp3(
    url: str,
    *,
    page: int = 1,
    lang: str | None = None,
    output_dir: str | Path | None = None,
    bitrate: str = DEFAULT_BITRATE,
    write_lrc: bool = True,
    write_srt: bool = False,
    embed_cover: bool = True,
    allow_asr: bool = False,
    force_asr: bool = False,
) -> dict:
    """Download audio, convert to MP3, embed lyrics (CC preferred, optional ASR).

    allow_asr: if no CC, run local ASR on downloaded audio (slow; needs mlx-whisper
    or BILIBILI_ASR_CMD). force_asr: skip CC and always ASR.
    """
    warnings: list[str] = []

    try:
        resolved_bitrate = resolve_bitrate(bitrate)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    pf = convert.preflight()
    if pf:
        return {"ok": False, "error": pf["error"]}

    video_data, cid, err = bilibili.resolve_video(url, page)
    if err or video_data is None or cid is None:
        return {"ok": False, "error": (err or {}).get("error", "resolve failed")}

    aid = video_data.get("aid")
    bvid = video_data.get("bvid") or ""
    title = video_data.get("title") or bvid or "untitled"
    owner = (video_data.get("owner") or {}).get("name") or ""
    pm = bilibili.page_meta(video_data, page)
    part = pm.get("part") or ""

    out_dir = Path(output_dir).expanduser() if output_dir else default_output_dir()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"无法创建输出目录: {e}"}

    base_name = safe_filename(f"{title}[{bvid}][P{page}]")
    mp3_path = _unique_path(out_dir / f"{base_name}.mp3")
    lrc_path: Path | None = None
    srt_path: Path | None = None

    # --- subtitles (CC) ---
    lines: list[dict] = []
    subtitle_source = "none"
    subtitle_lang: str | None = None
    available_langs: list[str] = []
    lyrics_embedded = False
    cover_embedded = False

    if not force_asr:
        sub, available_langs, sub_err = bilibili.get_subtitles(aid, cid, lang)
        if sub_err:
            # Explicit lang miss is a hard error unless ASR can cover
            if sub_err.get("lang_not_found") and not (allow_asr or force_asr):
                return {
                    "ok": False,
                    "error": sub_err.get("error"),
                    "available_languages": available_langs,
                    "warnings": warnings,
                }
            warnings.append(f"字幕获取失败: {sub_err.get('error')}")
        elif sub and sub.get("lines"):
            lines = sub["lines"]
            subtitle_source = "cc"
            subtitle_lang = sub.get("lan")
        else:
            if not bilibili.has_sessdata():
                warnings.append(
                    "无CC字幕（未配置 SESSDATA：字幕列表需登录态）"
                )
            else:
                warnings.append("该视频无可用CC字幕")

    # --- cover (optional) ---
    cover_data: bytes | None = None
    cover_mime: str | None = None
    if embed_cover:
        cdata, cmime, cerr = bilibili.download_cover(video_data.get("pic"))
        if cerr:
            warnings.append(f"封面跳过: {cerr.get('error')}")
        else:
            cover_data, cover_mime = cdata, cmime

    # --- audio download + optional ASR + convert ---
    audio_url, aerr = bilibili.get_audio_url(aid, cid)
    if aerr or not audio_url:
        return {
            "ok": False,
            "error": f"获取音频流失败: {(aerr or {}).get('error', 'unknown')}",
            "warnings": warnings,
        }

    try:
        with tempfile.TemporaryDirectory(prefix="bilibili2mp3_") as tmp:
            raw_path = Path(tmp) / "audio.m4a"
            derr = bilibili.download_audio(audio_url, raw_path)
            if derr:
                return {
                    "ok": False,
                    "error": f"下载音频失败: {derr.get('error')}",
                    "warnings": warnings,
                }

            need_asr = (not lines) and (allow_asr or force_asr)
            if need_asr:
                asr_lang = _cc_lang_to_asr_lang(lang)
                logger.info("running ASR fallback force=%s", force_asr)
                asr_lines, asr_err = asr.transcribe(str(raw_path), language=asr_lang)
                if asr_err:
                    warnings.append(f"ASR 失败: {asr_err.get('error')}")
                elif asr_lines:
                    lines = asr_lines
                    subtitle_source = "asr"
                    subtitle_lang = asr_lang or ASR_DEFAULT_LANG
                else:
                    warnings.append("ASR 未产出文本")
            elif not lines:
                warnings.append("仍输出无歌词 MP3（可加 --allow-asr 启用 ASR 兜底）")

            tmp_mp3 = Path(tmp) / "audio.mp3"
            cerr = convert.to_mp3(raw_path, tmp_mp3, bitrate=resolved_bitrate)
            if cerr:
                return {
                    "ok": False,
                    "error": cerr.get("error"),
                    "warnings": warnings,
                }

            eerr = embed.embed_metadata(
                tmp_mp3,
                title=_id3_title(title, part),
                artist=owner or None,
                album=f"Bilibili {bvid}",
                year=_year_from_pubdate(video_data.get("pubdate")),
                comment=f"{bvid} P{page} https://www.bilibili.com/video/{bvid}",
                lines=lines or None,
                cover_data=cover_data,
                cover_mime=cover_mime,
            )
            if eerr:
                warnings.append(f"ID3 写入警告: {eerr.get('error')}")
                # Do not claim lyrics/cover were embedded
                if lines:
                    warnings.append("歌词未成功写入 ID3（文件仍已生成）")
                lyrics_embedded = False
                cover_embedded = False
            else:
                lyrics_embedded = bool(lines)
                cover_embedded = bool(cover_data)

            # Prefer rename within same FS; fall back to copy across devices
            try:
                os.replace(tmp_mp3, mp3_path)
            except OSError:
                shutil.copy2(tmp_mp3, mp3_path)

            if write_lrc and lines:
                try:
                    lrc_path = _unique_path(mp3_path.with_suffix(".lrc"))
                    lrc_path.write_text(to_lrc(lines), encoding="utf-8")
                except OSError as e:
                    warnings.append(f"写 LRC 失败: {e}")
                    lrc_path = None

            if write_srt and lines:
                try:
                    srt_path = _unique_path(mp3_path.with_suffix(".srt"))
                    srt_path.write_text(to_srt(lines), encoding="utf-8")
                except OSError as e:
                    warnings.append(f"写 SRT 失败: {e}")
                    srt_path = None
    except OSError as e:
        return {"ok": False, "error": f"文件系统错误: {e}", "warnings": warnings}

    # Report source accurately: if we had lines but failed to embed, still keep
    # subtitle_source as where text came from, but expose lyrics_embedded flag.
    return {
        "ok": True,
        "bvid": bvid,
        "aid": aid,
        "page": page,
        "title": title,
        "part": part,
        "owner": owner,
        "mp3_path": str(mp3_path.resolve()),
        "lrc_path": str(lrc_path.resolve()) if lrc_path else None,
        "srt_path": str(srt_path.resolve()) if srt_path else None,
        "subtitle_source": subtitle_source,
        "subtitle_lang": subtitle_lang,
        "lyrics_embedded": lyrics_embedded,
        "available_languages": available_langs,
        "duration_sec": pm.get("duration") or video_data.get("duration"),
        "bitrate": resolved_bitrate,
        "bitrate_requested": bitrate,
        "embed_cover": cover_embedded,
        "warnings": warnings,
    }
