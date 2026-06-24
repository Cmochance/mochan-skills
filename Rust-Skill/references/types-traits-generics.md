# 类型系统 / trait / 泛型 / 单态化 / typestate

让编译器替你扛约束的一层。**"这调用没有那个方法 / 没实现那个 trait / 类型不匹配"先来这**(配合 [`error-codes.md`](error-codes.md))。

适用:E0277(未满足 trait bound)、E0308(类型不匹配)、E0599(方法/关联项不存在)、E0038(trait 非 object-safe、不能 `dyn`)、E0119/E0117(impl 冲突 / 孤儿规则)、E0207(未约束的类型参数)、E0271(关联类型不匹配);以及"泛型还是 `dyn`"、"关联类型还是泛型参数"、"`impl Trait` 放哪"、"怎么用类型把非法状态变得不可表达"。

---

## 心智模型(先建立,再设计)

- **trait = 行为契约**:定义"能做什么"(方法集 + 关联项),类型 `impl` 它来兑现。约束写成 trait bound,编译期校验。
- **泛型 `<T: Trait>` = 静态分发**:每个具体 `T` 单态化(monomorphization)生成一份特化代码,调用直接 inline,零运行期开销,但代码膨胀、编译变慢。
- **`dyn Trait` = 动态分发**:统一一份代码,运行期经 vtable 查方法,有一次间接跳转 + 胖指针(数据指针 + vtable 指针),换来异构集合与更小二进制。
- **关联类型 = trait 的"输出类型"**:由 impl 一次性钉死(每个实现类型对一个 trait 只有一组关联类型);泛型参数则是"输入类型",同一类型可对不同参数多次实现。
- **类型即约束**:能用类型让非法状态**不可表达**(newtype / enum 穷举 / typestate),就别靠运行期 if 兜底。这是 Rust 类型系统的最大杠杆。

设计套路:先问"调用方需要异构存一堆吗 / 要不要进 `Vec`、跨 FFI 边界"——要 → `dyn`;否则默认泛型静态分发。

## 静态分发(泛型)vs 动态分发(`dyn`)— 决策

| 场景 | 选 | 理由 / 规则 |
|---|---|---|
| 默认、单一具体类型、热路径 | 泛型 `<T: Trait>` / `impl Trait` | 单态化 inline,零开销 → [`trait-dyn-vs-generic`](rules/trait-dyn-vs-generic.md) |
| 异构集合(`Vec<Box<dyn Trait>>`) | `dyn Trait` | 静态分发存不下不同类型 → [`trait-dyn-vs-generic`](rules/trait-dyn-vs-generic.md) |
| 插件 / 回调 / 想缩二进制体积、压编译时间 | `dyn Trait` | 一份代码,vtable 间接调用代价可接受 |
| 闭包作参数/返回 | `impl Fn` vs `Box<dyn Fn>` 同理 | → [`closure-static-vs-dyn`](rules/closure-static-vs-dyn.md)、[`closure-fn-trait-bounds`](rules/closure-fn-trait-bounds.md)、[`closure-impl-fn-return`](rules/closure-impl-fn-return.md) |

> 经验:**先泛型,被异构需求逼到了再退 `dyn`**。别一上来 `Box<dyn Trait>` 兜底——那常是没想清类型关系的味道(见 [`anti-type-erasure`](rules/anti-type-erasure.md))。

## trait bound 与 `where`

- 简单约束写在尖括号:`fn f<T: Clone + Debug>(x: T)`;约束多/长时移到 `where` 子句,签名更清爽:`where T: Clone + Debug, U: Iterator<Item = T>`。
- **blanket impl**(`impl<T: A> B for T`)给满足条件的所有类型批量实现,威力大但会吃掉孤儿规则的腾挪空间、也可能撞 E0119 冲突。→ [`trait-blanket-impl`](rules/trait-blanket-impl.md)
- 默认方法:在 trait 里给方法体,实现者可不重写。→ [`trait-default-methods`](rules/trait-default-methods.md)
- 给常见 trait 提供 impl(`Debug`/`Clone`/`Default`/`PartialEq`…)是好公民,多数能 `#[derive]`。→ [`api-common-traits`](rules/api-common-traits.md)、[`api-default-impl`](rules/api-default-impl.md)

