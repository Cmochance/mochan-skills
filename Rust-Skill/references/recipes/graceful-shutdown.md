# 优雅退出(ctrl_c + CancellationToken)

> 一句话:接到 Ctrl-C 后用 `CancellationToken` 通知所有任务收尾,等它们清理完再退出。

## 依赖
```toml
# 版本以 docs.rs 最新为准
tokio = { version = "1", features = ["full"] }
tokio-util = "0.7"   # CancellationToken
```

## 做法
```rust
use std::time::Duration;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

async fn worker(id: u32, token: CancellationToken) {
    let mut tick = tokio::time::interval(Duration::from_millis(100));
    loop {
        tokio::select! {
            // 协作式取消:token 被取消时这个分支立刻就绪
            _ = token.cancelled() => {
                println!("worker {id} 收到取消,清理收尾");
                // 这里做 flush / 关连接等清理
                break;
            }
            _ = tick.tick() => { /* 正常干活 */ }
        }
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let token = CancellationToken::new();
    let mut set = JoinSet::new();
    for id in 0..3 {
        set.spawn(worker(id, token.clone())); // 每任务一份 token clone,共享同一取消源
    }

    // 等 Ctrl-C(也可换成监听 SIGTERM)
    tokio::signal::ctrl_c().await?;
    println!("收到 Ctrl-C,开始优雅退出");
    token.cancel(); // 广播取消给所有持有 clone 的任务

    // 等所有任务清理完成(可再包一层 timeout 强制兜底)
    while set.join_next().await.is_some() {}
    println!("全部退出干净");
    Ok(())
}
```

## 要点 / 坑
- `CancellationToken` 是**协作式**:任务必须主动 `select!` 上 `token.cancelled()` 才会响应;不轮询它的任务不会被打断。
- `token.clone()` 共享同一取消源,`cancel()` 一次广播给所有 clone;子 token 用 `child_token()` 做分层取消。
- `ctrl_c()` 跨平台;要同时处理 SIGTERM(容器/systemd)用 `tokio::signal::unix::signal`。
- 收尾别无限等:`while join_next()` 外面套 `timeout`,超时再 `set.abort_all()` 强制结束,避免卡死无法退出。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)
- 规则:[`async-cancellation-token`](../rules/async-cancellation-token.md)、[`async-joinset-structured`](../rules/async-joinset-structured.md)
