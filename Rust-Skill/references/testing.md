# 测试 / 单元 / 集成 / doctest / property / 基准

Rust 把测试做进了语言和工具链:`#[test]`、文档即测试、`cargo test`/`nextest` 开箱即用。本域讲**写哪种测试、放哪、用什么 crate**。

适用:写单元/集成测试、doctest 该不该写、property-based(`proptest`/`quickcheck`)、跑得更快(`nextest`)、写基准(`criterion`)、mock 依赖、测编译失败(`trybuild`)、快照测试(`insta`)、覆盖率。

---

## 测试分层(先选对种类)

| 测什么 | 放哪 | 怎么写 | 规则 |
|---|---|---|---|
| 单个函数/模块内部逻辑(含私有项) | 同文件 `#[cfg(test)] mod tests` | `#[test]` + `assert_eq!` | [`test-cfg-test-module`](rules/test-cfg-test-module.md)、[`test-use-super`](rules/test-use-super.md) |
| 公共 API / crate 对外行为 | `tests/` 目录(各文件独立 crate) | 只能用 `pub` 项 | [`test-integration-dir`](rules/test-integration-dir.md) |
| 文档示例正确性 | rustdoc 注释里的代码块 | ```` ```rust ```` 自动当测试跑 | [`test-doctest-examples`](rules/test-doctest-examples.md) |
| 不变量/任意输入 | 任意测试 | `proptest`/`quickcheck` | [`test-proptest-properties`](rules/test-proptest-properties.md) |
| 性能 | `benches/` | `criterion` | [`test-criterion-bench`](rules/test-criterion-bench.md) |

> 单元测试与被测代码同文件(`mod tests` 内 `use super::*`)——能测私有项、改代码顺手改测试。集成测试只验对外契约,逼你把 API 设计得可用。

## 单元测试惯用法

- **结构 AAA**:Arrange(造数据)→ Act(调被测)→ Assert(验结果),一个测试一个意图。→ [`test-arrange-act-assert`](rules/test-arrange-act-assert.md)
- **命名说清场景**:`fn parse_rejects_empty_input()` 比 `test1` 强,失败时一眼知道断了什么。→ [`test-descriptive-names`](rules/test-descriptive-names.md)
- **断言宏**:`assert_eq!`/`assert_ne!`(失败打印两侧值)优于 `assert!(a == b)`;布尔条件才用 `assert!`。
- **测 panic**:`#[should_panic(expected = "...")]` 验该 panic 的路径;但**预期失败优先用 `Result` 返回**而非 panic。→ [`test-should-panic`](rules/test-should-panic.md)
- **测返回 `Result`**:测试函数可写 `fn t() -> Result<(), E>`,体内用 `?`,比层层 `unwrap` 干净。
- **资源清理用 RAII**:临时文件/目录用 `tempfile`,Drop 自动清,别手动删。→ [`test-fixture-raii`](rules/test-fixture-raii.md)

## doctest

文档代码块默认会被 `cargo test` 当测试编译并运行——既保证示例不过时,又是 API 用法范例:

- 默认 ```` ```rust ````(或裸 ```` ``` ````)即测试;不想跑用 ```` ```no_run ````(编译不运行)/ ```` ```ignore ````/ ```` ```text ````。
- **`?` 传播**:示例里想用 `?`,把 body 包进返回 `Result` 的 `fn main()`,或用 `# Ok::<(), Error>(())` 收尾。→ [`doc-question-mark`](rules/doc-question-mark.md)
- **隐藏样板**:`#` 开头的行编译但不显示(藏 `use`/`fn main`/构造),让读者只看重点。→ [`doc-hidden-setup`](rules/doc-hidden-setup.md)
- 在 rustdoc 的 `# Examples` 段放可跑示例。→ [`doc-examples-section`](rules/doc-examples-section.md)

## property-based(`proptest` / `quickcheck`)

不再手列固定 case,而是声明**对任意输入都成立的性质**,框架随机生成大量输入找反例(并 shrink 到最小失败 case):