## 关联类型 vs 泛型参数

- **一个实现类型对该 trait 只有一种"输出"** → 用**关联类型**(如 `Iterator::Item`、`Deref::Target`)。调用方写 `T::Item`,不用到处带类型参数,签名干净。→ [`trait-associated-type-vs-generic`](rules/trait-associated-type-vs-generic.md)
- **同一类型要对多种参数都实现** → 用**泛型参数**(如 `From<T>`:`String` 同时 `From<&str>`、`From<char>`…)。
- 误用关联类型当输入会逼出 E0207(类型参数未被约束)或让 API 僵硬;误用泛型参数当输出会让调用方被迫到处标注。

## object safety(为什么不能 `dyn`,怎么改)

trait 要能 `dyn Trait`,必须 **object-safe**。常见违规(触发 E0038):

- 方法有泛型参数(`fn f<T>(&self, x: T)`)——vtable 装不下无限特化。
- 方法返回 `Self` 或在签名里用了 `Self`(除 receiver 外)。
- 有不带 `where Self: Sized` 的关联常量 / 关联函数(无 `self`)。

改法:把违规方法加 `where Self: Sized`(从 vtable 排除,只在静态分发时可用);或把泛型参数擦成 `&dyn`;或拆出一个 object-safe 子 trait。→ [`trait-object-safety`](rules/trait-object-safety.md)

## 孤儿规则与 newtype 绕过

**孤儿规则**(coherence):`impl Trait for Type`,**trait 或 Type 至少一个属于本 crate**,否则 E0117。防止两个外部 crate 给同一外部类型撞实现。

- 想给**外部类型**实现**外部 trait**(如给 `Vec<T>` impl 别人的 `Serialize` 之外的 trait)→ 用 **newtype** 包一层:`struct MyVec(Vec<T>)`,在 `MyVec` 上实现。→ [`trait-coherence-newtype`](rules/trait-coherence-newtype.md)、[`api-newtype-safety`](rules/api-newtype-safety.md)
- newtype 还能加语义不变量、避免参数顺序搞混(`UserId(u64)` vs `OrderId(u64)`)→ [`type-newtype-ids`](rules/type-newtype-ids.md)、[`type-newtype-validated`](rules/type-newtype-validated.md)
- 想对外暴露 trait 但禁止下游实现 → **sealed trait**(空私有 supertrait)→ [`api-sealed-trait`](rules/api-sealed-trait.md)

## 用类型编码状态机(typestate / phantom)

把"对象处于哪个状态"提升到**类型层**,非法转移在编译期就过不了:

- **typestate**:`Builder<Unset>` → `Builder<Set>`,只有 `Set` 态才有 `.build()`。误用顺序直接编译错。→ [`api-typestate`](rules/api-typestate.md)
- **PhantomData 标记**:`struct Conn<S> { _state: PhantomData<S> }`,`S` 不占内存只携带状态标签。→ [`type-phantom-marker`](rules/type-phantom-marker.md)
- **enum 表状态**:状态有限且要在运行期切换 → 用 enum + 穷尽 match,而非 typestate。→ [`type-enum-states`](rules/type-enum-states.md)
- 通用准则:**parse, don't validate** —— 在边界一次性把"未验证输入"解析成"已验证类型",之后全程靠类型保证。→ [`api-parse-dont-validate`](rules/api-parse-dont-validate.md)、[`anti-stringly-typed`](rules/anti-stringly-typed.md)、[`type-no-stringly`](rules/type-no-stringly.md)

