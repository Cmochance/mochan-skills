# 异步任务编排(tokio::spawn / JoinSet / timeout / select)

> 一句话:用 `tokio::spawn`/`JoinSet` 并发跑任务、`timeout` 加期限、`interval` 周期触发、`select!` 竞速。

## 依赖
```toml
# 版本以 docs.rs 最新为准
tokio = { version = "1", features = ["full"] }
```

## 做法
```rust
use std::time::Duration;
use tokio::task::JoinSet;
use tokio::time::{interval, sleep, timeout};

async fn fetch(id: u32) -> u32 { sleep(Duration::from_millis(50)).await; id * 2 }

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // 1. JoinSet:动态一批任务,并发跑、逐个收结果(结构化并发)
    let mut set = JoinSet::new();
    for id in 0..5 { set.spawn(fetch(id)); }
    let mut results = Vec::new();
    while let Some(res) = set.join_next().await {
        results.push(res?); // res 是 Result<u32, JoinError>:任务 panic 会是 Err
    }
    println!("{results:?}");

    // 2. timeout:给 future 加期限,超时返回 Err
    match timeout(Duration::from_millis(10), fetch(99)).await {
        Ok(v)  => println!("got {v}"),
        Err(_) => println!("timed out"),
    }

    // 3. interval:周期触发(首 tick 立即返回)
    let mut tick = interval(Duration::from_millis(20));
    for _ in 0..3 { tick.tick().await; }

    // 4. select!:竞速,谁先好用谁,其余被丢弃(取消)
    tokio::select! {
        v = fetch(1) => println!("fetch won: {v}"),
        _ = sleep(Duration::from_millis(5)) => println!("timer won"),
    }
    Ok(())
}
```

## 要点 / 坑
- `tokio::spawn(fut)` 要 `fut: Send + 'static`;把 owned 值 `move` 进去,共享数据 `Arc::clone` 后搬,别借栈。
- 要并发一批又能借父作用域/逐个收结果用 **`JoinSet`**,优于一堆裸 `spawn` + 收集 `JoinHandle`。
- `select!` 落选分支的 future 被 **drop = 取消**,中途进度丢失;分支必须 cancel-safe,别塞"读一半才提交"的非原子操作。
- 全部完成(非竞速)用 `tokio::join!`(全跑完)或 `tokio::try_join!`(任一 Err 短路)。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)
- 规则:[`async-joinset-structured`](../rules/async-joinset-structured.md)、[`async-select-racing`](../rules/async-select-racing.md)
