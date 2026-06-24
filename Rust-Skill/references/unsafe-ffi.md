# unsafe / 裸指针 / FFI / UB

Rust 安全保证的"逃生舱口"。**碰 `unsafe` / FFI / UB 排查先来这**(配合 [`error-codes.md`](error-codes.md))。

适用:E0133(call to unsafe function / use of unsafe block requires unsafe context);绑定 C/C++ 库;裸指针解引用、`transmute`、`static mut`;`cargo miri` 报 UB("Undefined Behavior")、对齐/有效性/别名违规;`#[repr(C)]` 布局、`CStr/CString` 跨边界、所有权与生命周期穿越 FFI。

---

## 心智模型(先建立,再动手)

- **`unsafe` 不等于"关闭检查"**,而是"编译器证明不了这段不变量成立,我(程序员)来担保"。借用检查、类型检查在 `unsafe` 块里照常生效——它只多解锁五种能力(见下)。
- **不变量责任反转**:safe 代码里编译器替你证明无 UB;`unsafe` 里这个证明义务转给你。担保失败 = UB = 整个程序行为未定义(不止那一行),优化器可任意假设它不发生。
- **最小化 + 封装**:把 `unsafe` 缩到最小面积,外面包一层**安全抽象**,让调用方无需 `unsafe` 即可安全使用(`Vec`/`String` 内部全是 `unsafe`,API 却安全)。→ [`unsafe-minimize-scope`](rules/unsafe-minimize-scope.md)
- **每块都要能解释"为什么安全"**:不能写 `# Safety` 注释说明前提的 `unsafe`,就是你还没想清楚。→ [`unsafe-safety-comment`](rules/unsafe-safety-comment.md)、[`doc-safety-section`](rules/doc-safety-section.md)

## unsafe 解锁的五种能力(仅此五种)

1. **解引用裸指针** `*const T` / `*mut T`(创建裸指针是 safe,解引用才需 unsafe)。
2. **调用 unsafe fn / unsafe 方法**(含 FFI `extern` 函数)。
3. **访问 / 修改可变 static**(`static mut`,数据竞争风险;新代码优先 `OnceLock`/`atomic`/`Mutex` 而非 `static mut`)。
4. **实现 unsafe trait**(如手写 `Send`/`Sync`)。→ [`unsafe-send-sync-manual`](rules/unsafe-send-sync-manual.md)
5. **访问 union 字段**(读哪个字段有效由你担保)。

> 注意:`unsafe` **不**解锁绕过借用检查、不解锁解空指针"合法化"、不解锁数据竞争"变安全"。它只是承认"这些操作的安全性由我证明"。

## 决策顺序(要不要 unsafe / 怎么写)

1. **能用 safe 抽象吗?** 切片、迭代器、`split_at_mut`、`Cell`/`RefCell`、`MaybeUninit` 配套 API 往往已覆盖需求——先穷尽标准库。无谓 `unsafe` 是坏味道。
2. **是 FFI 必需吗?** 调 C/C++ 是 `unsafe` 的正当理由,但把裸接口包成安全 Rust API(见下)。
3. **是性能热点且已 profile 证实吗?** 跳过边界检查(`get_unchecked`)只在 profile 指认后做,且写清不变量。→ 先看 [`performance.md`](performance.md)。
4. **真要写**:最小块 + `// SAFETY:` 注释 + `unsafe fn` 配 `# Safety` rustdoc + `cargo miri test` 验。

## FFI 要点(绑 C 库)

- **声明外部函数**:`unsafe extern "C" { fn foo(x: c_int) -> c_int; }`;ABI 字符串常用 `"C"`。→ [`unsafe-extern-block`](rules/unsafe-extern-block.md)
- **导出给 C 调**:`#[unsafe(no_mangle)] pub extern "C" fn bar() {}`(`no_mangle` 现需 `unsafe(...)` 包裹,见 docs.rs/edition 说明)。→ [`unsafe-no-mangle-unsafe`](rules/unsafe-no-mangle-unsafe.md)
- **布局**:跨边界类型加 `#[repr(C)]`(稳定字段顺序/对齐),别用默认 `#[repr(Rust)]`(布局未定义)。零大小/单字段透传用 `#[repr(transparent)]`。
- **指针与所有权**:跨边界传 `*const T`/`*mut T`;**谁分配谁释放**——Rust 分配的内存别让 C `free`,反之亦然。返回给 C 的 owned 指针用 `Box::into_raw`,回收用 `Box::from_raw`(都在 `unsafe` 里)。
- **字符串**:Rust `&str`(UTF-8 无 nul)↔ C `char*`(nul 结尾)不等价。出参 `CString::new(s)?.into_raw()`;入参 `unsafe { CStr::from_ptr(p) }.to_str()?`。别把 `CString` 的指针存了又让它 drop(悬垂)。
- **整数类型**:用 `std::ffi::{c_int, c_char, c_void, c_uint, ...}` 而非硬编 `i32`,跨平台宽度才对。
- **回调**:传给 C 的 Rust 函数指针需 `extern "C"`;捕获环境的闭包不能直接当 C 回调(用 `void* userdata` 透传上下文的惯用法)。

