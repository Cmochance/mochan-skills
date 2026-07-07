# Followup / TODO

本文件记录 bilibili-compact-mcp 的待办增强项(非 bug,是有意延后的功能)。

## 无字幕视频的音频转写 fallback(优先级:中)

**现状**:`get_subtitles` 依赖 B站 CC 字幕接口(需 SESSDATA)。视频没有 CC 字幕时,
只能返回标题 + 简介兜底,拿不到正文内容用于总结。

**目标**:无 CC 字幕时,下载音频流用 ASR(如 faster-whisper / funasr)转写成带时间戳的
文本,作为字幕的替代来源喂给总结。

**为何延后**:
- 引入重依赖(whisper 模型 / ffmpeg / torch),与本 MCP "compact" 定位冲突,需先决定
  是走本地模型还是调外部 ASR API
- 音频流下载需处理 B站 dash 音频 URL 签名 + referer 防盗链
- BibiGPT 开源版本身也没做本地转写(其转写在付费后端),无现成实现可直接借鉴

**落地时的技术锚点**:
- 音频流地址:`https://api.bilibili.com/x/player/playurl?bvid=&cid=&fnval=16`(dash.audio)
- 转写产物结构对齐现有字幕 `lines: [{t: 秒, text}]`,让上层无感切换

## 评论深翻页(优先级:低)

`get_comments` 目前只返回热度/时间排序的首页(约 20 条)。深翻页(page2+)需处理
B站 buvid 激活反爬(ExClimbWuzhi),脆弱且与 compact 定位不符,暂不做。
如需全量评论,再评估是否值得引入这套反爬链。
