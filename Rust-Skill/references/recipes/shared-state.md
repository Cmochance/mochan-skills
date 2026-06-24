# 跨任务/线程共享状态(Arc<Mutex> / Arc<RwLock>)

> 一句话:用 `Arc<Mutex<T>>` / `Arc<RwLock<T>>` 在多任务间共享可变状态,注意锁粒度与"别持锁过 await"。

## 依赖
```toml
# Arc/Mutex/RwLock 全部来自标准库
tokio = { version = "1", features = ["full"] }  # 仅示例 spawn 用
```

## 做法
```rust
use std::sync::{Arc, Mutex, RwLock};
use std::collections::HashMap;

#[tokio::main]
async fn main() {
    // —— Mutex:读写都互斥,适合写多或临界区短 ——
    let counter = Arc::new(Mutex::new(0u64));
    let mut handles = Vec::new();
    for _ in 0..4 {
        let counter = Arc::clone(&counter); // 复制 Arc 指针,不是数据
        handles.push(tokio::spawn(async move {
            // 临界区纯同步、不含 .await:用 std Mutex 即可
            let mut g = counter.lock().unwrap();
            *g += 1;
        }));
    }
    for h in handles { h.await.unwrap(); }
    println!("count = {}", *counter.lock().unwrap());

    // —— RwLock:读多写少,多个读者可并发持有 ——
    let cache: Arc<RwLock<HashMap<String, u64>>> = Arc::new(RwLock::new(HashMap::new()));
    {
        let mut w = cache.write().unwrap(); // 写锁独占
        w.insert("hits".into(), 1);
    } // 写锁在块末释放
    let snapshot = {
        let r = cache.read().unwrap();      // 读锁,可并发
        r.get("hits").copied()              // 取出值,锁随块结束释放
    };
    println!("{snapshot:?}"); // Some(1)
}
```

## 要点 / 坑
- **共享 = `Arc::clone`**(复制引用计数指针),不是 clone 内部数据;搬进 `spawn`/线程满足 `'static`。
- **锁粒度**:临界区越短越好。取出需要的值后让 guard 出作用域,别在持锁期间做 IO/计算/`.await`。
- 头号铁律:**`std::sync` 的 guard 不可跨 `.await`**(`!Send` + 易死锁)。临界区内必须 await 才用 `tokio::sync::Mutex`,否则默认 std Mutex + extract→release。
- `RwLock` 仅在**读远多于写**时才赢 Mutex;写频繁时退化甚至更慢。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)、[`../ownership-lifetimes.md`](../ownership-lifetimes.md)
- 规则:[`own-arc-shared`](../rules/own-arc-shared.md)、[`own-mutex-interior`](../rules/own-mutex-interior.md)、[`own-rwlock-readers`](../rules/own-rwlock-readers.md)、[`anti-lock-across-await`](../rules/anti-lock-across-await.md)
