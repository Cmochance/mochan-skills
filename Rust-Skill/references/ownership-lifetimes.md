# 所有权 / 借用 / 生命周期 / 内部可变性

Rust 最独特、也最容易卡住的一层。**借用检查器报错先来这**(配合 [`error-codes.md`](error-codes.md))。

适用:E0382/E0499/E0502/E0505/E0507/E0515/E0597/E0621 等;"move 后不能用"、"cannot borrow as mutable"、"borrowed value does not live long enough"、"returns a value referencing data owned by the current function";以及"该用 Box / Rc / Arc / RefCell / Cow 哪个"。

---

## 心智模型(先建立,再排错)

- **每个值有唯一所有者**;所有者离开作用域 → 值被 drop(RAII)。
- **移动(move)默认**:非 `Copy` 类型赋值/传参是 move,原变量失效。`Copy` 类型(整数/`bool`/`char`/小元组等)是按位复制。
- **借用(`&` / `&mut`)**:同一时刻,要么**多个共享引用 `&`**,要么**唯一可变引用 `&mut`**,二者不可兼得(别名 ⊕ 可变)。这条规则是大多数借用报错的根。
- **生命周期**:引用不能活得比被引用对象久。编译器用它静态保证无悬垂引用。

排错套路:看报错码 → 判断是「move 问题」「别名+可变冲突」还是「生命周期不够长」→ 对症,而不是盲目加 `&`/`clone`。

## move vs 借用 vs 克隆(决策顺序)

遇到"值被 move 走了/借用冲突",按这个顺序考虑,**`clone` 在很后面**:

1. **借用就够吗?** 函数只读 → 收 `&T`;只读切片 → 收 `&[T]`/`&str` 而非 `&Vec`/`&String`。→ [`own-borrow-over-clone`](rules/own-borrow-over-clone.md)、[`anti-vec-for-slice`](rules/anti-vec-for-slice.md)、[`anti-string-for-str`](rules/anti-string-for-str.md)
2. **是 `Copy` 小类型吗?** 小而无堆的类型可派生 `Copy` 免 move 烦恼。→ [`own-copy-small`](rules/own-copy-small.md)
3. **重构所有权**:让数据流单向、谁用谁拥有;返回 owned 值而非借局部(E0515)。→ [`own-move-large`](rules/own-move-large.md)
4. **真要共享**:见下「共享与内部可变性」。
5. **最后才 `clone`**,且**显式、有理由**——不是为了消报错。无谓 clone 是新手最常见坏味道。→ [`own-clone-explicit`](rules/own-clone-explicit.md)、[`anti-clone-excessive`](rules/anti-clone-excessive.md)、[`mem-clone-from`](rules/mem-clone-from.md)(复用已分配)

## 生命周期标注

- **省略规则**:多数函数不用写 `'a`(编译器自动)。需要手写通常是:返回引用、struct 持有引用、多个引用输入需关联。→ [`own-lifetime-elision`](rules/own-lifetime-elision.md)
- **返回引用**:返回值的生命周期必须来自某个输入参数;返回局部的引用 → 改返回 owned(E0515)。
- **struct 存引用**:`struct S<'a> { x: &'a T }` 让 S 不能活过 `x`。多数情况**改存 owned 或 `Arc`** 更省心,除非确有零拷贝需求。
- **`'static`**:要么真全局/常量,要么 owned 且不借任何短命数据。闭包/spawn 要求 `'static` 时,`move` + clone/`Arc` 进去。

## 共享与内部可变性(选型表)

| 需求 | 用 | 规则 |
|---|---|---|
| 单线程多所有者(只读共享) | `Rc<T>` | [`own-rc-single-thread`](rules/own-rc-single-thread.md) |
| 多线程多所有者 | `Arc<T>` | [`own-arc-shared`](rules/own-arc-shared.md) |
| 单线程共享 + 可变 | `Rc<RefCell<T>>` | [`own-refcell-interior`](rules/own-refcell-interior.md) |
| 多线程共享 + 可变(互斥) | `Arc<Mutex<T>>` | [`own-mutex-interior`](rules/own-mutex-interior.md) |
| 多线程读多写少 | `Arc<RwLock<T>>` | [`own-rwlock-readers`](rules/own-rwlock-readers.md) |
| 借/拥有二选一(按需 clone) | `Cow<'a, T>` | [`own-cow-conditional`](rules/own-cow-conditional.md) |

> 注意:`RefCell` 把借用检查挪到**运行期**(违反会 panic);`Mutex`/`RwLock` 在 async 里别持锁过 `.await`(见 [`concurrency-async.md`](concurrency-async.md))。能用 `&`/`&mut` 静态借用就别急着上这些。

## drop 顺序与资源管理

- 变量按**声明逆序** drop;struct 字段按声明顺序 drop。涉及锁释放、文件关闭、清理时序时要留意。→ [`mem-drop-order`](rules/mem-drop-order.md)
- 提前释放:`drop(x)` 显式;或用块作用域 `{ let g = lock(); ... }` 让 guard 早 drop。
- 从借用后 move out:用 [`mem-take-replace`](rules/mem-take-replace.md)(`std::mem::take`/`replace`)避免 E0507。

## 典型坑

- **为消报错而 `clone`**:先问"借用够不够"。clone 满天飞 = 没理解所有权。
- **struct 存引用引发生命周期传染**:层层 `'a`,改存 owned/`Arc` 多数更好。
- **`RefCell` 运行期 panic**:`already borrowed`——同时拿了 `borrow_mut` 和 `borrow`。
- **自引用结构**:Rust 原生不支持;需要时用索引/`Rc`/`Pin`/`ouroboros`/`rental`,别硬来。
- **闭包捕获**:默认按引用借,导致生命周期/`Send` 问题;`move` 闭包按值捕获。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **所有权(`own-*`)** 与 **内存/智能指针(`mem-*`)** 两类(共 29 条)
- 深度:[`deep/_index.md`](deep/_index.md) 的 idioms(`mem::replace`、`Cow`、默认特质)与 anti-patterns(`Deref` 多态、`clone` 满足借用检查器)
- 配方:见 [`recipes/_index.md`](recipes/_index.md) 中涉及缓冲复用、零拷贝解析的条目

## 参考

- The Book ch.4(Ownership)、ch.10.3(Lifetimes)、ch.15(Smart Pointers)
- Rustonomicon(`'static`、子类型与方差、`Pin`)
- `std` 文档:`Rc`/`Arc`/`Cell`/`RefCell`/`Cow`/`std::mem`
