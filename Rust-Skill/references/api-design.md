# 公共 API 设计

库作者的判断层:让 API 难以误用、易于演进、读起来地道。**"这 API 怎么设计更 Rust"先来这**。

适用:设计公开类型/trait/函数签名;builder vs 多参数;newtype / sealed trait / `#[non_exhaustive]` / `#[must_use]` 取舍;该实现哪些 trait;入参/返回类型放宽;命名约定;对照 Rust API Guidelines。

---

## 心智模型(先建立,再设计)

- **parse, don't validate**:用类型让非法状态**不可表示**。把"已校验"编码进类型(解析一次得到强类型,之后无需反复校验),而不是到处传 `String`/`i32` 再每次 `if` 检查。→ [`api-parse-dont-validate`](rules/api-parse-dont-validate.md)、[`type-newtype-validated`](rules/type-newtype-validated.md)
- **让正确用法是唯一容易的用法**:好 API 让误用编译不过或显眼;类型签名是文档也是约束(`Result` 强制处理错误、`&mut` 表达独占、newtype 防参数顺序搞混)。
- **为演进留缝**:公开 enum/struct 加 `#[non_exhaustive]`、trait 用 sealed 模式,这样后续加变体/方法不算 breaking change。设计时就想"半年后要扩展怎么办"。
- **遵循生态惯例**:对齐 Rust API Guidelines(命名、trait 实现、`From`/`TryFrom`、`#[must_use]`),用户才能凭直觉用对。

## 用类型表达约束

- **newtype 增强类型安全 + 绕孤儿规则**:`struct UserId(u64)` 让 `UserId` 与 `OrderId` 不可互换、防参数顺序错;也可为外部类型包一层以在本 crate 实现外部 trait(绕开 orphan rule)。→ [`api-newtype-safety`](rules/api-newtype-safety.md)、[`type-newtype-ids`](rules/type-newtype-ids.md)、[`trait-coherence-newtype`](rules/trait-coherence-newtype.md)
- **构造时校验、之后免检**:校验放进构造函数返回 `Result<Self, Error>`,字段私有,外部拿到的实例必然合法。→ [`type-newtype-validated`](rules/type-newtype-validated.md)
- **用 enum 表达状态、`Option` 表达可空、`Result` 表达可失败**,别用魔法值/`-1`/空字符串。→ [`type-enum-states`](rules/type-enum-states.md)、[`type-option-nullable`](rules/type-option-nullable.md)、[`type-result-fallible`](rules/type-result-fallible.md)、[`type-no-stringly`](rules/type-no-stringly.md)
- **typestate**:把对象状态编码进类型参数,让"未连接时不能 send"这类约束编译期成立。→ [`api-typestate`](rules/api-typestate.md)

## builder 模式

- **可选参数多 / 未来可能增参时用 builder**:`Foo::builder().a(1).b(2).build()`,比一长串位置参数或一堆 `new_with_xxx` 可读且可演进。→ [`api-builder-pattern`](rules/api-builder-pattern.md)
- **builder 和 `build()` 标 `#[must_use]`**:链式方法返回 builder、`build()` 返回成品,不用就是 bug,`#[must_use]` 让编译器警告丢弃。→ [`api-builder-must-use`](rules/api-builder-must-use.md)、[`api-must-use`](rules/api-must-use.md)
- 参数少且稳定时,直接 `new(a, b)` 更简单——别为没必要的灵活性上 builder。

## 为演进留余地

- **`#[non_exhaustive]`**:加在公开 enum 上,下游 `match` 必须带 `_ =>` 通配,这样你后加变体不破坏下游;加在 struct 上则下游不能用字面量构造、必须走你的构造器。→ [`api-non-exhaustive`](rules/api-non-exhaustive.md)
- **sealed trait**:trait 内引用一个私有 supertrait,使下游无法 impl 你的 trait——你就能后加方法不算 breaking,且能控制实现者集合。→ [`api-sealed-trait`](rules/api-sealed-trait.md)
- **`#[must_use]`** 用在"忽略返回值几乎肯定是 bug"的类型/函数上(`Result`、builder、`Iterator` 适配器、纯查询)。→ [`api-must-use`](rules/api-must-use.md)

## 该实现的常见 trait

公开类型默认尽量实现(能 `derive` 就 `derive`):`Debug`(几乎必备,便于排错/日志)、`Clone`、`Default`(有合理默认时)、`PartialEq`/`Eq`、`Hash`(要进 map/set 时)、`PartialOrd`/`Ord`(可排序时)。→ [`api-common-traits`](rules/api-common-traits.md)、[`api-default-impl`](rules/api-default-impl.md)、[`type-display-vs-debug`](rules/type-display-vs-debug.md)(`Display` 面向用户、`Debug` 面向开发者,别混)

转换 trait 用对方向:

- **实现 `From` 而非 `Into`**:`impl From<A> for B` 会自动给到 `Into<B> for A`,反之不行;且 `From` 不会失败。→ [`api-from-not-into`](rules/api-from-not-into.md)、[`api-impl-into`](rules/api-impl-into.md)
- **可失败转换用 `TryFrom`**;字符串解析用 `FromStr`(让 `"...".parse()` 可用)。→ [`conv-tryfrom-fallible`](rules/conv-tryfrom-fallible.md)、[`conv-fromstr-parsing`](rules/conv-fromstr-parsing.md)

