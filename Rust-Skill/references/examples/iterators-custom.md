# 自定义迭代器

> 实现 `Iterator`(给关联类型 `Item` + 一个 `next`)即可白嫖全部适配器;实现 `IntoIterator` 让类型能用于 `for`。

```rust
// 斐波那契:实现 Iterator 即可链 map/take/filter 等
struct Fib {
    a: u64,
    b: u64,
}

impl Iterator for Fib {
    type Item = u64; // 关联类型:每次产出什么

    fn next(&mut self) -> Option<Self::Item> {
        let cur = self.a;
        self.a = self.b;
        self.b = cur + self.b;
        Some(cur) // 无限迭代器,永不返回 None
    }
}

// 自定义集合实现 IntoIterator,支持 for 循环
struct Bag {
    items: Vec<i32>,
}

impl IntoIterator for Bag {
    type Item = i32;
    type IntoIter = std::vec::IntoIter<i32>;

    fn into_iter(self) -> Self::IntoIter {
        self.items.into_iter() // 委托给 Vec 的迭代器
    }
}

fn main() {
    let fib = Fib { a: 0, b: 1 };
    // 适配器链:对自定义迭代器同样可用
    let first: Vec<u64> = fib.take(8).filter(|n| n % 2 == 0).collect();
    println!("even fibs={first:?}");

    let bag = Bag { items: vec![1, 2, 3] };
    let mut total = 0;
    for x in bag {
        // for 触发 into_iter()
        total += x;
    }
    println!("bag total={total}");
}
```

输出:
```
even fibs=[0, 2, 8]
bag total=6
```

## 要点
- 只需写 `type Item` + `next`,`map`/`filter`/`take`/`fold`/`collect` 等几十个方法全部自动可用。
- `next` 返回 `None` 表示结束;不返回 `None` 就是无限迭代器,靠 `take(n)` 等截断。
- `IntoIterator` 三种实现对应 `for x in c`(消费)、`&c`(借)、`&mut c`(可变借)——按需各实现。
- 适配器自身惰性:`take(8)` 不会驱动无限 `Fib` 跑飞,只拉 8 个就停。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`name-iter-method`](../rules/name-iter-method.md)、[`trait-associated-type-vs-generic`](../rules/trait-associated-type-vs-generic.md)
