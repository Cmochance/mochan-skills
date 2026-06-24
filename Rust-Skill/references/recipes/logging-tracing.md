# 结构化日志(tracing + tracing-subscriber)

> 一句话:用 `tracing` 打结构化日志、`EnvFilter` 控级别、fmt/json layer 选输出格式、`#[instrument]` 自动建 span。

## 依赖
```toml
# 版本以 docs.rs 最新为准
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }
```

## 做法
```rust
use tracing::{info, instrument, warn};
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

// #[instrument] 自动给函数建 span,参数作为 span 字段;skip 跳过大/敏感参数
#[instrument(skip(payload), fields(len = payload.len()))]
fn handle(user_id: u64, payload: &[u8]) {
    info!("处理请求"); // 自动带上 user_id / len 等 span 字段
    if payload.is_empty() {
        warn!(reason = "empty", "空载荷");
    }
}

fn main() {
    // EnvFilter 读 RUST_LOG(如 RUST_LOG=info,myapp::db=debug),缺省给个默认
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));

    // fmt layer:人类可读;换成 .json() 输出结构化 JSON 给日志系统
    let fmt_layer = fmt::layer().with_target(true);

    tracing_subscriber::registry()
        .with(filter)
        .with(fmt_layer) // 生产环境可 .with(fmt::layer().json())
        .init();

    handle(42, b"hello");
}
```

## 要点 / 坑
- **结构化字段优于字符串拼接**:`info!(user_id, %err, "失败")` 而非 `info!("user {} 失败: {}", id, err)`——字段可被日志系统索引过滤。`%` 用 Display、`?` 用 Debug。
- 库里**只发 event**(`tracing` 宏),**别在库里 `.init()` subscriber**;由二进制(应用)初始化一次全局 subscriber。
- `EnvFilter` 支持 per-module 级别(`RUST_LOG=warn,myapp=debug`);只 `.init()` 一次,重复会 panic。
- `#[instrument]` 默认把所有参数记进 span,大对象/敏感数据用 `skip(...)`;别把 token/密码记进日志。

## 关联
- 概览:[`../observability.md`](../observability.md)
- 规则:[`obs-tracing-over-log`](../rules/obs-tracing-over-log.md)、[`obs-instrument-spans`](../rules/obs-instrument-spans.md)、[`obs-levels-filter`](../rules/obs-levels-filter.md)、[`obs-structured-fields`](../rules/obs-structured-fields.md)
