# 并发与异步(线程 / `Send`+`Sync` / tokio / rayon / 锁 / channel)

把工作并行/并发跑、又不数据竞争的一层。**"`future is not Send`"、async 卡住/死锁、spawn 生命周期报错先来这。**

适用:"future cannot be sent between threads safely / is not `Send`"、`spawn` 要求 `'static` 报错、async 任务卡死或死锁、"`T` cannot be shared between threads safely"(缺 `Sync`)、选 `std::sync::Mutex` 还是 `tokio::sync::Mutex`、该用线程池还是 async。

---

## 心智模型(先建立,再写)

- **`Send` = 可在线程间转移所有权**;**`Sync` = `&T` 可在线程间共享**(即 `T: Sync` ⟺ `&T: Send`)。绝大多数类型自动派生,**`Rc`/`RefCell`/裸指针不是**。
- **async 的 `Future` 是状态机**:`.await` 是暂停点,跨 `.await` 还活着的局部变量被存进状态机。**这些变量必须 `Send`,整个 future 才 `Send`**,才能被多线程 runtime `spawn`。这是 `future is not Send` 的根。
- **runtime 调度任务,任务跨线程被搬运** → `tokio::spawn` 的 future 要 `Send + 'static`。
- **两套锁**:`std::sync::Mutex`(同步、持锁期间阻塞线程)vs `tokio::sync::Mutex`(异步、可跨 `.await` 持有、`.lock().await`)。选错是死锁/性能塌方的常见根。
- **CPU 密集 vs IO 密集是分水岭**:IO 等待 → async(少量线程驾驭海量并发连接);CPU 计算 → 线程池 / rayon(async runtime 被算满会饿死所有任务)。

排错套路:`not Send` → 找跨 `.await` 持有的非 `Send` 值(`Rc`、`MutexGuard`、`RefCell` borrow);async 卡住 → 查是不是持锁过 await 或在 async 上下文跑了阻塞调用。

## `Send` / `Sync` 与 "future is not Send"

根因几乎总是:**某个非 `Send` 的值跨过了 `.await` 还活着**。最常见两类:

1. **`Rc` / `RefCell` 跨 await**:换 `Arc` / `Arc<Mutex<_>>`(或重构成不跨 await)。
2. **`std::sync::MutexGuard` 跨 await**:`guard` 不是 `Send`,持着它 `.await` 直接让 future 变 `!Send`,而且**极易死锁**。

修法:**把需要的数据从锁里取出来、释放锁,再 `.await`**(extract-then-release)。或 clone 出要用的值后 `drop(guard)`。→ [`async-no-lock-await`](rules/async-no-lock-await.md)、[`anti-lock-across-await`](rules/anti-lock-across-await.md)、[`async-clone-before-await`](rules/async-clone-before-await.md)

```rust
// Bad:guard 跨 await → !Send + 可能死锁
let g = state.lock().unwrap();
do_async(&g.value).await;        // ✗

// Good:取出来、放锁、再 await
let v = { state.lock().unwrap().value.clone() };  // 锁在块末释放
do_async(&v).await;              // ✓
```

## 绝不持锁过 `.await`(头号铁律)

`std::sync::Mutex` 的 guard 跨 `.await`:① 让 future `!Send`;② 锁被持有期间该任务被挂起,**别的任务想拿锁就全卡死**(单线程 runtime 直接自死锁)。

- **首选**:extract→release 模式(上面),锁的临界区里**不出现 `.await`**。
- 确实需要"持有跨 await 的异步互斥"(临界区内必须 await)→ 用 **`tokio::sync::Mutex`**(`.lock().await`,guard 是 `Send`)。代价:比 std Mutex 慢,且仍可能逻辑死锁,能避则避。
- 共享状态首选 `Arc<...>` 包裹;内部可变用 `Arc<Mutex<T>>` / `Arc<RwLock<T>>`。→ [`own-arc-shared`](rules/own-arc-shared.md)、[`own-mutex-interior`](rules/own-mutex-interior.md)

## `std::sync::Mutex` vs `tokio::sync::Mutex`

