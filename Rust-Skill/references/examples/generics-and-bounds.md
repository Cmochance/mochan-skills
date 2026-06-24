# 泛型与 trait bound

> 泛型让一份代码服务多种类型;trait bound(`T: Trait`)约束"这些类型得能做什么";编译期单态化为每个具体类型生成专用代码。

```rust
use std::fmt::Display;
use std::ops::Add;

// 泛型函数 + bound:T 必须能比较(PartialOrd)且能复制(Copy)
fn max<T: PartialOrd + Copy>(items: &[T]) -> Option<T> {
    let mut it = items.iter();
    let mut best = *it.next()?;
    for &x in it {
        if x > best {
            best = x;
        }
    }
    Some(best)
}

// where 子句:bound 多时更清晰
fn sum_and_show<T>(items: &[T]) -> String
where
    T: Add<Output = T> + Copy + Display + Default,
{
    let mut acc = T::default();
    for &x in items {
        acc = acc + x;
    }
    format!("sum = {acc}")
}

// 泛型 struct
struct Pair<T> {
    a: T,
    b: T,
}

impl<T: Display> Pair<T> {
    fn show(&self) -> String {
        format!("({}, {})", self.a, self.b)
    }
}

fn main() {
    println!("{:?}", max(&[3, 7, 2])); // Some(7)
    println!("{:?}", max::<i32>(&[])); // None
    println!("{}", sum_and_show(&[1.5, 2.5, 1.0]));
    println!("{}", Pair { a: "x", b: "y" }.show());
}
```

输出:
```
Some(7)
None
sum = 5
(x, y)
```

## 要点
- bound 写在哪都行:`<T: Trait>`、`where T: Trait`(多约束时 `where` 更易读)。
- 单态化:`max::<i32>` 和 `max::<f64>` 编译成两份独立机器码——零运行期开销,但代码膨胀。
- bound 是"能力清单":用到 `+`(`Add`)、`>`(`PartialOrd`)、`{}`(`Display`)就要在 bound 里声明。
- 关联类型约束:`Add<Output = T>` 把"加法结果还是 T"也写进约束。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`type-generic-bounds`](../rules/type-generic-bounds.md)、[`trait-dyn-vs-generic`](../rules/trait-dyn-vs-generic.md)