## `impl Trait` 放哪

- **参数位**(`fn f(x: impl Trait)`):等价 `fn f<T: Trait>(x: T)` 的语法糖,静态分发,简洁。但拿不到那个类型名,无法 turbofish 指定。
- **返回位**(`fn f() -> impl Trait`):返回一个具体但不愿写出的类型(典型:迭代器、闭包、`Future`)。**只能返回单一具体类型**,分支返回不同类型要么 `Box<dyn>` 要么 enum 包装。→ [`closure-impl-fn-return`](rules/closure-impl-fn-return.md)
- trait 方法里的 async / `impl Trait` 返回有额外约束,见 [`concurrency-async.md`](concurrency-async.md) 的 `async-fn-in-trait`。

## 类型转换惯例

- `From`/`Into`:实现 `From`,自动获得 `Into`,**永远 impl `From` 而非 `Into`**。→ [`api-from-not-into`](rules/api-from-not-into.md)、[`api-impl-into`](rules/api-impl-into.md)
- 可失败转换:`TryFrom`/`TryInto`(带 `Error`)。→ [`conv-tryfrom-fallible`](rules/conv-tryfrom-fallible.md)
- 从字符串解析:`FromStr`(配 `str::parse`)。→ [`conv-fromstr-parsing`](rules/conv-fromstr-parsing.md)
- 借用视图:`AsRef`/`AsMut` 让 API 同时收 `String`/`&str`、`Vec`/`&[T]`。→ [`api-impl-asref`](rules/api-impl-asref.md)、[`conv-asmut-mutable`](rules/conv-asmut-mutable.md)

## 典型坑

- **过早 `Box<dyn Trait>`**:多数时候泛型更合适;类型擦除了就丢了具体类型信息和 inline 机会。→ [`anti-type-erasure`](rules/anti-type-erasure.md)
- **过度抽象**:为一个实现造一个 trait、泛型层层套——抽象要由≥2 个真实用例驱动。→ [`anti-over-abstraction`](rules/anti-over-abstraction.md)
- **关联类型/泛型参数选反**:输出当输入(E0207),或输入当输出(API 僵硬);照"该类型对此 trait 是否只有一种输出"判。
- **想 `dyn` 一个非 object-safe trait**:E0038 才发现;设计 trait 时若打算 `dyn`,提前避开泛型方法 / 返回 `Self`。
- **孤儿规则卡住外部 trait + 外部类型**:newtype 包一层,别想绕 coherence。
- **`String` 满天飞**(stringly-typed):状态、ID、枚举值都塞字符串 → 拼写错、非法值到运行期才炸。换 newtype / enum。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **trait(`trait-*`)**、**类型(`type-*`)**、**转换(`conv-*`)**、**闭包(`closure-*`)**、**const(`const-*`)** 类;API 设计相关见 `api-*`(`api-newtype-safety`/`api-sealed-trait`/`api-typestate`/`api-parse-dont-validate`)
- 深度:[`deep/_index.md`](deep/_index.md) 的 idioms(newtype、`From`/`Into`、临时可变性)与 anti-patterns(`Deref` 当多态、用 trait 强行复用)
- 配方/用例:见 [`recipes/_index.md`](recipes/_index.md)、[`examples/_index.md`](examples/_index.md) 中泛型容器、自定义迭代器、trait object 分发等条目

## 参考

- The Book ch.10(泛型/trait/生命周期)、ch.17.2(trait object)、ch.19.2-19.3(高级 trait:关联类型、newtype、typestate)
- Rust Reference:trait、coherence(孤儿规则)、`dyn`、object safety
- `std` 文档:`From`/`Into`/`TryFrom`/`AsRef`/`FromStr`/`PhantomData`/`Iterator`(关联类型范例)
- API Guidelines:`C-COMMON-TRAITS`、`C-CONV-TRAITS`、`C-NEWTYPE`、`C-SEALED`