| 选 | 当 | 理由 |
|---|---|---|
| `std::sync::Mutex` | 临界区**短、纯同步、不含 `.await`** | 更快;guard 块内即放,`!Send` 不外泄 → [`own-mutex-interior`](rules/own-mutex-interior.md) |
| `tokio::sync::Mutex` | 临界区内**必须 `.await`** | guard `Send`、`.lock().await` 不阻塞 runtime 线程;但更慢 |

> 默认用 `std::sync::Mutex` + extract-then-release;只有"临界区天然要 await"才上 tokio 版。别因为代码在 async 函数里就反射性换 tokio Mutex。

## `tokio::spawn` 的生命周期与边界

- `tokio::spawn(fut)` 要求 `fut: Future + Send + 'static`,返回 `JoinHandle`。
- **`'static`**:任务可能比当前栈帧活得久 → 不能借栈上短命数据。把要用的 `move` 进闭包:owned 值直接搬,共享数据 `Arc::clone` 后搬。→ [`async-clone-before-await`](rules/async-clone-before-await.md)
- 需要"借父作用域数据、结束前 join"的结构化并发 → 用 **`JoinSet`** 或 tokio 的 scoped 能力,而非裸 spawn。→ [`async-joinset-structured`](rules/async-joinset-structured.md)
- 同步线程同理:`std::thread::spawn` 也要 `'static + Send`;借栈数据用 **scoped threads**(`std::thread::scope`)。→ [`conc-scoped-threads`](rules/conc-scoped-threads.md)

## CPU 密集 vs IO 密集(放哪跑)

| 工作 | 放哪 | 规则 |
|---|---|---|
| IO 等待(网络/磁盘/DB) | async / `tokio` 任务 | 少线程撑海量并发 → [`async-tokio-runtime`](rules/async-tokio-runtime.md)、[`async-tokio-fs`](rules/async-tokio-fs.md) |
| 单个重 CPU 块混在 async 里 | `tokio::task::spawn_blocking` | 挪到阻塞线程池,别堵住 runtime → [`async-spawn-blocking`](rules/async-spawn-blocking.md) |
| 数据并行(map/reduce 大数组) | **rayon** `par_iter()` | work-stealing 线程池,改一行并行 → [`conc-rayon-par-iter`](rules/conc-rayon-par-iter.md) |
| 共享计数/标志 | 原子类型 + 选对 `Ordering` | 无锁,注意内存序 → [`conc-atomic-ordering`](rules/conc-atomic-ordering.md) |

> **在 async 任务里跑长 CPU 循环 = runtime 杀手**:它不让出,同 worker 上的所有任务饿死。重计算 `spawn_blocking` 或交给 rayon。

## channel(选型)

| 形态 | 用 | 规则 |
|---|---|---|
| 多生产者单消费者、任务队列 | `tokio::sync::mpsc`(**有界**带背压) | → [`async-mpsc-queue`](rules/async-mpsc-queue.md)、[`async-bounded-channel`](rules/async-bounded-channel.md) |
| 一次性请求-响应 | `tokio::sync::oneshot` | → [`async-oneshot-response`](rules/async-oneshot-response.md) |
| 广播给多订阅者 | `tokio::sync::broadcast` | → [`async-broadcast-pubsub`](rules/async-broadcast-pubsub.md) |
| 只关心"最新值"(配置/状态) | `tokio::sync::watch` | → [`async-watch-latest`](rules/async-watch-latest.md) |

> 默认用**有界** channel:无界会在消费跟不上时无限堆积内存,有界天然提供背压。

## 组合多个 future:`join` / `select` / `JoinSet`

| 要 | 用 | 语义 / 规则 |
|---|---|---|
| 并发跑多个、**全部**完成 | `tokio::join!` / `futures::join!` | 并发非并行,同任务内轮询 → [`async-join-parallel`](rules/async-join-parallel.md) |
| 并发跑、任一失败即短路 | `tokio::try_join!` | 任一 `Err` 立即返回 → [`async-try-join`](rules/async-try-join.md) |
| 竞速,**谁先好用谁**,其余取消 | `tokio::select!` | 注意**取消安全**:被丢弃分支的 future 中途状态可能丢 → [`async-select-racing`](rules/async-select-racing.md) |
| 动态一批任务、并发收集 | `JoinSet` | 结构化、可逐个 `join_next()` → [`async-joinset-structured`](rules/async-joinset-structured.md) |

