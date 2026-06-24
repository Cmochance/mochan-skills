# 闭包与迭代器

> 闭包是能捕获环境的匿名函数,按需实现 `Fn`/`FnMut`/`FnOnce`;迭代器适配器(`map`/`filter`/`fold`)惰性组合,`collect`/`sum` 等消费者才真正驱动。

```rust
fn apply<F: Fn(i32) -> i32>(x: i32, f: F) -> i32 {
    f(x)
}

fn main() {
    let factor = 3;
    let scale = |n| n * factor; // 借用捕获 factor(Fn)
    println!("apply={}", apply(10, scale));

    let mut count = 0;
    let mut tick = || count += 1; // FnMut:可变捕获 count
    tick();
    tick();
    println!("count={count}");

    // 惰性链:这一行不做任何计算,只搭好管道
    let pipeline = (1..=10).map(|x| x * x).filter(|x| x % 2 == 0);
    // collect 才真正拉动迭代器
    let evens_sq: Vec<i32> = pipeline.collect();
    println!("{evens_sq:?}");

    // fold:从初值累积
    let sum = (1..=5).fold(0, |acc, x| acc + x);
    println!("sum={sum}");

    // 常见组合:filter_map + sum
    let total: i32 = ["1", "x", "3"].iter().filter_map(|s| s.parse::<i32>().ok()).sum();
    println!("total={total}");
}
```

输出:
```
apply=30
count=2
[4, 16, 36, 64, 100]
sum=15
total=4
```

## 要点
- 捕获方式由用法推断:只读 → `Fn`;改捕获变量 → `FnMut`;把捕获值移走/消费 → `FnOnce`。
- 迭代器惰性:`map`/`filter` 只构造适配器,直到 `collect`/`sum`/`for`/`count` 等消费者才求值。
- 优先迭代器链而非手写索引循环:更难越界、更易并行化、意图更清晰。
- `collect` 的目标类型常需标注(`Vec<_>`/`String`/`HashMap<_,_>`),靠它选具体集合。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`closure-fn-trait-bounds`](../rules/closure-fn-trait-bounds.md)、[`perf-iter-lazy`](../rules/perf-iter-lazy.md)、[`perf-iter-over-index`](../rules/perf-iter-over-index.md)
