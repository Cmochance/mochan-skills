# 运算符重载

> 运算符由 trait 驱动:`Add`/`Mul` 给 `+`/`*`、`Index` 给 `[]`、`PartialEq`/`PartialOrd` 给 `==`/`<`、`Display` 给 `{}`。实现对应 trait 即可让自定义类型用上这些语法。

```rust
use std::fmt;
use std::ops::{Add, Index, Mul};

#[derive(Clone, Copy, PartialEq, PartialOrd)] // == 和 < 由 derive 生成
struct Vec2 {
    x: f64,
    y: f64,
}

impl Add for Vec2 {
    type Output = Vec2;
    fn add(self, rhs: Vec2) -> Vec2 {
        Vec2 { x: self.x + rhs.x, y: self.y + rhs.y }
    }
}

impl Mul<f64> for Vec2 {
    // 标量乘:rhs 类型是 f64
    type Output = Vec2;
    fn mul(self, k: f64) -> Vec2 {
        Vec2 { x: self.x * k, y: self.y * k }
    }
}

impl Index<usize> for Vec2 {
    type Output = f64;
    fn index(&self, i: usize) -> &f64 {
        match i {
            0 => &self.x,
            1 => &self.y,
            _ => panic!("Vec2 index out of range"),
        }
    }
}

impl fmt::Display for Vec2 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "({}, {})", self.x, self.y)
    }
}

fn main() {
    let a = Vec2 { x: 1.0, y: 2.0 };
    let b = Vec2 { x: 3.0, y: 4.0 };
    println!("a+b = {}", a + b); // Add -> Display
    println!("a*2 = {}", a * 2.0); // Mul<f64>
    println!("a[0]={} a[1]={}", a[0], a[1]); // Index
    println!("a==a: {}, a<b: {}", a == a, a.x < b.x); // PartialEq/PartialOrd
}
```

输出:
```
a+b = (4, 6)
a*2 = (2, 4)
a[0]=1 a[1]=2
a==a: true, a<b: true
```

## 要点
- `PartialEq`/`PartialOrd`/`Clone`/`Copy` 多数可 `#[derive]`;有特殊语义才手写。
- `Add` 默认 `Rhs = Self`;异类型运算(`Vec2 * f64`)写 `Mul<f64>` 指定右操作数类型。
- `Index` 返回 `&Self::Output`(引用),越界惯例 panic;无 panic 版本另开 `get` 返 `Option`。
- 重载要符合直觉:别让 `+` 干奇怪的事,否则违背最小惊讶原则。

## 关联
- 概览:[`../api-design.md`](../api-design.md)
- 规则:[`api-operator-overload`](../rules/api-operator-overload.md)、[`type-display-vs-debug`](../rules/type-display-vs-debug.md)
