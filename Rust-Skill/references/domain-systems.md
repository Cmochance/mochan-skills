# 系统 / 网络编程(socket / 异步 IO / 进程 / 零拷贝)

底层网络与系统编程:TCP/UDP socket、同步 vs 异步 IO、进程/信号、零拷贝、事件循环、syscall。

适用:写 socket 服务/客户端、选同步还是 tokio 异步、自定义协议帧编解码、零拷贝缓冲、信号/进程/管道管理、用 mio/io_uring 等底层、调用 libc syscall。

---

## 同步 vs 异步(先定基调)

| | 同步(`std`) | 异步(tokio) |
|---|---|---|
| 网络 | `std::net::{TcpStream,TcpListener,UdpSocket}` | `tokio::net::{TcpStream,TcpListener,UdpSocket}` |
| 文件 | `std::fs` | `tokio::fs`(见坑) |
| 进程 | `std::process::Command` | `tokio::process::Command` |
| 并发模型 | 一连接一线程(thread-per-conn) | 一连接一 task,少量 worker 线程多路复用 |

**选型**:连接数少(几十几百)、逻辑简单、或纯 CPU 工具 → 同步 + 线程更直白好调。**高并发 IO**(成千上万连接、大量等待)→ tokio 异步,task 比线程轻得多。别为「显得现代」给一个跑批小工具套 async runtime。tokio 细节见 [`concurrency-async.md`](concurrency-async.md)。

## 异步 IO 抽象:AsyncRead/AsyncWrite/Framed

- tokio 的 `AsyncReadExt`/`AsyncWriteExt` 给 stream 加 `read`/`write_all`/`read_to_end` 等异步方法。
- **协议分帧别手搓**:用 `tokio_util::codec` 的 `Framed` + 实现 `Decoder`/`Encoder`,把字节流切成消息帧(处理粘包/半包)。现成 codec:`LinesCodec`(按行)、`LengthDelimitedCodec`(长度前缀)。自定义协议实现 `Decoder::decode`(从 `BytesMut` 攒够一帧就吐一个消息),框架处理缓冲与背压。
- 这套把「读字节 → 拼帧 → 反序列化」分层,比裸 `read` + 手动状态机健壮太多。

## 零拷贝与缓冲

- **`bytes::Bytes` / `BytesMut`**:引用计数的字节缓冲,`split`/`clone` 不复制底层数据(只调引用计数 + 偏移)。在网络栈里传 buffer 默认用它,避免 `Vec<u8>` 到处 clone。见 [`rules/mem-zero-copy.md`](rules/mem-zero-copy.md)。
- **`std::io::copy` / `tokio::io::copy`**:流到流搬运,内部用复用缓冲。
- **`sendfile`**(经 `nix`/`libc` 或 tokio 的相关封装):文件→socket 直接内核态搬,不经用户态,大文件服务用。
- 解析时零拷贝:借用输入切片而非 owned,见所有权域 [`rules/mem-zero-copy.md`](rules/mem-zero-copy.md) 与 `serde` 的借用反序列化(见 [`serde-data.md`](serde-data.md))。

## 底层:mio / io_uring / socket2

- **`mio`**:tokio 底下的跨平台事件循环(epoll/kqueue/IOCP 抽象)。**一般不直接用**——除非你在造自己的 runtime 或需要 tokio 不给的底层控制。
- **`io_uring`**(Linux):新一代异步 IO 接口,真异步文件 IO + 更少 syscall。`tokio-uring` 或 `io-uring` crate;尚非 tokio 默认,按需且仅 Linux。
- **`socket2`**:`std`/`tokio` 没暴露的 socket 选项(`SO_REUSEADDR`/`TCP_NODELAY`/keepalive/绑定特定接口/raw socket)。先用 `socket2::Socket` 配好选项,再转成 std/tokio 的类型。
- 直接 syscall:`nix`(安全包装,优先)或 `libc`(裸 FFI,unsafe),见 [`unsafe-ffi.md`](unsafe-ffi.md)。

## 信号与进程

- **信号**:异步用 `tokio::signal`(`ctrl_c()` / Unix `signal(SignalKind::terminate())`)做优雅停机;同步/更全用 `signal-hook`。**别在信号处理器里做复杂事**(async-signal-safety),改成「信号 → 设标志/发 channel → 主循环处理」。
- **进程**:`Command` spawn 子进程,接管 stdin/stdout/stderr 做管道(`Stdio::piped()`);异步版 `tokio::process` 可 `.await` 子进程退出、并发读其输出。注意收割僵尸进程(`.wait()`/`.await`)。

## 背压

生产快于消费会爆内存。用**有界**通道/缓冲(`tokio::sync::mpsc::channel(N)` 而非 `unbounded`,见 [`rules/async-bounded-channel.md`](rules/async-bounded-channel.md)),`Framed` 的 sink 满了自然产生背压。网络层别无脑全收进内存,跟着下游处理速度走。

## 典型坑

- **阻塞调用堵 async runtime**:在 tokio task 里调同步 `std::net`/`std::fs`/CPU 密集/`std::thread::sleep`,**卡死整个 worker 线程**(其它 task 饿死)。用 `tokio::task::spawn_blocking` 或对应 async API(见 [`rules/async-spawn-blocking.md`](rules/async-spawn-blocking.md))。
- **`tokio::fs` 不是真异步**:OS 没有可移植的异步文件 IO,`tokio::fs` 实际是 `spawn_blocking` 包同步调用(线程池)。大量小文件 IO 时它不比同步快,心里有数;真异步文件 IO 看 io_uring。
- **粘包/半包**:裸 `read` 一次不保证读到完整消息(TCP 是流不是包)。用 `Framed` + `Decoder` 处理,别假设一次 read = 一条消息。
- **无界通道吃内存**:`unbounded_channel` 在生产快时无限堆积。默认有界 + 背压。
- **信号处理器里干重活**:违反 async-signal-safety,死锁/未定义。处理器只设标志。
- **忘了 `TCP_NODELAY`**:Nagle 算法让小包延迟攒批,低延迟场景要用 `socket2`/`set_nodelay` 关掉。
- **僵尸子进程**:spawn 后不 `wait`,进程表泄漏。

## 关联知识库

- 概览:[`concurrency-async.md`](concurrency-async.md)(tokio runtime/task/channel/`spawn_blocking`/锁)、[`unsafe-ffi.md`](unsafe-ffi.md)(libc/nix syscall、裸指针、`sendfile`)、[`performance.md`](performance.md)(缓冲/零拷贝/IO 批量)
- 规则:`rules/_index.md` 的 `async-*`(尤其 [`rules/async-spawn-blocking.md`](rules/async-spawn-blocking.md)、[`rules/async-bounded-channel.md`](rules/async-bounded-channel.md)、[`rules/async-tokio-fs.md`](rules/async-tokio-fs.md))、`conc-*`、零拷贝 [`rules/mem-zero-copy.md`](rules/mem-zero-copy.md)、IO 缓冲 [`rules/perf-io-buffering.md`](rules/perf-io-buffering.md)

## 参考

- tokio 文档与教程(`net`/`io`/`process`/`signal` 模块;tokio Tutorial 的 framing 章)
- `tokio-util`(codec/`Framed`)、`bytes`、`socket2`、`mio` 文档(docs.rs)
- `nix` / `libc`(syscall)、`signal-hook` 文档;`io-uring`/`tokio-uring`(仅 Linux)
- 标准库 `std::net` / `std::io` / `std::process` 文档;版本/签名以 docs.rs 当前为准,不确定查 docs.rs
