# 宏 — 声明宏(macro_rules!)与过程宏

元编程层:生成代码而非运行时抽象。**写宏 / 宏展开不对 / syn·quote 调试先来这**。

适用:写 `macro_rules!` 但匹配/重复/卫生性出错;实现 derive / attribute / function-like 过程宏;`syn` 解析、`quote!` 生成、span/错误定位;`cargo expand` 看展开、`trybuild` 测编译失败用例。

---

## 心智模型(先建立,再动手)

- **宏在编译期把一段 token 变成另一段 token**(语法层,不是字符串拼接;在类型检查/借用检查**之前**展开)。它操作的是 AST 片段,不是值。
- **声明宏 vs 过程宏**:`macro_rules!` 是"模式 → 模板"的声明式替换,够用就别上过程宏;过程宏是任意 Rust 代码处理 `TokenStream`,更强但更重(单独 crate、编译更慢、依赖 syn/quote)。→ [`macro-prefer-functions`](rules/macro-prefer-functions.md)
- **能用函数/泛型/trait 解决就别写宏**。宏牺牲可读性、IDE 支持、报错质量换取语法灵活性;只在"普通抽象表达不了"时用(可变参数、DSL、重复样板、编译期代码生成)。→ [`macro-prefer-functions`](rules/macro-prefer-functions.md)

## macro_rules!(声明宏)

**fragment specifier**(`$name:kind` 里的 kind,决定匹配什么 + 后续能怎么用):

| specifier | 匹配 | 常见用途 |
|---|---|---|
| `expr` | 表达式 | 传值/计算 |
| `ty` | 类型 | 泛型样板、类型参数 |
| `ident` | 标识符 | 生成变量/函数/字段名 |
| `pat` / `pat_param` | 模式 | match 臂样板 |
| `path` | 路径(`a::b::C`) | 引用类型/函数路径 |
| `tt` | 单个 token tree | 最通用、可转发;递归宏常用 |
| `block` / `stmt` | 块 / 语句 | 包裹代码 |
| `literal` / `lifetime` / `meta` / `vis` | 字面量 / 生命周期 / 属性内容 / 可见性 | 各自场景 |

→ [`macro-fragment-specifiers`](rules/macro-fragment-specifiers.md)

**重复**:`$(...)sep rep`,`sep` 是可选分隔符(`,`),`rep` 是 `*`(0+)/`+`(1+)/`?`(0或1)。例:`$( $x:expr ),*` 匹配逗号分隔的表达式列表,展开端 `$( f($x); )*` 逐个展开。

**卫生性(hygiene)**:`macro_rules!` 卫生——宏内引入的局部变量不会捕获/被调用处同名变量捕获,标识符按定义处作用域解析。所以宏里 `let tmp = ...` 不会撞调用者的 `tmp`。但卫生性不完全覆盖所有情形(类型/路径较弱),跨 crate 路径要用 `$crate`。→ [`macro-rules-hygiene`](rules/macro-rules-hygiene.md)

**路径解析**:宏内引用本 crate 的项必须用 `$crate::path::to::Item`,否则在调用方 crate 里路径找不到(宏导出后在别处展开)。→ [`macro-export-crate-path`](rules/macro-export-crate-path.md)

**封装内部规则**:多分支宏的辅助/内部分支用 `@tag` 约定或 `#[doc(hidden)]` 隐藏,别暴露给用户。→ [`macro-private-helpers`](rules/macro-private-helpers.md)

## 过程宏(三类,需独立 crate)

过程宏必须放在 `proc-macro = true` 的独立 crate(`Cargo.toml` 里 `[lib] proc-macro = true`),不能和被它使用的代码同 crate。→ [`macro-proc-two-crate`](rules/macro-proc-two-crate.md)

| 类型 | 触发形式 | 签名(概念) |
|---|---|---|
| **derive** | `#[derive(MyTrait)]` | `(input: TokenStream) -> TokenStream`,标 `#[proc_macro_derive(MyTrait)]` |
| **attribute** | `#[my_attr(args)] fn f(){}` | `(attr: TokenStream, item: TokenStream) -> TokenStream`,标 `#[proc_macro_attribute]` |
| **function-like** | `my_macro!(...)` | `(input: TokenStream) -> TokenStream`,标 `#[proc_macro]` |

**核心三件套**:

- **`syn`** — 把 `TokenStream` 解析成结构化 AST(`syn::parse_macro_input!(input as DeriveInput)`、`syn::ItemFn`、`syn::Type` 等);解析属性参数可配 **`darling`**(把 `#[my(a = 1, b = "x")]` 解析成 struct,省去手撸)。
- **`quote`** — `quote! { ... }` 用模板生成 `TokenStream`,内插用 `#var`、重复用 `#( #items )*`(类似 macro_rules 重复)。
- **`proc-macro2`** — `syn`/`quote` 基于的 `TokenStream` 类型(可在非 proc-macro 上下文/测试里用);最终 `.into()` 成编译器的 `proc_macro::TokenStream`。

→ [`macro-proc-syn-quote`](rules/macro-proc-syn-quote.md)

## 过程宏错误定位

- **别 panic**:用 `syn::Error::new_spanned(tokens, "message").to_compile_error()` 生成带**正确 span** 的编译错误,让报错指到用户代码的具体位置,而非宏内部。→ [`macro-proc-error-spans`](rules/macro-proc-error-spans.md)
- 惯用骨架:`fn expand(input) -> syn::Result<TokenStream2>`,顶层 `match expand(...) { Ok(ts) => ts, Err(e) => e.to_compile_error() }.into()`,错误就近 `return Err(syn::Error::new_spanned(...))`。
- span 决定报错下划线位置和卫生上下文;`Span::call_site()`(调用处卫生)vs `Span::mixed_site()`,生成标识符时选对 span 才不会撞名或泄漏。

## 工具链(必备)

- **`cargo expand`** — 看宏展开后的真实代码,调试 `macro_rules!`/derive 的第一工具(基于 nightly,`cargo install cargo-expand`)。
- **`trybuild`** — 测**编译失败**用例:断言某段误用会报特定错误信息(过程宏错误质量的回归测试)。配合 `#[test]` 跑。
- **`macrotest`** — 快照式断言宏展开结果。
- 普通行为测试照常用 `#[test]`(过程宏的逻辑可对 `proc-macro2::TokenStream` 单测,不必每次进编译器)。

## 典型坑

- **卫生性误解**:`macro_rules!` 卫生导致宏内 `let x` 拿不到调用者的 `x`(这是特性不是 bug);确需共享标识符要把它作为参数传入(`$x:ident`)。过程宏默认**不**卫生(call_site span),反而易意外捕获/撞名。
- **漏 `$crate`**:宏内写 `crate::foo` 或裸 `foo`,导出到别的 crate 展开后路径失效。统一 `$crate::`。→ [`macro-export-crate-path`](rules/macro-export-crate-path.md)
- **递归展开上限**:递归 `macro_rules!`(尤其 `tt`-muncher)超默认深度报 "recursion limit reached",需 `#![recursion_limit = "256"]`,或重构减少递归。
- **fragment 跟随限制**:某些 specifier 后面只能跟特定 token(如 `expr` 后只能跟 `=>`/`,`/`;`),否则 "local ambiguity"。
- **过程宏 crate 边界**:把 `#[proc_macro]` 和普通函数放同 crate 编译失败;过程宏 crate 也不能直接被同 workspace 当普通库用其非宏项。
- **`syn` feature 没开全**:`syn` 默认 feature 精简,解析 `full` 语法(函数体/语句)要开 `features = ["full"]`,否则 parse 失败。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **宏(`macro-*`,8 条)** 全类(fragment-specifiers / rules-hygiene / export-crate-path / private-helpers / prefer-functions / proc-syn-quote / proc-two-crate / proc-error-spans)
- 相邻概览:[`api-design.md`](api-design.md)(derive 宏常服务于 API 人体工学)、[`types-traits-generics.md`](types-traits-generics.md)(很多 derive 是 trait 实现的样板)
- 深度:见 [`deep/_index.md`](deep/_index.md) 中元编程 / 代码生成相关条目

## 参考

- The Book ch.19.5(Macros);The Little Book of Rust Macros(`macro_rules!` 权威进阶,含 TT-muncher/internal rules)
- `syn` / `quote` / `proc-macro2` / `darling` docs.rs;`syn` 仓库 examples(`heapsize_derive` 等)
- Rust Reference: Macros(fragment specifier 跟随集、卫生性细则)
- `cargo expand`、`trybuild`、`macrotest` 项目 README