## 入参放宽 / 返回收紧

- **入参用泛型放宽**:接 `impl AsRef<str>`/`impl AsRef<Path>` 让调用方传 `&str`/`String`/`&String` 都行;接 `impl IntoIterator<Item = T>` 比硬要 `Vec<T>` 灵活;只读切片收 `&[T]`/`&str` 而非 `&Vec`/`&String`。→ [`api-impl-asref`](rules/api-impl-asref.md)、[`api-impl-fromiterator`](rules/api-impl-fromiterator.md)、[`conv-asmut-mutable`](rules/conv-asmut-mutable.md)
- **返回具体类型**:返回 `Vec<T>`/具体 struct / `impl Iterator`,而非 `Box<dyn ...>`(除非确需类型擦除);调用方拿到更多信息、零额外开销。
- 别过度泛型化到伤可读性——放宽是为常见调用便利,不是炫技。

## 命名约定(所有权语义写进名字)

| 前缀/约定 | 含义 | 规则 |
|---|---|---|
| `as_xxx` | 借用转换、零成本、不改所有权(`&self -> &U`) | [`name-as-free`](rules/name-as-free.md) |
| `to_xxx` | 可能有成本的转换、借用入(`&self -> U`,常含分配/克隆) | [`name-to-expensive`](rules/name-to-expensive.md) |
| `into_xxx` | 消耗所有权的转换(`self -> U`) | [`name-into-ownership`](rules/name-into-ownership.md) |
| `iter` / `iter_mut` / `into_iter` | 借用 / 可变借用 / 消耗 的迭代器 | [`name-iter-convention`](rules/name-iter-convention.md)、[`name-iter-method`](rules/name-iter-method.md) |
| `is_xxx` / `has_xxx` | 返回 `bool` 的查询 | [`name-is-has-bool`](rules/name-is-has-bool.md) |
| getter 不加 `get_` 前缀 | `fn name(&self)` 而非 `fn get_name` | [`name-no-get-prefix`](rules/name-no-get-prefix.md) |

类型 `CamelCase`、函数/变量 `snake_case`、常量 `SCREAMING_SNAKE_CASE`、acronym 当一个词(`HttpClient` 非 `HTTPClient`)。→ [`name-types-camel`](rules/name-types-camel.md)、[`name-funcs-snake`](rules/name-funcs-snake.md)、[`name-consts-screaming`](rules/name-consts-screaming.md)、[`name-acronym-word`](rules/name-acronym-word.md)、[`name-crate-no-rs`](rules/name-crate-no-rs.md)

## 文档与扩展

- 公开项写 rustdoc,失败函数写 `# Errors`、可 panic 写 `# Panics`、unsafe 写 `# Safety`、给可跑示例。→ [`doc-all-public`](rules/doc-all-public.md)、[`doc-errors-section`](rules/doc-errors-section.md)、[`doc-examples-section`](rules/doc-examples-section.md)
- **扩展 trait**:给外部类型加方法用 extension trait(`trait FooExt { ... } impl FooExt for Bar`),而非到处自由函数。→ [`api-extension-trait`](rules/api-extension-trait.md)
- serde 派生的可选字段用 `#[serde(default)]`/`skip_serializing_if` 保持兼容。→ [`api-serde-optional`](rules/api-serde-optional.md)

## 典型坑

- **stringly-typed API**:到处传 `String` 当枚举/ID/路径用,编译器帮不上忙、易错。换 enum/newtype。→ [`anti-stringly-typed`](rules/anti-stringly-typed.md)
- **公开 enum 没 `#[non_exhaustive]`**:加一个变体就是 breaking change,下游全炸。
- **实现了 `Into` 没实现 `From`**:别人拿不到自动的反向转换;永远写 `From`。
- **过度抽象**:为单一实现造 trait、为没人要的灵活性上泛型/builder,增加心智负担。→ [`anti-over-abstraction`](rules/anti-over-abstraction.md)
- **`Display` 和 `Debug` 混用**:面向用户的输出别依赖 `Debug` 格式(不稳定、含引号)。
- **公开字段泄漏不变量**:校验过的类型把字段设公开,下游可绕过构造器造非法值;字段私有 + 访问器。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **API(`api-*`,17 条)**、**类型(`type-*`)**、**命名(`name-*`,16 条)**、**转换(`conv-*`)** 四类,加 [`anti-stringly-typed`](rules/anti-stringly-typed.md)、[`anti-over-abstraction`](rules/anti-over-abstraction.md)、[`trait-coherence-newtype`](rules/trait-coherence-newtype.md)
- 相邻概览:[`types-traits-generics.md`](types-traits-generics.md)(trait 设计 / 泛型 vs dyn / object safety)、[`macros.md`](macros.md)(derive 宏服务 API 人体工学);序列化兼容另见 `serde-data.md`(规划中)
- 深度:见 [`deep/_index.md`](deep/_index.md) 中 builder / newtype / typestate / sealed 等 idiom 条目

## 参考

- Rust API Guidelines(命名 / 互操作 / 可预测性 / 灵活性 / 类型安全 / 可演进 checklist——本域权威)
- The Book ch.10(泛型/trait)、ch.17(面向对象特性);Rust for Rust-aceans(API 演进、sealed、`#[non_exhaustive]`)
- "Parse, don't validate"(Alexis King);std 文档里 `From`/`TryFrom`/`AsRef`/`FromStr` 的约定
