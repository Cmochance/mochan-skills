# 性能 / profiling / 分配 / zero-cost

Rust 默认就快,但"快"不等于"已优化"。本域的第一原则是**先测量定位热点,再动手**——别凭直觉改。

适用:程序跑得慢、想知道时间花在哪、热路径分配过多、迭代器 vs 索引取舍、`#[inline]` 该不该加、release profile(`lto`/`codegen-units`/`panic`)怎么配、`clone` 开销、数据布局(SoA/AoS、`#[repr]`)。

> 反面信号:还没 profile 就开始 `#[inline(always)]` 满天飞、把清晰代码改成 `unsafe` 索引、为"感觉快"而牺牲可读性。见 [`anti-premature-optimize`](rules/anti-premature-optimize.md)。

---

## 决策顺序(性能工作的正确次序)

1. **先确认值得优化**:有明确的延迟/吞吐目标或用户可感的慢,才开工;否则停。
2. **测量,定位热点**:`cargo flamegraph`(底层 perf/dtrace)出火焰图,或 `perf`/`samply`/Instruments;找到真正吃时间的函数,别猜。→ [`perf-profile-first`](rules/perf-profile-first.md)
3. **建立基准**:用 `criterion` 给热点函数立 benchmark,记录 before 数字(统计严谨,见下)。
4. **针对热点改一处**:减分配 / 改算法 / 调 profile,一次一个变量。
5. **重测对比**:`criterion` 自动报 regression/improvement;没数据支撑的"更快了"不算数。
6. 还不够 → 才考虑 `unsafe`/SIMD/PGO 等重武器,且每步都留 benchmark。

## 减少分配(热路径最大杠杆)

堆分配通常是热路径首要开销。按影响排序:

- **预留容量**:已知大小用 `Vec::with_capacity`/`String::with_capacity`,避免多次 realloc。→ [`mem-with-capacity`](rules/mem-with-capacity.md)
- **复用缓冲**:循环里 `buf.clear()` 复用而非每轮 `Vec::new()`;`drain`/`clone_from` 复用已分配内存。→ [`mem-reuse-collections`](rules/mem-reuse-collections.md)、[`perf-drain-reuse`](rules/perf-drain-reuse.md)、[`mem-clone-from`](rules/mem-clone-from.md)
- **栈上小集合**:元素少且大小可控时用 `SmallVec`/`ArrayVec`(`smallvec`/`arrayvec` crate)免堆分配。→ [`mem-smallvec`](rules/mem-smallvec.md)、[`mem-arrayvec`](rules/mem-arrayvec.md)
- **借/拥有二选一**:多数情况不需分配新串时用 `Cow<'a, str>`。→ 见 [`ownership-lifetimes.md`](ownership-lifetimes.md) 的 `own-cow-conditional`
- **别在热路径 `format!`**:`format!` 每次分配 `String`;改用 `write!(buf, ...)` 写进复用缓冲。→ [`anti-format-hot-path`](rules/anti-format-hot-path.md)、[`mem-avoid-format`](rules/mem-avoid-format.md)、[`mem-write-over-format`](rules/mem-write-over-format.md)
- **批量 extend**:`extend`/`collect` 一次性灌入优于逐个 `push`。→ [`perf-extend-batch`](rules/perf-extend-batch.md)、[`perf-collect-into`](rules/perf-collect-into.md)

## 迭代器 vs 索引

- **迭代器是零成本抽象**:`iter().map().filter().sum()` 编译后等同手写循环,且**省掉边界检查**(编译器知道不越界)。优先迭代器而非 `for i in 0..n { v[i] }`。→ [`perf-iter-over-index`](rules/perf-iter-over-index.md)、[`anti-index-over-iter`](rules/anti-index-over-iter.md)、[`opt-bounds-check`](rules/opt-bounds-check.md)
- **保持惰性,别中途 collect**:链式适配器全程惰性,避免 `collect` 出中间 `Vec` 再继续处理。→ [`perf-iter-lazy`](rules/perf-iter-lazy.md)、[`anti-collect-intermediate`](rules/anti-collect-intermediate.md)、[`perf-collect-once`](rules/perf-collect-once.md)

## `#[inline]` 的取舍

| 场景 | 选择 | 规则 |
|---|---|---|
| 跨 crate 调用的小函数(默认不内联) | `#[inline]`(建议,非强制) | [`opt-inline-small`](rules/opt-inline-small.md) |
| 同 crate 小函数 | 多数无需标(优化器自决) | — |
| 确属冷路径(错误/慢径) | `#[inline(never)]` + `#[cold]` | [`opt-inline-never-cold`](rules/opt-inline-never-cold.md)、[`opt-cold-unlikely`](rules/opt-cold-unlikely.md) |
| 真要强制(罕见,有 benchmark 证据) | `#[inline(always)]` | [`opt-inline-always-rare`](rules/opt-inline-always-rare.md) |

