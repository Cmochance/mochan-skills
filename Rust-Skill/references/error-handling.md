# 错误处理(Result / Option / `?` / 错误类型设计 / panic 边界)

把"可能失败"写进类型、用 `?` 把错误顺着调用链送上去的一层。**"`?` 用不了 / 错误类型怎么设计 / 这里该不该 panic"先来这。**

适用:`?` 报"the trait `From` is not implemented"(错误类型不能互转)、E0277(`?` 要求的 `Try`/`From` 没满足);设计库的错误枚举;`Option` 与 `Result` 互转;判断某处该返回 `Err` 还是 `panic!`。

---

## 心智模型(先建立,再写)

- **可恢复用 `Result<T, E>`**,**不可恢复(bug / 违反不变量)用 `panic!`**。这是 Rust 错误处理的总分界。
- **错误是值,不是控制流**:没有异常、没有 `try/catch`。失败通过返回 `Result` 显式传递,调用方必须处理(或用 `?` 上抛)。→ 这逼着每条失败路径都被看见。
- **`?` = "成功就解包,失败就 `return Err(转换后的错误)`"**:它在 `Err` 分支自动调 `From::from` 做错误类型转换,所以"`?` 用不了"几乎总是**缺一个 `From` impl**。
- **`Option<T>` 表"有没有"**(缺值不是错误),**`Result<T, E>` 表"成没成"**(失败带原因)。两者可互转,别混用语义。

排错套路:`?` 编不过 → 看是不是函数返回类型的 `E` 缺了从子错误的 `From`(库用 thiserror 的 `#[from]` 一行解决,应用用 anyhow 自动兼容任意 `Error`)。

## `Result` / `Option` / `?` 传播

- 函数签名声明可失败:`fn f() -> Result<T, MyError>`;内部对子调用用 `?` 顺着上抛,别手写 `match { Err(e) => return Err(e), .. }`。→ [`err-question-mark`](rules/err-question-mark.md)
- `?` 也作用于 `Option`(在返回 `Option` 的函数里),`None` 即早返回。
- `main` 可返回 `Result<(), E>`(`E: Debug`),让 `?` 直接用在顶层。
- 链式组合优先用组合子(`map`/`and_then`/`unwrap_or_else`),而非层层 `match`。

## `Option` ↔ `Result` 互转(常用一张表)

| 起点 | 想要 | 用 |
|---|---|---|
| `Option<T>` | `Result<T, E>` | `.ok_or(err)` / `.ok_or_else(\|\| err)` |
| `Result<T, E>` | `Option<T>`(丢错误) | `.ok()` |
| `Result<T, E>` | `Option<E>`(取错误) | `.err()` |
| `Option<T>` | 缺值即 panic(仅 bug 场景) | `.expect("不变量:...")` |
| `Result<T, E>` | 缺则给默认 | `.unwrap_or(d)` / `.unwrap_or_default()` / `.unwrap_or_else(..)` |

> `ok_or_else` / `unwrap_or_else` 收闭包,**err 值构造有开销时用它**(惰性),别用 `ok_or(expensive())` 每次都算。

## 库 vs 应用:thiserror 还是 anyhow(核心决策)

| 你在写 | 用 | 为什么 |
|---|---|---|
| **库 / crate**(给别人调) | **`thiserror`** | 定义**具名、可匹配**的错误 `enum`,调用方能 `match` 分支精确处理;`#[from]` 自动生成 `From` 让 `?` 顺畅 → [`err-thiserror-lib`](rules/err-thiserror-lib.md)、[`err-custom-type`](rules/err-custom-type.md) |
| **应用 / 二进制 / 顶层** | **`anyhow`**(或 `eyre`) | `anyhow::Result<T>` 吃任意 `Error`,`.context("...")` 加上下文链,不用为每种错误建类型 → [`err-anyhow-app`](rules/err-anyhow-app.md)、[`err-context-chain`](rules/err-context-chain.md) |

要点:

- **库别用 anyhow 当公共 API 返回类型** —— 那会把"具体错误"擦成不透明黑盒,下游无法按类型分支。库返回自己的 typed error。
- 应用里 `anyhow::Result` + `?` + `.context("读取配置 {path} 失败")`,出错时打印整条 context 链,定位快。
- thiserror 只是**派生宏**(零运行期成本,生成 `Display`/`Error`/`From`);anyhow 是**带 backtrace 的动态错误容器**。两者常配合:库内部 thiserror,应用入口 anyhow 收口。

## 自定义错误类型该有的样子

- 实现 `std::error::Error`(thiserror `#[derive(Error)]` 自动)+ `Display`(`#[error("...")]`)+ `Debug`。
- **`source()` 错误链**:底层错误用 `#[from]` 或 `#[source]` 挂上,保留根因,别丢。→ [`err-source-chain`](rules/err-source-chain.md)、[`err-from-impl`](rules/err-from-impl.md)
- **消息小写、不带句尾标点**(惯例,便于嵌入更大句子):`#[error("invalid header {0}")]`。→ [`err-lowercase-msg`](rules/err-lowercase-msg.md)
- 用 `enum` 分变体表达不同失败种类,让调用方可 `match`;别一个 `String` 兜所有错误。

