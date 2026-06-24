# 线程与 channel(std::thread + mpsc)

> 一句话:用 `thread::spawn` + `mpsc` 做生产者-消费者,用 `thread::scope` 借栈数据并 join 收结果。

## 依赖
```toml
# 全部来自标准库,无需依赖
```

## 做法
```rust
use std::sync::mpsc;
use std::thread;

fn main() {
    // —— 1. spawn + mpsc:多生产者单消费者 ——
    let (tx, rx) = mpsc::channel::<u32>();
    for id in 0..3 {
        let tx = tx.clone(); // 每个生产者一份 Sender
        thread::spawn(move || {
            tx.send(id * 10).unwrap();
        }); // tx 在线程结束时 drop
    }
    drop(tx); // 丢掉原始 tx,否则 rx 永远等不到所有 Sender 关闭
    // 所有 Sender drop 后 for 循环自然结束
    let mut got: Vec<u32> = rx.iter().collect();
    got.sort();
    println!("{got:?}"); // [0, 10, 20]

    // —— 2. scoped threads:借栈上数据,无需 'static / Arc ——
    let data = vec![1, 2, 3, 4];
    let total: i32 = thread::scope(|s| {
        let h1 = s.spawn(|| data[..2].iter().sum::<i32>()); // 直接借 data,不用 move
        let h2 = s.spawn(|| data[2..].iter().sum::<i32>());
        h1.join().unwrap() + h2.join().unwrap() // 作用域结束前必 join
    });
    println!("total = {total}"); // 10
}
```

## 要点 / 坑
- `mpsc::channel` 是无界的;要背压用 `mpsc::sync_channel(cap)`(满了 `send` 阻塞)。
- **消费端循环不退出的头号原因**:还有 `Sender` 活着。`rx.iter()` 在所有 `Sender` drop 后才结束——记得 `drop(tx)` 原始句柄。
- `thread::scope`(Rust 1.63+)让闭包能借父作用域的栈数据(无需 `'static`/`Arc`),作用域退出前保证所有子线程已 join。
- `join()` 返回 `Result`:线程 panic 会是 `Err`,`unwrap()` 把 panic 传播回来。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)
- 规则:[`conc-scoped-threads`](../rules/conc-scoped-threads.md)
