# Followup / TODO

本文件记录 bilibili-compact-mcp 的待办增强项(非 bug,是有意延后的功能)。

## ~~无字幕视频的音频转写 fallback~~(已完成,v0.4.0)

已落地为 `get_transcript` 工具 + `asr.py` 模块:CC 字幕优先,无则 WBI 签名 playurl
取 dash 音频流 → 下载(referer 防盗链)→ 子进程 ASR 转写成带时间戳 `lines:[{t,text}]`。
转写器外挂不进包依赖(默认 mlx-whisper via uvx,可用 `BILIBILI_ASR_CMD` 覆盖)。
已知限制:ASR 路径慢(下载+转写+首次下模型,数分钟);默认仅 Apple Silicon(mlx),
其他平台需设 `BILIBILI_ASR_CMD`。

## 评论深翻页(优先级:低)

`get_comments` 目前只返回热度/时间排序的首页(约 20 条)。深翻页(page2+)需处理
B站 buvid 激活反爬(ExClimbWuzhi),脆弱且与 compact 定位不符,暂不做。
如需全量评论,再评估是否值得引入这套反爬链。