```rust
#[derive(thiserror::Error, Debug)]
pub enum ConfigError {
    #[error("config file not found: {0}")]
    NotFound(PathBuf),
    #[error("invalid toml")]
    Parse(#[from] toml::de::Error),   // 自动 From + 进 source() 链
}
```

## panic 边界:`panic!` / `unwrap` / `expect` 只给"不可能"

- **`Result` 优先于 panic** 表达**预期会发生**的失败(找不到文件、网络断、解析错)。预期失败 panic 是反模式。→ [`err-result-over-panic`](rules/err-result-over-panic.md)、[`anti-panic-expected`](rules/anti-panic-expected.md)
- `unwrap()` / `expect()` 只用于**逻辑上不可能失败**或**失败即 bug**(违反了你能保证的不变量)。→ [`err-expect-bugs-only`](rules/err-expect-bugs-only.md)
- **`expect` 优于 `unwrap`**:写清"为什么这里不可能失败 / 失败意味着什么 bug",别裸 `unwrap()`。→ [`anti-expect-lazy`](rules/anti-expect-lazy.md)、[`anti-unwrap-abuse`](rules/anti-unwrap-abuse.md)、[`err-no-unwrap-prod`](rules/err-no-unwrap-prod.md)
- **别吞错误**:`let _ = result;` / 空的 `if let Ok(_) =` 把失败默默咽下,出问题无迹可查。要么处理,要么 `?` 上抛,要么显式记录。→ [`anti-empty-catch`](rules/anti-empty-catch.md)
- panic 只对**本进程**;`catch_unwind` 不是异常机制(且 abort 模式下根本不展开)。库**绝不**用 panic 当跨边界错误传递。

## 文档:`# Errors` / `# Panics` 段

公共 API 必须说明失败契约:

- 返回 `Result` 的函数写 **`# Errors`**:什么条件下返回 `Err`、返回哪种错误。→ [`doc-errors-section`](rules/doc-errors-section.md)、[`err-doc-errors`](rules/err-doc-errors.md)
- 可能 panic 的函数写 **`# Panics`**:什么输入会 panic。→ [`doc-panics-section`](rules/doc-panics-section.md)
- rustdoc 例子里用 `?` 时,把它放进一个返回 `Result` 的隐藏 `main`/包装函数。→ [`doc-question-mark`](rules/doc-question-mark.md)

## 典型坑

- **`?` 编不过**:十有八九是函数的错误类型缺了从子错误的 `From`。库用 thiserror `#[from]`,应用用 anyhow(自动)。
- **库 API 返回 anyhow**:擦掉了类型,下游没法分支处理 —— 库返回 typed error,只在二进制顶层用 anyhow。
- **`unwrap()` 一把梭**:预期失败也 unwrap,生产环境一炸就是 panic;改 `?` 上抛或给降级。
- **吞错误**:`let _ =`、`.ok();` 丢弃 `Result` 而无意识;失败静默 = 不可观测 bug。
- **丢 `source` 链**:`map_err(|_| MyError::Generic)` 把根因抹了 —— 用 `#[from]`/`#[source]` 留链。
- **错误消息大写带标点**:破坏与上层消息的拼接惯例。
- **过早降级**:把 `Result` 吞成 `unwrap`、把强类型错误降成 `String` 图省事 —— 默认不做(见 SKILL.md 核心姿态)。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **错误(`err-*`,12 条)** 全类;配套反模式 `anti-panic-expected` / `anti-unwrap-abuse` / `anti-expect-lazy` / `anti-empty-catch`;文档段 `doc-errors-section` / `doc-panics-section` / `doc-question-mark`
- 跨域:async 里的错误传播与并发失败聚合见 [`concurrency-async.md`](concurrency-async.md);用类型把"非法输入"挡在边界见 [`types-traits-generics.md`](types-traits-generics.md)(`api-parse-dont-validate`)
- 深度:[`deep/_index.md`](deep/_index.md) 的错误处理 idioms;配方见 [`recipes/_index.md`](recipes/_index.md) 中"自定义错误类型 / 错误链"条目

## 参考

- The Book ch.9(`panic!` vs `Result`、`?`、何时 panic)
- `std` 文档:`Result`、`Option`、`std::error::Error`(尤其 `source()`)、`std::process::Termination`
- crate docs.rs:`thiserror`(`#[derive(Error)]` / `#[error]` / `#[from]` / `#[source]`)、`anyhow`(`Result` / `Context` / `bail!` / `ensure!`)、`eyre`
- API Guidelines:`C-GOOD-ERR`(实现标准 trait)、`C-FAILURE`(文档化失败)
