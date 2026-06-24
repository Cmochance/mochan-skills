# rustc 错误码 → 根因域速查

Rust 报错带稳定错误码(`E0xxx`)。看到报错先在这查码,路由到根因域,**别盲目加 `&`/`clone`/生命周期标注试错**。完整解释:`rustc --explain E0382` 或 [doc.rust-lang.org/error_codes](https://doc.rust-lang.org/error_codes/error-index.html)。

> 用法:报错信息里抓出 `E0xxx` → 查下表 → 进「根因域」读机制 + 「相关规则」对照修法。`rustc --explain <code>` 给官方最小例子。

## 所有权 / 借用 / 移动 → `ownership-lifetimes.md`

| 码 | 含义 | 根因 / 相关规则 |
|---|---|---|
| **E0382** | use of moved value(移动后使用) | 值被 move 走;考虑借用 `&` / `clone` / `Copy` / 重构所有权。规则 `own-*`、`anti-clone-excessive` |
| **E0499** | 同一时刻多个可变借用 | 拆借用作用域 / 用索引分段 / `split_at_mut`。`own-*` |
| **E0502** | 可变借用与不可变借用并存 | NLL 作用域、先读后写。`own-*` |
| **E0505 / E0506** | move/assign 一个被借用的值 | 缩小借用生命周期。`own-*` |
| **E0507** | 从借用后面 move out(如 match 解构) | `ref` / `as_ref` / `std::mem::take` / `clone`。`mem-replace-take` |
| **E0508 / E0509** | 从数组/有 Drop 的类型 move out | `std::mem::replace` / 索引取引用 |
| **E0515** | 返回引用了局部变量的引用 | 返回 owned 值 / 调整所有权。`own-*` |
| **E0716** | 临时值被提前 drop | 绑定到 `let` 延长生命周期 |

## 生命周期 → `ownership-lifetimes.md`(生命周期段)

| 码 | 含义 | 根因 |
|---|---|---|
| **E0597** | borrowed value 活得不够久 | 被借对象生命周期 < 借用者;调整作用域/所有权 |
| **E0621** | 需要显式生命周期标注 | 给引用参数/返回标 `'a`;看省略规则 |
| **E0623 / E0495** | 生命周期不匹配 / 无法推断 | 显式标注、解开省略;考虑是否真需共享引用 |
| **E0312** | 生命周期约束不满足 | `'a: 'b` outlives 约束 |

## 类型 / Trait / 泛型 → `types-traits-generics.md`

| 码 | 含义 | 根因 / 相关规则 |
|---|---|---|
| **E0277** | trait bound 不满足(`T: Trait` 没实现) | 加约束 / 为类型实现 trait / 换类型。`trait-*`、`type-*` |
| **E0308** | 类型不匹配(mismatched types) | 看期望 vs 实际;`.into()`/`as`/`?`。`conv-*` |
| **E0599** | 方法/关联项不存在 | 缺 trait 在作用域(`use`)/ 类型不对 / 方法名错 |
| **E0038** | trait 不是 object-safe,不能 `dyn` | 用泛型 / 拆 trait / `where Self: Sized`。`closure-static-vs-dyn` |
| **E0119 / E0117** | 冲突实现 / 孤儿规则 | newtype 包一层再 impl。`api-newtype-safety` |
| **E0207** | 未约束的类型参数 | 用 `PhantomData` / 关联类型 |
| **E0282 / E0283** | 类型无法推断 / 有歧义 | 加 turbofish `::<T>` / 显式标注 |
| **E0271** | 关联类型不匹配 | 对齐 `Item = ...` 等关联类型 |

## 可变性 → `ownership-lifetimes.md`(可变性段)

| 码 | 含义 | 根因 |
|---|---|---|
| **E0594** | 给不可变绑定/字段赋值 | 加 `mut` / 用内部可变性(`Cell`/`RefCell`) |
| **E0596** | 对不可变引用取 `&mut` | 源头标 `mut` / 传 `&mut` / 内部可变性 |
| **E0384** | 给不可变变量二次赋值 | `let mut` / shadowing |

## 并发 / async → `concurrency-async.md`

| 症状(常无独立码,体现在 E0277) | 根因 / 相关规则 |
|---|---|
| `future is not Send` 无法 spawn | 持有非 `Send` 跨 await(如 `Rc`、`MutexGuard`)。`async-no-lock-await`、`async-clone-before-await` |
| `T: Sync` 不满足共享 | 用 `Arc<Mutex<T>>`/`Arc<RwLock<T>>`。`conc-*`、`mem-*` |
| 闭包要求 `'static` 但捕获了引用 | `move` + `Arc` / clone 进闭包。`closure-move-capture` |

## unsafe / FFI → `unsafe-ffi.md`

| 码 | 含义 | 根因 |
|---|---|---|
| **E0133** | unsafe 操作未在 unsafe 块中 | 包 `unsafe { }` 并写 `# Safety` 文档说明前提。`unsafe-*` |
| **E0152 / E0512** | lang item / transmute 尺寸不符 | 检查 `repr`、尺寸对齐;能不 transmute 就不 |

## 宏 → `macros.md`

| 症状 | 根因 |
|---|---|
| `macro_rules` 匹配失败 / 重复展开 | 检查 fragment specifier(`$x:expr`/`:ty`/`:tt`)、`$(...)*` 重复、卫生性。用 `cargo expand` 看展开 |
| proc-macro panic / 报错位置差 | `syn::Error::to_compile_error()` 给准确 span;`trybuild` 测错误信息 |

## Cargo / 工程 → `project-cargo.md`

| 症状 | 根因 |
|---|---|
| `can't find crate` / feature 未启用 | `Cargo.toml` 加依赖/feature;检查 `default-features` |
| 版本冲突 / 多版本同 crate | `cargo tree -d` 看重复;统一版本 / `[patch]` |
| `cfg` 条件没生效 | `#[cfg(feature = "x")]` 拼写;`--features` 传对 |

---

**通用排查纪律**:
1. 读完整报错(rustc 报错通常已指出问题行 + 建议),`--explain` 看官方例子。
2. 定位根因域,理解机制,**再**改——而不是对着报错位置加符号凑。
3. 改完 `cargo check` 确认,`clippy` 看有没有引入坏味道。
