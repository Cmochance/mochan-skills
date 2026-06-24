# WebSocket 客户端(tokio-tungstenite)

> 一句话:用 `tokio-tungstenite` 连接 WS、收发文本消息、用 Ping 做心跳。

## 依赖
```toml
# 版本以 docs.rs 最新为准
tokio-tungstenite = { version = "0.24", features = ["rustls-tls-webpki-roots"] }
tokio = { version = "1", features = ["full"] }
futures-util = "0.3"   # Sink/Stream 的 .send()/.next()
```

## 做法
```rust
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use std::time::Duration;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // 握手:wss:// 走 TLS,ws:// 明文
    let (ws, _resp) = connect_async("wss://echo.websocket.org").await?;
    // split 成读写两半,各自独立用(读循环 + 写/心跳并发)
    let (mut write, mut read) = ws.split();

    write.send(Message::Text("hello".into())).await?;

    // 心跳:每 30s 发一个 Ping;对端回 Pong,tungstenite 自动回应收到的 Ping
    let mut ticker = tokio::time::interval(Duration::from_secs(30));

    loop {
        tokio::select! {
            // 收消息
            msg = read.next() => match msg {
                Some(Ok(Message::Text(t)))  => println!("recv: {t}"),
                Some(Ok(Message::Binary(b))) => println!("recv {} bytes", b.len()),
                Some(Ok(Message::Close(_))) | None => break, // 对端关闭或流结束
                Some(Ok(_)) => {}                 // Ping/Pong 等,库已自动处理
                Some(Err(e)) => return Err(e.into()),
            },
            // 心跳
            _ = ticker.tick() => {
                write.send(Message::Ping(Vec::new().into())).await?;
            }
        }
    }
    Ok(())
}
```

## 要点 / 坑
- `connect_async` 返回 `(WebSocketStream, Response)`;`.split()` 后读半实现 `Stream`、写半实现 `Sink`,要 `use futures_util::{StreamExt, SinkExt}` 才有 `.next()`/`.send()`。
- 收到 `Message::Ping` 库会自动回 `Pong`,你只需主动发 Ping 探活;`read.next()` 返回 `None` 即流结束。
- `select!` 分支要 cancel-safe:`read.next()` 和 `interval.tick()` 都安全(被丢弃不丢状态),但别在分支里塞"读一半才提交"的非原子操作。
- 版本/feature 名(如 TLS backend)易变,**以 docs.rs 当前 `tokio-tungstenite` 为准**。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)
- 规则:[`async-select-racing`](../rules/async-select-racing.md)、[`async-cancel-safety`](../rules/async-cancel-safety.md)