## 绑定生成工具(选型)

| 方向 | 工具 | 何时用 |
|---|---|---|
| C 头文件 → Rust 绑定 | `bindgen` | 绑已有 C 库;`build.rs` 里跑或预生成 |
| Rust → C 头文件 | `cbindgen` | 把 Rust 库导出给 C 消费者 |
| C++ ↔ Rust(安全互调) | `cxx` | 需要 C++(类/模板/异常),`cxx` 生成双向安全桥、避免手写裸 FFI |
| 链接系统库 | `pkg-config`/`build.rs` | `cargo:rustc-link-lib=foo` 等指令 → [`proj-build-rs-minimal`](rules/proj-build-rs-minimal.md) |

> `bindgen` 产物全是 `unsafe extern` 裸接口,**必须**自己再包一层 safe wrapper(校验指针非空、管理生命周期、转换错误码为 `Result`),别让调用方直接碰生成的裸函数。`cxx` 因模型更安全,C++ 互操作优先考虑它而非 `bindgen`+手写。

## `transmute` 是最后手段

`std::mem::transmute<A, B>` 按位重解释,绕过类型系统,极易 UB。动它前确认:

- **尺寸相等**(`size_of::<A>() == size_of::<B>()`,否则编译错);**对齐兼容**;**位模式对目标类型有效**(如不能 transmute 出非法 `bool`/`char`/`enum` 判别值/悬垂引用——这些是即时 UB)。
- 多数场景有更安全替代:数值转换用 `as`/`TryFrom`(→ [`num-cast-try-from`](rules/num-cast-try-from.md));指针转换用 `as`/`.cast()`;字节↔类型用 `to_ne_bytes`/`from_ne_bytes` 或 `bytemuck`(校验过的 plain-old-data 转换)。
- 未初始化内存别 transmute,用 [`unsafe-maybeuninit`](rules/unsafe-maybeuninit.md)(`MaybeUninit<T>` + `assume_init`,严守"读前必写")。

## 用 Miri 检 UB

- `cargo +nightly miri test` 在解释器里跑测试,捕获越界、use-after-free、对齐错误、非法值、Stacked/Tree Borrows 别名违规——这些 `cargo test` 通常不报。改了任何 `unsafe` 都该跑。→ [`unsafe-miri-ci`](rules/unsafe-miri-ci.md)
- CI 里挂一条 miri job 守护 `unsafe` 代码(慢但值);配合 `cargo careful`、ASan/`-Zsanitizer` 进一步兜底。
- Miri 不是万能:它检测的是被执行到的路径,覆盖率取决于测试;它也不替代对 `# Safety` 不变量的人工审查。

## 典型坑

- **"`unsafe` 让报错消失了"**:多半是把 UB 藏起来,不是修好——优化后可能崩。Miri 跑一遍。
- **`transmute` 改大小/对齐不同的类型**:即时 UB;先查 `size_of`/`align_of`。
- **`CStr::from_ptr` 接了悬垂/非 nul 结尾指针**:读越界。确保指针存活且确为 C 字符串。
- **`static mut` 多线程访问**:数据竞争 UB。换 `atomic`/`Mutex`/`OnceLock`。
- **`Box::from_raw` 调两次 / 对非 `Box::into_raw` 来的指针调**:double-free。所有权流向要单一清晰。
- **手写 `unsafe impl Send/Sync` 没真满足条件**:把数据竞争伪装成安全。务必写清为何线程安全。→ [`unsafe-send-sync-manual`](rules/unsafe-send-sync-manual.md)
- **`#[repr(C)]` 漏标**:Rust 默认布局可重排字段,与 C struct 不一致 → 读错偏移。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **unsafe(`unsafe-*`,7 条)** 全类,加 [`doc-safety-section`](rules/doc-safety-section.md)、[`lint-unsafe-doc`](rules/lint-unsafe-doc.md)、[`num-cast-try-from`](rules/num-cast-try-from.md)、[`mem-assert-type-size`](rules/mem-assert-type-size.md)、[`proj-build-rs-minimal`](rules/proj-build-rs-minimal.md)
- 相邻概览:[`performance.md`](performance.md)(`get_unchecked`/SIMD 等需 unsafe 的优化)、[`types-traits-generics.md`](types-traits-generics.md)(`Send`/`Sync`/`repr`);系统/FFI 场景另见 `domain-systems.md`(规划中)
- 深度:见 [`deep/_index.md`](deep/_index.md) 中 FFI / unsafe 抽象相关条目

## 参考

- The Rustonomicon(unsafe 圣经:UB、别名、`transmute`、`Send`/`Sync`、`PhantomData`、exception safety)
- The Book ch.19.1(Unsafe Rust);`std::ptr` / `std::mem` / `std::ffi` 文档
- Rust FFI omnibus、`bindgen` / `cxx` / `cbindgen` 官方 user guide(docs.rs / 项目站)
- `cargo miri` README、Miri / Stacked Borrows 论文
