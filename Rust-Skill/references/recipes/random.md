# 随机数

> 一句话:`rand` 生成范围随机、洗牌、抽样,需复现时用带 seed 的 `StdRng`。

## 依赖

```toml
rand = "0.8"   # 注:0.9 起 API 有调整(gen_range -> random_range 等),以 docs.rs 当前版本为准
```

## 做法

```rust
use rand::Rng;
use rand::seq::SliceRandom;          // shuffle / choose
use rand::rngs::StdRng;
use rand::SeedableRng;

fn demo() {
    // 线程局部 RNG:最省事,自动播种,够日常用
    let mut rng = rand::thread_rng();

    let dice: u32 = rng.gen_range(1..=6);          // 闭区间 [1,6]
    let prob: f64 = rng.gen();                     // [0.0, 1.0)
    let coin: bool = rng.gen_bool(0.7);            // 70% 概率 true
    println!("{dice} {prob:.3} {coin}");

    // 洗牌 / 随机抽一个 / 抽样 k 个
    let mut deck: Vec<u32> = (1..=10).collect();
    deck.shuffle(&mut rng);
    let pick = deck.choose(&mut rng).copied();     // Option(空切片得 None)
    let sample: Vec<_> = deck.choose_multiple(&mut rng, 3).collect();
    println!("{pick:?} {sample:?}");

    // 可复现:固定 seed 的 StdRng,同 seed 同序列(测试/调试必备)
    let mut seeded = StdRng::seed_from_u64(42);
    let a: u32 = seeded.gen_range(0..100);
    let mut seeded2 = StdRng::seed_from_u64(42);
    let b: u32 = seeded2.gen_range(0..100);
    assert_eq!(a, b);                              // 同 seed 必然相等
}
```

## 要点 / 坑

- `rand` 跨大版本 **API 改名**(0.9 把 `gen_range`→`random_range`、`gen`→`random` 等);照本配方前先核对你的版本 docs.rs。
- 默认 `thread_rng` 是**密码学不安全**的快速 PRNG;生成 token/密钥用 `rand` 的 `OsRng` 或专门的 crypto crate。
- 复现性靠**固定 seed** 的 `StdRng`/`SmallRng`;`thread_rng` 每次不同,测试里别用它再断言具体值。
- `choose`/`choose_multiple` 对空切片返回 `None`/空,别 `unwrap` 假设非空。
- 浮点 `gen::<f64>()` 是 `[0,1)` **左闭右开**;要 `(0,1]` 或其他区间自己变换。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 测试:[`../testing.md`](../testing.md)(可复现 seed 配合 proptest)
- 规则:[`test-proptest-properties`](../rules/test-proptest-properties.md)、[`num-float-compare`](../rules/num-float-compare.md)
