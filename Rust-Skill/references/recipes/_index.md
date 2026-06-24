# Rust 任务配方 (recipes/) — 索引

> 「怎么用 Rust 做某件具体的事」的可编译配方:依赖 + 做法 + 要点/坑 + 关联。组织借鉴 Rust Cookbook(CC0),代码自写。

> 共 28 篇。按需读单文件,别全量预载。

- [`async-tasks`](async-tasks.md) — 用 `tokio::spawn`/`JoinSet` 并发跑任务、`timeout` 加期限、`interval` 周期触发、`select!` 竞速。
- [`cli-clap`](cli-clap.md) — 用 `clap` 的 derive 宏定义 `Parser`、子命令 enum、参数校验,返回 `ExitCode`。
- [`compression`](compression.md) — `flate2` 做 gzip/deflate 字节流,`zip` 读写 zip 归档。
- [`csv-processing`](csv-processing.md) — `csv` crate 配合 serde 读到 struct、写出、自定义分隔符、大文件流式。
- [`database-sqlx`](database-sqlx.md) — 用 `sqlx` 建连接池、`query!` 做编译期校验的查询、事务、把行 map 到 struct。
- [`datetime`](datetime.md) — `chrono` 取当前时间、解析、格式化、时区与时长运算(`time` 是替代)。
- [`directory-traversal`](directory-traversal.md) — 列目录、递归子树、按 glob 模式找文件。
- [`env-and-args`](env-and-args.md) — `std::env` 读环境变量/参数,`dotenvy` 加载 `.env`,优雅处理缺失与默认值。
- [`error-handling`](error-handling.md) — 库里用 `thiserror` 定义具体错误枚举,应用里用 `anyhow` 加 context,`?` 全程贯穿。
- [`graceful-shutdown`](graceful-shutdown.md) — 接到 Ctrl-C 后用 `CancellationToken` 通知所有任务收尾,等它们清理完再退出。
- [`hashing-encoding`](hashing-encoding.md) — `sha2`/`blake3` 算哈希,`base64`(0.22 Engine API)与 `hex` 编解码。
- [`http-client`](http-client.md) — 用 `reqwest` 发 GET/POST、带 header 与超时、收发 JSON、把错误用 `?` 传播。
- [`http-server-minimal`](http-server-minimal.md) — 用 `axum` 起一个带路由、`Json` 提取/返回、共享 `State` 的最小服务。
- [`logging-tracing`](logging-tracing.md) — 用 `tracing` 打结构化日志、`EnvFilter` 控级别、fmt/json layer 选输出格式、`#[instrument]` 自动建 span。
- [`parse-config`](parse-config.md) — TOML/YAML 反序列化到 struct,分层配置用 `figment`/`config` 叠加默认值+文件+环境变量。
- [`parse-json`](parse-json.md) — `serde_json` 解析到强类型 struct、动态访问 `Value`、生成与流式。
- [`path-handling`](path-handling.md) — 用 `Path`/`PathBuf` 拼接、取扩展名/文件名、跨平台,别拼字符串。
- [`process-exec`](process-exec.md) — 用 `Command` 调外部程序、捕获 stdout/stderr、检查退出码、串管道。
- [`random`](random.md) — `rand` 生成范围随机、洗牌、抽样,需复现时用带 seed 的 `StdRng`。
- [`rayon-parallel`](rayon-parallel.md) — 用 `rayon` 把 `iter()` 换成 `par_iter()` 做并行 map/reduce、`par_sort`,以及何时值得并行。
- [`read-write-files`](read-write-files.md) — 整体/逐行读、缓冲写,把文件 IO 写地道。
- [`regex-matching`](regex-matching.md) — `regex` 做匹配/捕获组/替换,用 `LazyLock`/`once_cell` 编译一次复用。
- [`shared-state`](shared-state.md) — 用 `Arc<Mutex<T>>` / `Arc<RwLock<T>>` 在多任务间共享可变状态,注意锁粒度与"别持锁过 await"。
- [`string-manipulation`](string-manipulation.md) — 切分/拼接/大小写/trim/格式化,以及 Unicode 正确的字符与字素切分。
- [`tcp-client-server`](tcp-client-server.md) — 用 `tokio` 写 accept 循环 + 读写的 echo 服务,并对比 `std::net` 的同步阻塞版。
- [`temp-files`](temp-files.md) — `tempfile` 创建临时文件/目录,作用域结束自动清理。
- [`threads-and-channels`](threads-and-channels.md) — 用 `thread::spawn` + `mpsc` 做生产者-消费者,用 `thread::scope` 借栈数据并 join 收结果。
- [`websocket`](websocket.md) — 用 `tokio-tungstenite` 连接 WS、收发文本消息、用 Ping 做心跳。
