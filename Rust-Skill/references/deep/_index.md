# 设计模式深度层 (deep/) — 索引

> 近原样移植自《Rust Design Patterns》(rust-unofficial/patterns, **MPL-2.0**)。每文件头部保留来源与许可。
> 概览层点到为止时进这里读完整论述。按需读单文件,别全量预载。

> 与 [`../rules/`](../rules/_index.md) 的区别:rules 是一句话准则 + Bad/Good 速查;deep 是带动机、权衡、变体的**长文论述**。

## 惯用法 (Idioms)

- [`idiom__mem-replace`](idiom__mem-replace.md) — 用 mem::replace/take 从 &mut 后面取出值、避免无谓 clone
- [`idiom__constructors`](idiom__constructors.md) — 构造器惯例:new() 关联函数 + Default
- [`idiom__default-trait`](idiom__default-trait.md) — 为类型实现 Default 提供合理默认值
- [`idiom__finalisation-in-dtor`](idiom__finalisation-in-dtor.md) — 用 Drop 做收尾/finally 逻辑(即便 panic 也跑)
- [`idiom__on-stack-dyn-dispatch`](idiom__on-stack-dyn-dispatch.md) — 栈上动态分发:用变量延长临时量、避免 Box
- [`idiom__privacy-for-extensibility`](idiom__privacy-for-extensibility.md) — 用私有字段(#[non_exhaustive])保留向后兼容扩展空间
- [`idiom__temporary-mutability`](idiom__temporary-mutability.md) — 临时可变:初始化后用 shadowing 冻结为不可变
- [`idiom__coercion-in-arguments`](idiom__coercion-in-arguments.md) — 参数用 &str/&[T] 借用类型,靠 deref coercion 放宽入参
- [`idiom__return-consumed-on-error`](idiom__return-consumed-on-error.md) — 出错时把吃进去的参数还回去(Result 的 Err 带回所有权)
- [`idiom__pass-vars-to-closure`](idiom__pass-vars-to-closure.md) — 显式把变量(借用/clone/move)传进闭包
- [`idiom__iterating-over-option`](idiom__iterating-over-option.md) — Option 当 0/1 元素迭代器用
- [`idiom__concat-strings-format`](idiom__concat-strings-format.md) — 拼接字符串用 format! 而非链式 push_str
- [`idiom__deref-for-collections`](idiom__deref-for-collections.md) — 为集合 newtype 实现 Deref 暴露内部 API
- [`idiom__doc-test-init`](idiom__doc-test-init.md) — 文档示例里用函数隐藏重复初始化代码

## 设计模式 (Patterns)

- [`pattern__builder`](pattern__builder.md) — Builder 模式:链式构造复杂对象
- [`pattern__raii-guards`](pattern__raii-guards.md) — RAII 守卫:用生命周期管理资源与锁
- [`pattern__newtype`](pattern__newtype.md) — Newtype:零成本封装 + 类型安全 + 绕孤儿规则
- [`pattern__fold`](pattern__fold.md) — Fold:用累加器把数据折叠成结果
- [`pattern__strategy`](pattern__strategy.md) — Strategy:用 trait 把算法做成可替换策略
- [`pattern__command`](pattern__command.md) — Command:把动作封装成对象
- [`pattern__visitor`](pattern__visitor.md) — Visitor:把操作与数据结构解耦
- [`pattern__interpreter`](pattern__interpreter.md) — Interpreter:为小语言定义文法与求值
- [`pattern__compose-structs`](pattern__compose-structs.md) — 拆分 struct 以绕过借用检查器的整体借用限制
- [`pattern__trait-obj-default-bounds`](pattern__trait-obj-default-bounds.md) — 用 trait 给 trait object 提供默认实现边界
- [`pattern__prefer-small-crates`](pattern__prefer-small-crates.md) — 倾向小而专的 crate
- [`pattern__contain-unsafe-in-modules`](pattern__contain-unsafe-in-modules.md) — 把 unsafe 收敛在小模块里便于审计

## 反模式 (Anti-patterns)

- [`antipattern__deref-polymorphism`](antipattern__deref-polymorphism.md) — 反模式:用 Deref 模拟继承/多态
- [`antipattern__deny-warnings`](antipattern__deny-warnings.md) — 反模式:crate 顶 #![deny(warnings)] 的脆弱性
- [`antipattern__clone-to-satisfy-borrowck`](antipattern__clone-to-satisfy-borrowck.md) — 反模式:为讨好借用检查器而 clone

## 函数式 (Functional)

- [`functional__paradigms`](functional__paradigms.md) — 函数式范式在 Rust 的体现
- [`functional__generics-as-type-classes`](functional__generics-as-type-classes.md) — 泛型作为类型类(type class)
- [`functional__optics-lenses-prisms`](functional__optics-lenses-prisms.md) — Optics:lens/prism 在 Rust 类型系统的对应

## FFI

- [`ffi__exporting-rust-to-c`](ffi__exporting-rust-to-c.md) — 把 Rust API 安全导出给 C 的惯用法
- [`ffi__type-consolidation-wrappers`](ffi__type-consolidation-wrappers.md) — FFI:用包装类型整合 C 对象
- [`ffi__accepting-strings`](ffi__accepting-strings.md) — FFI:从 C 接收字符串的正确姿势
- [`ffi__passing-strings`](ffi__passing-strings.md) — FFI:把字符串传给 C 的正确姿势
- [`ffi__error-handling`](ffi__error-handling.md) — FFI:跨边界的错误码/错误处理
