# Web 后端(axum / actix-web / tower / hyper)

用 Rust 写 HTTP 服务:路由、提取器、中间件、共享状态、错误响应、数据库。绝大多数新项目默认 **axum**。

适用:选 web 框架(axum vs actix-web)、提取器(`State`/`Path`/`Query`/`Json`)怎么排、handler 返回什么、中间件怎么挂、自定义 error 怎么变成 HTTP 响应、连数据库(sqlx/sea-orm/diesel)、JWT/CORS/超时/限流。

---

## 框架选型(先定这个)

| 框架 | 适合 | 取舍 |
|---|---|---|
| **axum** | 新项目默认 | tokio 官方系,基于 `tower`/`hyper`;类型化提取器,handler 是普通 async fn,返回 `impl IntoResponse`;生态(tower-http 中间件)复用强 |
| **actix-web** | 极致吞吐 / 已有 actix 代码 | actor 模型,成熟、benchmark 常年靠前;自带一套 extractor/middleware,与 tower 生态不互通;心智负担略高 |
| 裸 **hyper** | 库/代理/非标准协议 | 最底层,没有路由/提取器,什么都要自己搭;只在框架抽象碍事时用 |

**推荐**:常规 REST/JSON API 选 axum——它把 hyper(HTTP 实现)+ tower(中间件抽象)粘在一起,而 tower 生态(`tower-http` 的 trace/cors/compression/timeout)直接可用。actix 只在你已经在用、或压测证明 axum 顶不住时选。

## handler 与提取器

axum handler 是 async fn,参数都是**提取器**(实现 `FromRequest`/`FromRequestParts`),返回实现 `IntoResponse` 的类型:

- `State<S>`:共享应用状态(下一节)。
- `Path<T>`:路径参数,如 `/users/{id}` → `Path(id): Path<u64>`。
- `Query<T>`:查询串 `?a=1&b=2` 反序列化进 `T`(serde)。
- `Json<T>`:请求体按 JSON 反序列化;返回时 `Json(value)` 自动序列化 + 设 content-type。
- `Extension<T>`:中间件注入的类型化值。

**提取器顺序有讲究**:消费 body 的提取器(`Json`/`String`/`Bytes`/`Form`)只能有一个,且**必须放参数列表最后**——它们实现的是 `FromRequest`(消费整个请求),前面的 `Path`/`Query`/`State` 实现 `FromRequestParts`(只看 header/uri)。顺序错了编译器会报 trait bound 不满足。

## 共享状态

用 `State` 提取器配合 `Router::with_state`。状态内放连接池、配置、HTTP 客户端等。需要跨线程共享 + 内部可变时按 [`concurrency-async.md`](concurrency-async.md) 选锁:

```rust
#[derive(Clone)]
struct AppState { db: PgPool, cfg: Arc<Config> }
// Router::new().route("/x", get(handler)).with_state(state)
// async fn handler(State(st): State<AppState>) -> impl IntoResponse { ... }
```

`State` 内部要 `Clone`(每请求克隆一份);把重对象包 `Arc` 让 clone 廉价。连接池(`PgPool` 等)本身已是 `Arc` 语义,直接放即可。共享可变状态用 `Arc<Mutex<_>>`/`Arc<RwLock<_>>`,但**别持锁跨 `.await`**(见 [`rules/anti-lock-across-await.md`](rules/anti-lock-across-await.md))。

## 中间件(tower)

axum 中间件即 tower `Layer`/`Service`。优先用现成的 `tower-http`,别手搓:

- `TraceLayer`:请求日志(配合 tracing,见 [`observability.md`](observability.md))。
- `CorsLayer`:CORS。`TimeoutLayer`:整请求超时。`CompressionLayer`:gzip/br。
- 限流/并发上限:`tower::limit` 的 `ConcurrencyLimitLayer`/`RateLimitLayer`。

自定义逻辑用 `axum::middleware::from_fn`(写个 async fn 拿 `Request` + `Next`)比裸写 `Service` 简单得多。挂载用 `.layer(...)`,注意 **layer 应用顺序是从下往上包裹**(最后 `.layer` 的最外层)。

## 错误处理(error → HTTP 响应)

定义一个应用 error 类型实现 `IntoResponse`,handler 返回 `Result<T, AppError>`,`?` 直接传播。配合 thiserror 定义错误、`From` 转换上游错误(见 [`error-handling.md`](error-handling.md)):

```rust
// enum AppError { NotFound, Db(sqlx::Error), Validation(String) ... } via thiserror
// impl IntoResponse for AppError { 映射到 (StatusCode, Json<ErrBody>) }
```