> `#[inline(always)]` 是少数情况:乱用会撑大代码体积、拖累 i-cache,反而更慢。没有 benchmark 数字就别加。

## release profile 调优

`[profile.release]`(`Cargo.toml`)是改一行就生效的整体杠杆:

- `opt-level`:默认 3(全速);`"s"`/`"z"` 优化体积。
- `lto = "thin"`(或 `true`/`"fat"`):跨 crate 内联,通常提速、显著拖慢编译。→ [`opt-lto-release`](rules/opt-lto-release.md)
- `codegen-units = 1`:更激进优化(单元越少越能跨函数优化),编译更慢。→ [`opt-codegen-units`](rules/opt-codegen-units.md)
- `panic = "abort"`:去掉 unwind 表,二进制更小、可能略快(代价:无法 `catch_unwind`)。
- `target-cpu=native`(`RUSTFLAGS`):为本机 CPU 启用 SIMD 等指令集,**牺牲可移植性**。→ [`opt-target-cpu`](rules/opt-target-cpu.md)
- 进阶:PGO(profile-guided)、portable SIMD。→ [`opt-pgo-profile`](rules/opt-pgo-profile.md)、[`opt-simd-portable`](rules/opt-simd-portable.md)、[`perf-release-profile`](rules/perf-release-profile.md)

> benchmark 必须在 `--release` 下跑;debug build 的性能数字毫无参考价值。

## 借用 vs clone / 数据布局

- **`clone` 不是免费的**:`Vec`/`String`/`HashMap` clone = 堆分配 + 拷贝。能借 `&` 就别 clone;真要 clone 要显式有理由。→ [`anti-clone-excessive`](rules/anti-clone-excessive.md)
- **`Box<[T]>` vs `Vec<T>`**:不再增长的序列用 `Box<[T]>`,省掉 capacity 字段、表意"已定型"。→ [`mem-boxed-slice`](rules/mem-boxed-slice.md)
- **大 enum 变体装箱**:某变体远大于其它时 `Box` 它,缩小 enum 整体 size。→ [`mem-box-large-variant`](rules/mem-box-large-variant.md)、[`mem-assert-type-size`](rules/mem-assert-type-size.md)(用 `static_assertions` 钉住 size)
- **缓存友好布局**:顺序访问、SoA vs AoS、缩小热数据;`#[repr(C)]`/`#[repr(transparent)]` 控制布局。→ [`opt-cache-friendly`](rules/opt-cache-friendly.md)、[`mem-smaller-integers`](rules/mem-smaller-integers.md)(`u32` 够就别 `u64`)
- **哈希更快**:非抗 DoS 场景用 `ahash`/`FxHashMap` 替默认 SipHash。→ [`perf-ahash`](rules/perf-ahash.md)

## 典型坑

- **凭直觉优化**:没 profile 就改,常优化了不热的地方,白费力还伤可读性。
- **micro-bench 被优化掉**:`criterion` 里不用 `black_box` 包裹,优化器把整段算掉,测出"0ns"。→ [`perf-black-box-bench`](rules/perf-black-box-bench.md)
- **拿 debug build 测速**:慢几十倍,结论全错。
- **过早 `unsafe`**:为绕边界检查上 `get_unchecked`,而迭代器本就没边界检查——白冒 UB 风险。
- **I/O 未缓冲**:逐字节读写裸 `File`/`TcpStream` 慢;用 `BufReader`/`BufWriter`。→ [`perf-io-buffering`](rules/perf-io-buffering.md)

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **性能(`perf-*`)**、**优化(`opt-*`)**、**内存/分配(`mem-*`)** 三类;反模式 `anti-premature-optimize`/`anti-format-hot-path`/`anti-collect-intermediate`/`anti-index-over-iter`
- 工具:[`toolchain-and-mcp.md`](toolchain-and-mcp.md)(`cargo flamegraph`/`samply`/`hyperfine`/criterion);profiling 与 `criterion` benchmark 见 [`testing.md`](testing.md)
- 内存/智能指针/借用开销见 [`ownership-lifetimes.md`](ownership-lifetimes.md)

## 参考

- The Rust Performance Book(nnethercote)——profiling、分配、布局的权威清单
- `criterion` 文档(docs.rs/criterion)、`flamegraph` README
- `std` 文档:`Vec::with_capacity`、`Cow`、`std::hint::black_box`
- 具体 crate API(smallvec/arrayvec/ahash)以 docs.rs 为准,不确定别凭记忆写
