# 标准库集合

> `Vec`(增长序列)、`HashMap`(无序键值)、`HashSet`(去重)、`BTreeMap`(有序键值)覆盖绝大多数需求;`entry` API 是"按键更新"的惯用法。

```rust
use std::collections::{BTreeMap, HashMap, HashSet};

fn main() {
    // Vec:push / 迭代 / 收集
    let mut v = vec![3, 1, 2];
    v.push(4);
    v.sort();
    println!("vec={v:?}");

    // HashMap + entry:不存在则插默认,再就地改
    let text = "a b a c b a";
    let mut freq: HashMap<&str, u32> = HashMap::new();
    for w in text.split_whitespace() {
        *freq.entry(w).or_insert(0) += 1;
    }
    println!("a={} b={} c={}", freq["a"], freq["b"], freq["c"]);

    // HashSet:去重与成员测试
    let mut seen = HashSet::new();
    let nums = [1, 2, 2, 3, 3, 3];
    let unique: Vec<_> = nums.iter().filter(|&&n| seen.insert(n)).collect();
    println!("unique={unique:?}");

    // BTreeMap:按 key 有序迭代
    let mut scores = BTreeMap::new();
    scores.insert("carol", 90);
    scores.insert("alice", 85);
    scores.insert("bob", 88);
    for (name, s) in &scores {
        println!("{name}: {s}");
    }
}
```

输出:
```
vec=[1, 2, 3, 4]
a=3 b=2 c=1
unique=[1, 2, 3]
alice: 85
bob: 88
carol: 90
```

(注:BTreeMap 按 key 字典序遍历,故 alice/bob/carol 而非插入序。)

## 要点
- 选型:无序快查 `HashMap`/`HashSet`;要有序遍历或范围查询 `BTreeMap`/`BTreeSet`;序列默认 `Vec`。
- `entry(k).or_insert(default)` 返回 `&mut V`,可原地 `+=`——比"先 get 再 insert"少一次查找。
- `HashSet::insert` 返回 `bool`(是否新插入),正好用作"首次出现"过滤。
- `HashMap` 迭代顺序不确定;依赖顺序的逻辑别用它,换 `BTreeMap` 或显式排序。

## 关联
- 概览:[`../performance.md`](../performance.md)
- 规则:[`coll-map-choice`](../rules/coll-map-choice.md)、[`coll-seq-choice`](../rules/coll-seq-choice.md)、[`coll-set-membership`](../rules/coll-set-membership.md)、[`perf-entry-api`](../rules/perf-entry-api.md)
