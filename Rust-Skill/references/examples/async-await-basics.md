# async / await 基础

> `async fn` 返回一个惰性 `Future`,`.await` 在等待点让出执行权;需要运行时(runtime)来驱动,最常用 `#[tokio::main]`。`join!` 并发跑多个 future。

需依赖 tokio:`Cargo.toml` 加 `tokio = { version = "1", features = ["full"] }`。

```rust
use std::time::Duration;

// async fn 体内可 .await;调用它只得到 Future,不会立即执行
async fn fetch(name: &str, ms: u64) -> String {
    tokio::time::sleep(Duration::from_millis(ms)).await; // 等待点:让出而非阻塞线程
    format!("{name} done")
}

#[tokio::main] // 宏展开成建立 runtime + block_on(main 体)
async fn main() {
    // 串行:总耗时 ≈ 30+20 ms
    let a = fetch("A", 30).await;
    let b = fetch("B", 20).await;
    println!("{a} / {b}");

    // 并发:join! 同时推进两个 future,总耗时 ≈ max(30,20)
    let (c, d) = tokio::join!(fetch("C", 30), fetch("D", 20));
    println!("{c} / {d}");
}
```

输出:
```
A done / B done
C done / D done
```

## 要点
- `async fn` 调用**不执行**,只生成 future;必须 `.await` 或交给 runtime 才推进——忘了 await 是常见 bug。
- `.await` 让出而非阻塞:等待期间 runtime 能跑别的任务;别在 async 里调阻塞 IO/`std::thread::sleep`。
- 串行 `.await` 链是顺序等待;要并发用 `join!`(都成功)、`try_join!`(任一 Err 即返)、`select!`(竞速)。
- runtime 不是语言内置:必须自己引入(tokio / async-std),`#[tokio::main]` 是最省事的入口。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)
- 规则:[`async-join-parallel`](../rules/async-join-parallel.md)、[`async-tokio-runtime`](../rules/async-tokio-runtime.md)