- 经典性质:round-trip(`decode(encode(x)) == x`)、不变量(排序后长度不变、有序)、与朴素实现等价。
- `proptest`:`proptest! { fn p(x in 0..1000u32) { ... } }`,strategy 灵活、shrink 强;`quickcheck` 更轻量靠 `Arbitrary`。→ [`test-proptest-properties`](rules/test-proptest-properties.md)

## 跑测试:`cargo test` vs `nextest`

- `cargo test`:内置,够用;同进程跑测试。
- `cargo nextest run`:更快(进程级并行)、输出更清晰、支持**失败重试**(`--retries`)和分片(CI 友好)。doctest 它不跑,需 `cargo test --doc` 补。→ 工具见 [`toolchain-and-mcp.md`](toolchain-and-mcp.md)

## 基准:用 `criterion`,别手搓 `Instant`

- `criterion` 做统计采样、暖机、离群剔除,自动对比历史报 regression;`Instant::now()` 手搓受噪声/优化器影响,结论不可信。→ [`test-criterion-bench`](rules/test-criterion-bench.md)
- **`black_box`**:用 `std::hint::black_box`(或 `criterion::black_box`)包裹输入/输出,阻止优化器把被测代码算掉。→ [`perf-black-box-bench`](rules/perf-black-box-bench.md)
- benchmark 放 `benches/`,跑 `cargo bench`(隐含 `--release`)。

## mock / 异步 / 并发 / 编译失败

- **mock 走 trait 注入**:依赖抽成 trait,测试传假实现——优先手写 fake(简单),复杂场景用 `mockall` 生成 mock(可设期望/返回)。→ [`test-mock-traits`](rules/test-mock-traits.md)、[`test-mockall-mocking`](rules/test-mockall-mocking.md)
- **异步测试**:`#[tokio::test]` 起 runtime 跑 `async fn` 测试。→ [`test-tokio-async`](rules/test-tokio-async.md)
- **并发交错**:`loom` 穷举线程交错验无锁/原子代码的正确性(比随机跑可靠)。→ [`test-loom-concurrency`](rules/test-loom-concurrency.md)
- **快照测试**:`insta` 把大输出(序列化结果/渲染)存 snapshot,改动时 review diff、`cargo insta accept`。→ [`test-snapshot-testing`](rules/test-snapshot-testing.md)
- **测编译失败**:验"这段代码应该编不过"(API 误用、生命周期约束)用 `trybuild` 对照 `.stderr`。具体 API 查 docs.rs。
- **覆盖率**:`cargo llvm-cov`(基于 LLVM source-based coverage)出行/分支覆盖;别盲目追 100%。

## 典型坑

- **`criterion` 漏 `black_box`**:被测代码被优化消除,测出假的"超快"。
- **doctest `?` 编不过**:忘了把示例包进返回 `Result` 的上下文。
- **集成测试想测私有项**:`tests/` 只能访问 `pub`;要测内部逻辑放回 `#[cfg(test)] mod tests`。
- **测试依赖执行顺序/共享全局状态**:测试默认并行跑,互相污染;隔离状态或用独立 fixture。
- **`#[should_panic]` 不写 `expected`**:任何 panic 都算通过,可能测对了错误原因。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **测试(`test-*`,15 条)** 类;doctest 相关 `doc-examples-section`/`doc-hidden-setup`/`doc-question-mark`
- 基准与性能调优联动见 [`performance.md`](performance.md)(profile → 立 criterion 基准 → 改 → 重测)
- 工具(nextest/criterion/insta/llvm-cov)目录见 [`toolchain-and-mcp.md`](toolchain-and-mcp.md)

## 参考

- The Book ch.11(Writing Automated Tests)、rustdoc book(Documentation tests)
- `proptest`/`criterion`/`insta`/`mockall`/`trybuild`/`loom` 各自 docs.rs(API 以文档为准)
- `cargo-nextest` 站点、`cargo-llvm-cov` README
