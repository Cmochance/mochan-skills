# TCP 客户端 / 服务端(tokio + std 对比)

> 一句话:用 `tokio` 写 accept 循环 + 读写的 echo 服务,并对比 `std::net` 的同步阻塞版。

## 依赖
```toml
# 版本以 docs.rs 最新为准
tokio = { version = "1", features = ["full"] }
# std 版无需依赖
```

## 做法
```rust
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

// async echo 服务:每个连接 spawn 一个任务,单线程驾驭海量并发连接
#[tokio::main]
async fn main() -> std::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:7878").await?;
    loop {
        let (mut socket, peer) = listener.accept().await?;
        // 每连接一个独立任务;socket 是 owned,move 进去满足 'static
        tokio::spawn(async move {
            let mut buf = [0u8; 1024];
            loop {
                match socket.read(&mut buf).await {
                    Ok(0) => return,                       // 对端关闭
                    Ok(n) => {
                        if socket.write_all(&buf[..n]).await.is_err() {
                            return;                        // 写失败,断开
                        }
                    }
                    Err(_) => return,
                }
            }
            // peer 可用于日志
            let _ = peer;
        });
    }
}
```

同步阻塞版(`std::net`,每连接一个 OS 线程):
```rust
use std::io::{Read, Write};
use std::net::TcpListener;

fn main() -> std::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:7878")?;
    for stream in listener.incoming() {
        let mut stream = stream?;
        std::thread::spawn(move || {       // 线程也要 'static + Send
            let mut buf = [0u8; 1024];
            loop {
                match stream.read(&mut buf) {
                    Ok(0) | Err(_) => return,
                    Ok(n) => { let _ = stream.write_all(&buf[..n]); }
                }
            }
        });
    }
    Ok(())
}
```

## 要点 / 坑
- async 版用 `AsyncReadExt`/`AsyncWriteExt`(需 `use` 这俩 trait 才有 `.read`/`.write_all`)。
- `read` 返回 `Ok(0)` 表示 EOF/对端关闭,**不是错误**,要单独处理否则死循环。
- async 用少量 runtime 线程撑大量连接;std 版每连接一个 OS 线程,连接多会吃光线程。
- spawn 的任务/线程都要 `'static`:把 `socket`/`stream` **`move`** 进去,别借栈数据。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)、[`../domain-systems.md`](../domain-systems.md)
- 规则:[`async-tokio-runtime`](../rules/async-tokio-runtime.md)、[`conc-scoped-threads`](../rules/conc-scoped-threads.md)
