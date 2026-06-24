# 路由矩阵 — 按问题层级 / 用户意图 / crate·工具链 分流

把 Rust 任务路由到最合适的子域 reference 再开工。三维任一命中即可定位;跨域任务组合多个子域(见末尾「跨域路径」)。

> 用法:先完成路由再写代码,别「先写后路由」。编译/借用报错优先走 [`error-codes.md`](error-codes.md)。路由没命中 → 不硬塞,说明并提议(可查 docs.rs / 标准库文档)。

## 三层认知模型(借自 actionbook,组织本矩阵)

- **L1 语言机制**:编译器才关心的事——所有权、生命周期、trait bound、Send/Sync、mutability。症状通常是**编译不过**。
- **L2 工程设计**:编译能过、但好坏有别——API 形状、错误策略、性能、测试、工程结构。症状是**能跑但不地道/不健壮/慢**。
- **L3 领域约束**:具体场景的惯用栈——web/CLI/嵌入式/WASM/系统。症状是**选型与集成**。

先判任务落哪一层,再在该层内定位子域。

## 按问题层级(L1 / L2 / L3)

| 层 | 子域入口 | 典型问题 |
|---|---|---|
| L1 | `ownership-lifetimes.md` | "为什么这里报 borrow"、move 后还想用、生命周期标不对、Rc/Arc/RefCell 选哪个 |
| L1 | `types-traits-generics.md` | trait bound 不满足、泛型 vs `dyn`、关联类型、单态化、孤儿规则、typestate |
| L1 | `error-handling.md` | `?` 用不了、错误类型设计、`Option`↔`Result`、panic vs Result |
| L1 | `concurrency-async.md` | `Send`/`Sync` 不满足、async 持锁过 await、`spawn` 生命周期、select/join、rayon |
| L1 | `unsafe-ffi.md` | 裸指针、`transmute`、FFI 绑定、`#[repr(C)]`、UB 排查、miri |
| L1 | `macros.md` | `macro_rules!` 卫生性、过程宏(derive/attr)、`syn`/`quote`、`cargo expand` |
| L2 | `api-design.md` | builder、newtype、sealed trait、`#[non_exhaustive]`、`must_use`、封装边界 |
| L2 | `performance.md` | 分配热点、`String`/`Vec` 复用、迭代器 vs 索引、inline、profiling |
| L2 | `testing.md` | 单元/集成/doctest、`proptest`/`quickcheck`、`nextest`、`criterion`、mock |
| L2 | `project-cargo.md` | workspace、feature flag、`build.rs`、条件编译、发布、MSRV |
| L2 | `observability.md` | `tracing` span/event、结构化日志、`metrics`、OpenTelemetry |
| L2 | `serde-data.md` | derive、`#[serde(...)]`、自定义 (de)serialize、零拷贝、版本兼容 |
| L3 | `domain-web.md` | axum/actix handler、提取器、中间件、状态共享、错误响应 |
| L3 | `domain-cli.md` | clap derive/builder、子命令、配置、彩色输出、交互 |
| L3 | `domain-embedded.md` | `no_std`、`embedded-hal`、中断、内存约束、`heapless` |
| L3 | `domain-wasm.md` | `wasm-bindgen`、JS 互操作、`wasm32` 目标、体积优化 |
| L3 | `domain-systems.md` | socket、异步 IO、进程/信号、零拷贝、`mio`/`io_uring` |

## 按用户意图(用户说什么 → 进哪)

