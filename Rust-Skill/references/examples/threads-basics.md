# 线程基础

> `thread::spawn` 起 OS 线程、`join` 等它结束;`thread::scope` 允许借用栈数据的作用域线程;跨线程共享可变状态用 `Arc<Mutex<T>>`。

```rust
use std::sync::{Arc, Mutex};
use std::thread;

fn main() {
    // spawn + join:move 闭包按值捕获,返回值经 join 取回
    let handles: Vec<_> = (0..3)
        .map(|i| thread::spawn(move || i * i))
        .collect();
    let squares: Vec<i32> = handles.into_iter().map(|h| h.join().unwrap()).collect();
    println!("squares={squares:?}");

    // Arc<Mutex>:多线程共享 + 互斥可变,做并发计数
    let counter = Arc::new(Mutex::new(0));
    let mut workers = Vec::new();
    for _ in 0..4 {
        let c = Arc::clone(&counter);
        workers.push(thread::spawn(move || {
            let mut guard = c.lock().unwrap();
            *guard += 1; // guard 离开作用域自动解锁
        }));
    }
    for w in workers {
        w.join().unwrap();
    }
    println!("counter={}", *counter.lock().unwrap());

    // scope:作用域线程可借用栈上数据,无需 'static
    let data = vec![1, 2, 3, 4];
    let sum = thread::scope(|s| {
        let h = s.spawn(|| data.iter().sum::<i32>()); // 借 data,不需 move 进 Arc
        h.join().unwrap()
    });
    println!("scoped sum={sum}");
}
```

输出:
```
squares=[0, 1, 4]
counter=4
scoped sum=10
```

## 要点
- `spawn` 的闭包需 `'static`:捕获栈数据要么 `move` + clone/`Arc`,要么改用 `thread::scope`。
- `Arc` 共享所有权(跨线程引用计数),`Mutex` 提供互斥;二者常组合 `Arc<Mutex<T>>`。
- `lock()` 返回 guard,**离开作用域自动解锁**;别长期持锁,缩短临界区。
- `thread::scope`(1.63+)保证子线程在作用域结束前 join,因此能安全借用父栈数据。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)
- 规则:[`own-mutex-interior`](../rules/own-mutex-interior.md)、[`own-arc-shared`](../rules/own-arc-shared.md)、[`conc-scoped-threads`](../rules/conc-scoped-threads.md)
