# 可观测性 / tracing / log / metrics / OpenTelemetry

让运行中的程序"可被观察":发生了什么、慢在哪、出错链是什么。本域讲在 Rust 里选 log 还是 tracing、怎么配 subscriber、何时用 metric/trace。

适用:加日志、结构化追踪、async 上下文里的日志、自动 span、暴露指标(counter/gauge/histogram)、分布式追踪、判断"这事该 log 还是 metric 还是 trace"。

---

## log vs tracing(先选门面)

| 维度 | `log`(+ env_logger 等) | `tracing`(推荐) |
|---|---|---|
| 模型 | 扁平的一条条 event | event **+ span**(有层级/时段的上下文) |
| 结构化 | 主要是消息字符串 | 一等的 key-value 字段 |
| async | 跨 `.await` 上下文易丢失 | span 跟随任务,async 友好 |
| 生态 | 经典、轻量 | tokio 系标配,可桥接 `log` |

- **新代码默认 `tracing`**:它的 span 能表达"在处理请求 X 期间"这种时段上下文,async 里尤其关键;`log` 的宏可通过 `tracing-log` 桥接进来。→ [`obs-tracing-over-log`](rules/obs-tracing-over-log.md)
- **库(library)只依赖门面、不配 subscriber**:库里用 `tracing`(或 `log`)的宏发事件,**把"输出到哪、什么格式"留给二进制 crate 决定**——库装 subscriber 会和应用打架。→ [`obs-library-facade`](rules/obs-library-facade.md)

## span 与 event(tracing 的核心)

- **event**:某一时刻发生的事(`tracing::info!(...)`),对应传统一条日志。
- **span**:一段**有起止**的上下文(`let _g = span.enter()`),其内的所有 event 自动带上 span 的字段——这是 tracing 比 log 强的根本。
- **`#[instrument]`**:给函数加属性宏自动建 span,把参数作为字段记录(敏感参数用 `skip`/`skip_all`)。→ [`obs-instrument-spans`](rules/obs-instrument-spans.md)
- async 里 span 跟随 future,不会因 `.await` 切走任务而错乱上下文。

## subscriber 配置(`tracing-subscriber`)

应用入口装一次 subscriber,决定采集与输出:

- **`EnvFilter`**:按 `RUST_LOG`(如 `RUST_LOG=info,my_crate=debug`)运行时控制级别,per-module 粒度。→ [`obs-levels-filter`](rules/obs-levels-filter.md)
- **fmt layer**:人读的彩色/紧凑输出(开发);**json layer**:机器可解析(生产,喂给日志系统)。
- **Layer 叠加**:`Registry` + 多 layer 组合(fmt + filter + OTel + 自定义),各司其职。

## 字段 vs 消息(结构化优先)

- **把变量做成字段,别拼进消息串**:`info!(user_id, order_id, "created")` 而非 `info!("created order {order_id} for {user_id}")`——前者能按 `user_id` 检索/聚合,后者只能全文 grep。→ [`obs-structured-fields`](rules/obs-structured-fields.md)
- **错误链一起记**:记错误时带上 `source` 链(`error = ?e` 或专门字段),别只记顶层 message,丢了根因。→ [`obs-error-chain`](rules/obs-error-chain.md)
- **绝不记敏感数据**:密码/token/PII 不进日志;`#[instrument(skip(secret))]` 跳过敏感参数。→ [`obs-no-sensitive-data`](rules/obs-no-sensitive-data.md)

## log / metric / trace 怎么选

| 你想知道 | 用 | 例 |
|---|---|---|
| "这次具体发生了什么 / 出错细节" | **log/event** | 报错堆栈、关键分支 |
| "整体趋势 / 速率 / 分布"(聚合数值) | **metric** | QPS、错误率、p99 延迟、队列长度 |
| "一次请求跨服务/跨 await 走了哪条路、各段耗时" | **trace/span** | 分布式调用链 |

- **metrics**:用 `metrics` crate 门面(counter/gauge/histogram),后端(Prometheus exporter 等)可换;counter 只增、gauge 可增减、histogram 记分布。
- **分布式追踪**:`opentelemetry` + `tracing-opentelemetry` 把 tracing span 导出到 Jaeger/OTLP collector,跨服务关联 trace id。具体 API 查 docs.rs。

## 典型坑

- **热路径过度 log**:每次循环 `debug!` 拖垮吞吐;热路径只在异常分支记,或抬高级别用 `EnvFilter` 默认关掉。
- **库里装了 subscriber**:被应用引入后和应用的 subscriber 冲突/重复输出;库只发事件。
- **变量拼进消息串**:没法按字段检索聚合,失去结构化的全部价值。
- **敏感数据进日志**:token/密码泄漏到日志系统,合规事故。
- **只记顶层错误**:丢了 `source` 链,排查时不知根因——记错误务必带链。
- **级别用反**:把高频正常事件记成 `error`/`warn`,告警噪声淹没真问题。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **可观测性(`obs-*`,7 条)** 类
- 错误链(`source`)的构造见 [`error-handling.md`](error-handling.md)(`thiserror`/`anyhow`/`# Errors`)——可观测性记的就是这条链
- 工具与运行时环境见 [`toolchain-and-mcp.md`](toolchain-and-mcp.md)

## 参考

- `tracing` / `tracing-subscriber` 文档(docs.rs)——span/event/Layer/EnvFilter 权威
- `metrics` crate、`opentelemetry` + `tracing-opentelemetry` docs.rs(API 以文档为准)
- tokio 官方 tracing 指南(async 中的 span 行为)