| 用户说 | 路由到 |
|---|---|
| 「这里为什么 borrow 报错」「move 之后不能用了」「cannot borrow as mutable」 | `ownership-lifetimes.md`(+ `error-codes.md`) |
| 「生命周期怎么标」「`'a` 写哪」「returns a value referencing data owned by…」 | `ownership-lifetimes.md` |
| 「该用 Box / Rc / Arc / RefCell 哪个」「内部可变性」 | `ownership-lifetimes.md` + `rules/`(`mem-*`) |
| 「trait bound not satisfied」「泛型还是 dyn」「关联类型」「孤儿规则」 | `types-traits-generics.md` |
| 「怎么设计成编译期拦住非法状态」「newtype / typestate / phantom」 | `types-traits-generics.md` + `api-design.md` |
| 「错误类型怎么设计」「thiserror 还是 anyhow」「`?` 用不了」 | `error-handling.md` |
| 「async 死锁 / 卡住」「持锁过 await」「Send 不满足无法 spawn」 | `concurrency-async.md` |
| 「tokio / select! / join! / channel」「rayon 并行」「线程池」 | `concurrency-async.md` |
| 「unsafe 对不对」「FFI 绑 C 库」「bindgen / cbindgen」「transmute / repr(C)」 | `unsafe-ffi.md` |
| 「写个 derive 宏 / 属性宏」「macro_rules 展开不对」「syn / quote」 | `macros.md` |
| 「这个 API 怎么设计更地道」「builder 模式」「要不要 sealed / non_exhaustive」 | `api-design.md` |
| 「慢 / 怎么优化」「分配太多」「flamegraph / perf」「inline」 | `performance.md` |
| 「怎么测」「property test」「跑测试慢」「benchmark」「mock」 | `testing.md` |
| 「workspace 怎么组织」「feature flag」「build.rs」「条件编译」「发布 crate」 | `project-cargo.md` |
| 「serde 自定义序列化」「#[serde] 属性」「JSON/TOML/bincode」 | `serde-data.md` |
| 「加日志 / tracing」「结构化日志」「metrics / 链路追踪」 | `observability.md` |
| 「写个 web 服务 / API」「axum / actix」「中间件 / 提取器」 | `domain-web.md` |
| 「写个命令行工具」「clap / 参数解析 / 子命令」 | `domain-cli.md` |
| 「嵌入式 / 单片机 / no_std / 裸机」 | `domain-embedded.md` |
| 「编译到 WASM / 浏览器跑 Rust / wasm-bindgen」 | `domain-wasm.md` |
| 「socket / TCP / 异步 IO / 高性能网络」 | `domain-systems.md` |
| 「编译报错 E0xxx」 | `error-codes.md` → 对应域 |
| 「这段代码地道吗 / review 一下」 | 先 `rules/_index.md` 找相关类对照,再按主题进子域 |
| 「Cargo 依赖装不上 / 版本冲突」 | `project-cargo.md`(依赖段)+ `toolchain-and-mcp.md` |

## 按 crate / 工具链

| crate / 工具 | 相关子域 |
|---|---|
| tokio / async-std / futures | `concurrency-async.md` |
| rayon / crossbeam / parking_lot | `concurrency-async.md` |
| thiserror / anyhow / eyre / snafu | `error-handling.md` |
| serde / serde_json / bincode / toml | `serde-data.md` |
| clap / argh / structopt | `domain-cli.md` |
| axum / actix-web / tower / hyper / reqwest | `domain-web.md`、`domain-systems.md` |
| sqlx / diesel / sea-orm / rusqlite | `domain-web.md`(数据库段)、`recipes/` |
| tracing / log / metrics / opentelemetry | `observability.md` |
| syn / quote / proc-macro2 / darling | `macros.md` |
| bindgen / cbindgen / cxx / libc | `unsafe-ffi.md` |
| wasm-bindgen / wasm-pack / js-sys / web-sys | `domain-wasm.md` |
| embedded-hal / cortex-m / embassy / heapless | `domain-embedded.md` |
| criterion / proptest / quickcheck / nextest / mockall | `testing.md` |
| clippy / rustfmt / miri / cargo-expand / cargo-udeps / bacon | `toolchain-and-mcp.md` |

> 工具/crate 实际可用性、版本以本机与 docs.rs 为准(见 `toolchain-and-mcp.md` / 本机 `config.local.json`),不要猜签名。

## 跨域路径(常见组合)

```
写一个 Web API:
  domain-web(选 axum,handler/提取器/状态) → 错误响应? → error-handling(thiserror + IntoResponse)
  → 数据库? → recipes(sqlx 连接池/查询) → 并发? → concurrency-async → 加日志 → observability

借用检查器打架:
  error-codes(E0382/E0499/E0502 定位) → ownership-lifetimes(根因:move/可变借用/别名)
  → 真要共享可变? → mem-* 规则(Rc<RefCell>/Arc<Mutex>) → 还在 async? → concurrency-async(no-lock-await)

设计一个库的公共 API:
  api-design(builder/newtype/sealed) → 错误类型 → error-handling(thiserror) → 文档 → rules(doc-*)
  → 测试矩阵 → testing → 发布 → project-cargo(版本/feature/MSRV)

性能优化:
  performance(先 profile 定位热点,别瞎猜) → 分配热点? → rules(perf-*/opt-*/mem-*)
  → 并行化? → concurrency-async(rayon) → 验证 → criterion 对比基线

写过程宏:
  macros(syn 解析 → quote 生成) → cargo expand 验展开 → 卫生性/错误信息 → testing(trybuild)

FFI 绑 C 库:
  unsafe-ffi(bindgen 生成 → 安全封装层 → repr/对齐) → miri 验 UB → 测试 → project-cargo(build.rs 链接)
```
