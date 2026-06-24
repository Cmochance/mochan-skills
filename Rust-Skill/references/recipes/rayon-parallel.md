# 数据并行(rayon)

> 一句话:用 `rayon` 把 `iter()` 换成 `par_iter()` 做并行 map/reduce、`par_sort`,以及何时值得并行。

## 依赖
```toml
# 版本以 docs.rs 最新为准
rayon = "1"
```

## 做法
```rust
use rayon::prelude::*; // 引入 par_iter / par_sort 等扩展方法

fn main() {
    let v: Vec<u64> = (0..1_000_000).collect();

    // 并行 map-reduce:work-stealing 线程池自动分块
    let sum_of_squares: u64 = v
        .par_iter()
        .map(|&x| x * x)
        .sum(); // reduce 阶段也并行

    // 并行 filter + collect(结果顺序与输入一致)
    let evens: Vec<u64> = v.par_iter().copied().filter(|x| x % 2 == 0).collect();

    // 并行排序(原地)
    let mut data = vec![5u32, 2, 9, 1, 7, 3];
    data.par_sort_unstable(); // 不稳定排序更快;要稳定用 par_sort

    println!("{sum_of_squares} {} {:?}", evens.len(), data);
}
```

自定义 reduce(需提供单位元 + 结合的合并函数):
```rust
use rayon::prelude::*;
let max = (0..1000).into_par_iter().reduce(|| i32::MIN, |a, b| a.max(b));
```

## 要点 / 坑
- **何时值得**:数据量大(通常上万元素起)+ 每元素计算非平凡 + 操作无副作用/可独立。小数组或廉价操作,并行的调度开销 > 收益,串行更快——先测再并行。
- rayon 是 **CPU 密集**工具,基于线程池;**别在 async 任务里跑串行重 CPU 循环**饿死 runtime,改用 rayon 或 `spawn_blocking`。
- `reduce` 的合并函数必须满足结合律(顺序不定);`par_iter().sum()` 等内置 reduce 已保证正确。
- 闭包捕获的共享可变状态会触发借用/`Sync` 报错——并行体内别写共享 `&mut`,改成返回值再 reduce。

## 关联
- 概览:[`../concurrency-async.md`](../concurrency-async.md)、[`../performance.md`](../performance.md)
- 规则:[`conc-rayon-par-iter`](../rules/conc-rayon-par-iter.md)、[`async-spawn-blocking`](../rules/async-spawn-blocking.md)