要点:`IntoResponse` 里把内部错误(DB/IO)映射成 5xx 且**别把内部细节泄给客户端**(日志记全量,响应体给通用消息);校验/找不到映射 4xx。`?` 依赖 `From<sqlx::Error> for AppError` 等转换链。对应规则:[`rules/err-custom-type.md`](rules/err-custom-type.md)、[`rules/err-thiserror-lib.md`](rules/err-thiserror-lib.md)、[`rules/err-from-impl.md`](rules/err-from-impl.md)。

## 数据库

| crate | 特点 | 选它当 |
|---|---|---|
| **sqlx** | 异步、`query!` 宏**编译期校验 SQL**(连真库或离线缓存)、自带连接池 `PgPool` | 想写原生 SQL + 编译期安全,默认选这个 |
| **sea-orm** | 异步 ORM,建在 sqlx 上,动态查询、实体派生 | 要 ORM 抽象、关系/迁移管理 |
| **diesel** | 成熟 ORM,类型安全 DSL,**同步**为主(`diesel-async` 补异步) | 偏好编译期 schema DSL,能接受同步/桥接 |

连接池放进 `AppState`(`PgPool` 已是共享句柄)。sqlx 的离线模式(`cargo sqlx prepare` 生成 `.sqlx/`)让 CI 无需连库也能编译期校验。事务、迁移用各自的 migrate 工具。

## 其他常配

- **运行时**:tokio(`#[tokio::main]`)。axum/actix 都跑在 tokio 上。
- **HTTP 客户端**(服务内部调外部):reqwest(基于 hyper + tokio),复用一个 `Client` 实例(内带连接池),别每次新建。
- **auth/JWT**:`jsonwebtoken` 编解码,放进提取器或中间件校验;密码用 `argon2`/`bcrypt`,别自己搓哈希。
- **配置**:`config`/`figment` 叠加文件 + env(见 [`domain-cli.md`](domain-cli.md) 同款思路)。
- **校验**:请求体 `Json<T>` 后用 `validator` 或在 `TryFrom` 里校验(parse, don't validate,[`rules/api-parse-dont-validate.md`](rules/api-parse-dont-validate.md))。

## 典型坑

- **body 提取器没放最后** → trait bound 报错,或多个 body 提取器冲突。一个请求只能消费 body 一次。
- **持锁跨 `.await`**:`Arc<Mutex>` 在 `lock()` 后 await DB/IO,阻塞其它任务甚至死锁。用 actor/channel 或缩小临界区。
- **阻塞调用堵 runtime**:同步 DB 驱动、`std::fs`、CPU 密集放进 async handler 会卡住 worker 线程,用 `tokio::task::spawn_blocking`(见 [`rules/async-spawn-blocking.md`](rules/async-spawn-blocking.md))。
- **错误细节泄露**:`IntoResponse` 直接 `{:?}` 内部 error 进响应体,泄 SQL/路径。响应给通用文案,细节进日志。
- **每请求新建 reqwest `Client`**:丢掉连接池复用,性能差且耗 fd。建一次放 state。
- **sqlx 编译期校验没配离线缓存** → CI 没数据库连接就编不过。跑 `cargo sqlx prepare` 提交 `.sqlx/`。

## 关联知识库

- 概览:[`concurrency-async.md`](concurrency-async.md)(tokio/锁/spawn_blocking)、[`error-handling.md`](error-handling.md)(error 类型/`?`/thiserror)、[`serde-data.md`](serde-data.md)(请求/响应序列化)、[`observability.md`](observability.md)(tracing/结构化日志)
- 规则:`rules/_index.md` 的 `async-*`、`err-*`、`serde-*`、`obs-*`;特别是 [`rules/anti-lock-across-await.md`](rules/anti-lock-across-await.md)、[`rules/async-spawn-blocking.md`](rules/async-spawn-blocking.md)、[`rules/perf-io-buffering.md`](rules/perf-io-buffering.md)
- 配方:见 [`recipes/_index.md`](recipes/_index.md) 中 HTTP 服务 / JSON / 数据库 / 客户端相关条目

## 参考

- axum 文档(docs.rs/axum,看 `extract` 模块与 `FromRequest`/`FromRequestParts` 区别)、tower / tower-http 文档
- hyper 文档(底层 HTTP)、reqwest 文档(客户端)
- sqlx README + `query!` 宏离线模式说明;sea-orm / diesel 各自 guide
- 版本/签名以 docs.rs 当前版本为准,不确定就 `cargo doc --open` 查
