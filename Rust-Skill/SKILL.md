---
name: Rust-Skill
description: Rust 编程的统一方法论 + 路由 + 知识库。覆盖所有权/借用/生命周期、类型系统/trait/泛型、错误处理(Result/?/thiserror/anyhow)、并发与 async(tokio/rayon)、unsafe/FFI、宏、API 设计、性能优化、测试、Cargo/workspace 工程、serde、可观测性,以及 web(axum/actix)/CLI(clap)/嵌入式(no_std)/WASM/系统编程等领域。当任务涉及:写或重构 Rust 代码、借用检查器/编译器报错(E0382/E0499/E0277 等)、生命周期标注、trait bound 设计、async 死锁/持锁过 await、错误类型设计、unsafe 审查、宏编写、Cargo 依赖/feature/workspace、性能调优、写测试、选 crate/惯用法时使用。先路由到对应 references/ 子域,再用 rules/recipes/examples 知识库快速实现。
---

# Rust-Skill — Rust 编程方法论 / 路由 / 知识库

把 Rust 任务变成「先分类路由 → 看准则与用例 → 写出惯用代码 → cargo 验证」的可重复工作流。本 skill 是**方法论 + 主题路由 + 三层知识库(规则/配方/用例)**,不是单纯的语法手册。

> **基础来源**:架构借鉴自社区 `actionbook/rust-skills`(router-first + 认知分层 + error-code 索引)的思路,**剥除了**其过度工程部分(强制评估 hook、协商协议、成就游戏化);规则知识库逐字移植自 `leonardomso/rust-skills`(MIT);配方/用例借鉴 Rust Cookbook(CC0)、Rust by Example(MIT/Apache)、设计模式书(MPL-2.0)。完整归属见仓库根 [`NOTICE`](NOTICE)。

## 核心姿态(写 Rust 的判断,不是套话)

- **惯用优于聪明**:优先标准库/生态既有惯用法(见 `references/rules/`),别为绕过借用检查器而 `clone()` 满天飞、`unwrap()` 一把梭、`Box<dyn Trait>` 兜底。每个"投机"写法都该问:有没有更地道的?
- **类型表达约束**:能让编译期拦住的错误,不留到运行期(newtype / typestate / `Result` / 穷尽 match)。
- **不确定就验证,别猜**:API/trait/方法签名、crate 版本、宏展开、生命周期推断——不确定就 `cargo check` / `cargo expand` / 查 docs.rs,别凭记忆编。区分「我以为能编过」与「cargo 真编过了」。
- **报错先定位再动手**:编译/借用报错先查 [`references/error-codes.md`](references/error-codes.md) 路由到根因域,别盲目加 `&`/`clone`/生命周期标注试错。
- **破坏性降级要先问**:把 `Result` 吞成 `unwrap`、把强类型降成 `String`、删 `?` 改 panic 等"图省事"的降级,默认不做;没有非破坏性等价写法时,停下来说明权衡。

## 工作方式

1. **先路由**:把任务对照 [`references/routing.md`](references/routing.md)(问题层级 / 用户意图 / crate·工具链 三维),确定进哪个子域,再动手——不要「先写起来再说」。
2. **看准则 + 用例**:进对应子域概览文件,顺着它链到 `references/rules/`(地道写法 + 反模式对照)、`references/recipes/`(完成某任务的配方)、`references/examples/`(概念可跑示例)。照着 **Good** 写,拿 **Bad** 自查。
3. **写**:产出能编过、惯用、带必要测试的代码;不确定的签名/行为用 `cargo check`/`expand`/`nextest` 当场验。
4. **验证**:`cargo fmt && cargo clippy && cargo test`(或 `nextest`)三连;改了 unsafe 加 `cargo miri test`;性能改动给 `criterion`/`hyperfine` 数据,别口头说"更快了"。
5. 路由没命中 → 别硬塞,向用户说明并提议(可查 docs.rs / 标准库文档 / 联网)。

## 路由速查(详表见 references/routing.md)

