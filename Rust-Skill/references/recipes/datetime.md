# 日期时间

> 一句话:`chrono` 取当前时间、解析、格式化、时区与时长运算(`time` 是替代)。

## 依赖

```toml
chrono = { version = "0.4", features = ["serde"] }   # serde 用于 (de)serialize 时间字段
# 或 time = "0.3"(更轻、纯 Rust),选型查 docs.rs
```

## 做法

```rust
use chrono::{DateTime, Utc, Local, NaiveDate, Duration, TimeZone};
use anyhow::Result;

fn demo() -> Result<()> {
    // 当前时间:UTC 或本地时区
    let now_utc: DateTime<Utc> = Utc::now();
    let now_local = Local::now();

    // 格式化:strftime 风格;to_rfc3339 给 API/日志用
    let s = now_utc.format("%Y-%m-%d %H:%M:%S").to_string();   // "2026-06-25 08:30:00"
    let iso = now_utc.to_rfc3339();
    println!("{s} | {iso}");

    // 解析:格式串解析"无时区"的 NaiveDate,RFC3339 解析带时区的
    let d = NaiveDate::parse_from_str("2026-06-25", "%Y-%m-%d")?;
    let dt = DateTime::parse_from_rfc3339("2026-06-25T08:30:00+08:00")?;
    println!("{d} {dt}");

    // 时长运算:加减 Duration;两个时刻相减得 Duration
    let tomorrow = now_utc + Duration::days(1);
    let elapsed = tomorrow - now_utc;
    println!("差 {} 小时", elapsed.num_hours());

    // 时区转换:UTC <-> 本地。固定偏移用 FixedOffset;命名时区(如 Asia/Shanghai)需 chrono-tz
    let in_local = now_utc.with_timezone(&Local);
    println!("{in_local}");
    Ok(())
}
```

## 要点 / 坑

- 分清 `NaiveDateTime`(**无时区**,墙上时间)和 `DateTime<Tz>`(**带时区**);跨时区计算只信带时区的,别用 Naive 比较不同地点时刻。
- 命名时区(`Asia/Shanghai`/夏令时)`chrono` 本体不带,要 `chrono-tz`;只有固定偏移用 `FixedOffset`。
- `parse_from_str` 格式串必须**完全匹配**输入,多/少一个空格就报错;不确定先打印 format 输出对照。
- 持久化/传输统一存 **UTC + RFC3339**,展示时才转本地;别把本地时间存库。
- `time` crate 更轻量且无 chrono 的部分历史 CVE 包袱;新项目两者都可,按生态依赖选,查 docs.rs。

## 关联

- 概览:[`../serde-data.md`](../serde-data.md)(时间字段的 (de)serialize)
- 规则:[`serde-custom-with`](../rules/serde-custom-with.md)、[`conv-fromstr-parsing`](../rules/conv-fromstr-parsing.md)