## 取消与取消安全

- async future 被 drop 即取消 —— 在 `.await` 暂停点之间停下,**不保证跑完**。`select!` 落选分支、超时、任务 abort 都会触发。
- **取消安全(cancel-safe)**:future 在任意 `.await` 处被丢弃后,不会让共享状态处于半完成的坏态。`select!` 循环里的分支必须 cancel-safe,否则丢消息/破坏不变量。→ [`async-cancel-safety`](rules/async-cancel-safety.md)
- 主动取消用 `CancellationToken`(协作式)或 `JoinHandle::abort`。→ [`async-cancellation-token`](rules/async-cancellation-token.md)
- 非 cancel-safe 的操作(如"读一半的 buffer")别直接塞进 `select!`,改成"完成后才提交"或包一层使其原子。

## trait 里的 async

- Rust 1.75+ 原生支持 trait 中 `async fn`,但**返回的 future 默认不保证 `Send`**,跨多线程 runtime 用时常需 `Trait + Send` bound 或 `#[trait_variant::make(...)]`。复杂场景退回 `async-trait` 宏(`Box` future,有分配)。→ [`async-fn-in-trait`](rules/async-fn-in-trait.md)、[`async-async-fn-bounds`](rules/async-async-fn-bounds.md)

## 典型坑

- **持 `std::sync` guard 过 `.await`**:`!Send` + 死锁双杀。extract→release。
- **`Rc`/`RefCell` 在 async 里跨 await**:future 不 `Send`,无法 spawn。换 `Arc`/`Arc<Mutex>`。
- **async 任务里跑重 CPU**:饿死 runtime。`spawn_blocking` / rayon。
- **spawn 借栈数据报 `'static`**:`move` + clone / `Arc::clone` 进任务;或用 `JoinSet`/scoped。
- **无界 channel**:消费跟不上时内存爆。默认有界 + 背压。
- **`select!` 分支非 cancel-safe**:落选分支丢失中途进度 → 丢消息/状态半完成。
- **死锁**:同一任务对同一 `Mutex` 重复 lock、或多锁顺序不一致。临界区尽量短、固定加锁顺序。
- **反射性用 `tokio::sync::Mutex`**:多数同步临界区用 std Mutex 更快,只在临界区含 await 时才需 tokio 版。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **async(`async-*`,18 条)** 与 **并发(`conc-*`,4 条)** 全类;共享状态相关 `own-arc-shared` / `own-mutex-interior` / `own-rwlock-readers`;反模式 `anti-lock-across-await`
- 跨域:`Send`/`Sync` 与生命周期根在 [`ownership-lifetimes.md`](ownership-lifetimes.md);async 里的错误传播 / `try_join` 失败聚合见 [`error-handling.md`](error-handling.md)
- 深度/配方/用例:[`deep/_index.md`](deep/_index.md) 的并发 idioms;[`recipes/_index.md`](recipes/_index.md) 的"并发管道 / HTTP 客户端 / 限流"条目;并发测试见 `test-loom-concurrency` / `test-tokio-async`

## 参考

- The Book ch.16(无畏并发:线程、`Send`/`Sync`、channel、`Mutex`)、ch.17(async/await、`Future`)
- tokio 官方教程(尤其 "Shared state"、"Channels"、"Select"、"Graceful shutdown")
- `std` 文档:`std::thread`(`scope`)、`std::sync`(`Mutex`/`RwLock`/`Arc`/`atomic`)、`Send`/`Sync` marker trait
- crate docs.rs:`tokio`(`spawn`/`sync::{mpsc,oneshot,broadcast,watch,Mutex}`/`task::spawn_blocking`/`select!`/`JoinSet`)、`rayon`、`futures`、`tokio-util`(`CancellationToken`)、`async-trait`