| 任务 | 进入 |
|---|---|
| 所有权/借用/生命周期/移动语义 | [`references/ownership-lifetimes.md`](references/ownership-lifetimes.md) |
| 智能指针/内部可变性(Box/Rc/Arc/Cell/RefCell) | `ownership-lifetimes.md` + `rules/`(`mem-*`) |
| 类型系统/trait/泛型/单态化/typestate | [`references/types-traits-generics.md`](references/types-traits-generics.md) |
| 错误处理(Result/Option/?/thiserror/anyhow) | [`references/error-handling.md`](references/error-handling.md) |
| 并发/async/tokio/rayon/Send+Sync | [`references/concurrency-async.md`](references/concurrency-async.md) |
| unsafe/裸指针/FFI/bindgen/miri | [`references/unsafe-ffi.md`](references/unsafe-ffi.md) |
| 声明宏/过程宏(derive/attr/function-like) | [`references/macros.md`](references/macros.md) |
| API 设计(builder/newtype/sealed/封装) | [`references/api-design.md`](references/api-design.md) |
| 性能/profiling/分配/zero-cost | [`references/performance.md`](references/performance.md) |
| 测试(单元/集成/proptest/nextest/criterion) | [`references/testing.md`](references/testing.md) |
| Cargo/workspace/feature/build/发布 | [`references/project-cargo.md`](references/project-cargo.md) |
| serde/序列化/自定义 (de)serialize | [`references/serde-data.md`](references/serde-data.md) |
| tracing/log/metrics 可观测性 | [`references/observability.md`](references/observability.md) |
| Web 后端(axum/actix/tower) | [`references/domain-web.md`](references/domain-web.md) |
| CLI(clap/终端) | [`references/domain-cli.md`](references/domain-cli.md) |
| 嵌入式/no_std/裸机 | [`references/domain-embedded.md`](references/domain-embedded.md) |
| WASM(wasm-bindgen/wasm32) | [`references/domain-wasm.md`](references/domain-wasm.md) |
| 系统/网络编程(socket/IO/进程) | [`references/domain-systems.md`](references/domain-systems.md) |
| 编译/借用报错 E0xxx | [`references/error-codes.md`](references/error-codes.md) → 对应域 |

## references/ 索引(按需加载,别预载全部)

**导航层**
- `routing.md` — 完整路由矩阵(问题层级 / 用户意图 / crate·工具链)+ 跨域路径
- `error-codes.md` — rustc 错误码(E0382/E0499/E0502/E0277/E0507…)→ 根因域速查
- `toolchain-and-mcp.md` — 工具目录(rustup/cargo/clippy/rustfmt/miri/nextest/expand/bacon)+ rust-analyzer LSP / docs MCP(opt-in)

**概览/导航子域**(每个:识别/核心要点/典型坑/关联 rules·recipes·examples/参考)
- 语言机制:`ownership-lifetimes.md`、`types-traits-generics.md`、`error-handling.md`、`concurrency-async.md`、`unsafe-ffi.md`、`macros.md`
- 工程设计:`api-design.md`、`performance.md`、`testing.md`、`project-cargo.md`、`observability.md`、`serde-data.md`
- 领域:`domain-web.md`、`domain-cli.md`、`domain-embedded.md`、`domain-wasm.md`、`domain-systems.md`

**知识库三层**(高密度,按需读单文件)
- `rules/` — **265 条习惯/反模式规则**(26 类:own/mem/type/trait/async/err/api/test/perf/unsafe…)。每条 = 一句话准则 + Why + Bad/Good 对照。开工前查 `rules/_index.md` 找相关条目。
- `recipes/` — **任务配方**("怎么用 Rust 做 X":读写文件/HTTP 客户端/JSON/并发管道/CLI 解析/数据库…),每条完整可跑。见 `recipes/_index.md`。
- `examples/` — **概念可跑用例**(逐个语言/标准库特性的最小示例),对照学习。见 `examples/_index.md`。
- `deep/` — **设计模式书高保真移植**(idioms/patterns/anti-patterns/refactoring,MPL-2.0 分文件 + notice)。概览不够时进这里。见 `deep/_index.md`。
- `templates/` — Cargo 项目骨架 / error 类型 / bench / 集成测试 / CI 模板,可直接套。

## 完成清单(交付前自检)

- [ ] 代码 **`cargo check`/`clippy` 真过了**(不是「应该能编」),clippy 无 warning(或显式 `#[allow]` 并说明)
- [ ] 写法对照过 `rules/`:没有为绕借用检查器而无谓 `clone`/`unwrap`/`Box<dyn>`;错误用 `?` 传播而非吞掉
- [ ] 公共 API 有 rustdoc(`/// ` + `# Errors`/`# Panics`/`# Safety` 段如适用),关键路径有测试
- [ ] 改了 unsafe → `cargo miri test` 过;性能结论 → 有 `criterion`/`hyperfine` 数据
- [ ] crate/版本/签名来自实际查证(docs.rs / `cargo doc`),没猜;不确定处标了置信度
- [ ] (可选)把踩坑/可复用解法回写本地知识库
