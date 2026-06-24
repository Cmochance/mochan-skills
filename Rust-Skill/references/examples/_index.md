# Rust 概念用例 (examples/) — 索引

> 每篇聚焦一个语言/标准库概念,给最小可运行示例(Rust by Example 风格)。对照学习、照着改。

> 共 18 篇。按需读单文件,别全量预载。

- [`async-await-basics`](async-await-basics.md) — `async fn` 返回一个惰性 `Future`,`.await` 在等待点让出执行权;需要运行时(runtime)来驱动,最常用 `#[tokio::main]`。`join!` 并发跑多个 future。
- [`closures-and-iterators`](closures-and-iterators.md) — 闭包是能捕获环境的匿名函数,按需实现 `Fn`/`FnMut`/`FnOnce`;迭代器适配器(`map`/`filter`/`fold`)惰性组合,`collect`/`sum` 等消费者才真正驱动。
- [`collections`](collections.md) — `Vec`(增长序列)、`HashMap`(无序键值)、`HashSet`(去重)、`BTreeMap`(有序键值)覆盖绝大多数需求;`entry` API 是"按键更新"的惯用法。
- [`conversions`](conversions.md) — `From`/`Into` 是不会失败的转换(实现 `From` 自动得 `Into`);`TryFrom`/`TryInto` 是可能失败的(返 `Result`);`AsRef` 廉价借用转换;`str::parse` 经 `FromStr` 把字符串解析成类型。
- [`error-handling`](error-handling.md) — 可恢复错误用 `Result<T, E>`、可空用 `Option<T>`;`?` 自动传播并 `From` 转换错误类型;组合子(`map`/`and_then`/`unwrap_or`)避免显式 match。
- [`generics-and-bounds`](generics-and-bounds.md) — 泛型让一份代码服务多种类型;trait bound(`T: Trait`)约束"这些类型得能做什么";编译期单态化为每个具体类型生成专用代码。
- [`iterators-custom`](iterators-custom.md) — 实现 `Iterator`(给关联类型 `Item` + 一个 `next`)即可白嫖全部适配器;实现 `IntoIterator` 让类型能用于 `for`。
- [`lifetimes-in-action`](lifetimes-in-action.md) — 生命周期标注让编译器确认引用不悬垂;多数函数靠省略规则自动推断,只有"返回引用""struct 持引用""多引用需关联"时才手写 `'a`。
- [`modules-and-visibility`](modules-and-visibility.md) — `mod` 划分命名空间,默认私有;`pub` 对外暴露、`pub(crate)` 限本 crate;`use` 引入路径缩短引用。
- [`operator-overloading`](operator-overloading.md) — 运算符由 trait 驱动:`Add`/`Mul` 给 `+`/`*`、`Index` 给 `[]`、`PartialEq`/`PartialOrd` 给 `==`/`<`、`Display` 给 `{}`。实现对应 trait 即可让自定义类型用上这些语法。
- [`ownership-and-moves`](ownership-and-moves.md) — 每个值有唯一所有者;非 `Copy` 类型赋值/传参是 move,原变量失效。借用 `&`/`&mut` 让你用而不夺走所有权。
- [`pattern-matching`](pattern-matching.md) — `match` 必须穷尽,编译期保证没漏分支;`if let`/`let else`/`while let` 是单分支简写;模式支持解构、守卫、`@` 绑定、`|`。
- [`smart-pointers`](smart-pointers.md) — `Box<T>`(堆分配 / 递归类型)、`Rc<T>`(单线程多所有者)、`RefCell<T>`(运行期借用检查 / 内部可变),组合 `Rc<RefCell<T>>` 实现"共享 + 可变"。
- [`structs-and-enums`](structs-and-enums.md) — struct 把相关字段聚成一个类型;enum 表达"几选一"的状态、变体可带数据;`impl` 给它们挂方法与关联函数。
- [`threads-basics`](threads-basics.md) — `thread::spawn` 起 OS 线程、`join` 等它结束;`thread::scope` 允许借用栈数据的作用域线程;跨线程共享可变状态用 `Arc<Mutex<T>>`。
- [`trait-objects`](trait-objects.md) — `dyn Trait` 在运行期通过虚表分发,让不同具体类型存进同一容器;代价是间接调用 + 需 `Box`/`&` 包装(动态分发 vs 泛型的静态分发)。
- [`traits-basics`](traits-basics.md) — trait 是共享行为的契约;可给默认方法,为任意类型实现;`impl Trait` 让函数接受"任何满足契约的类型"。
- [`variables-and-types`](variables-and-types.md) — `let` 默认不可变,`mut` 才可变;基本标量类型(整数/浮点/bool/char)+ 复合(元组/数组)由编译器推断,必要时显式标注。
