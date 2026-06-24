# 结构体与枚举

> struct 把相关字段聚成一个类型;enum 表达"几选一"的状态、变体可带数据;`impl` 给它们挂方法与关联函数。

```rust
// 具名字段 struct
struct Point {
    x: i32,
    y: i32,
}

// tuple struct(无字段名)
struct Meters(f64);

// unit struct(无数据,常用作标记)
struct Marker;

// enum 变体可带不同形状的数据
enum Shape {
    Circle { radius: f64 },
    Rect(f64, f64),
    Dot, // 无数据变体
}

impl Shape {
    // 关联函数(无 self),常作构造器,用 Shape::unit_circle() 调用
    fn unit_circle() -> Self {
        Shape::Circle { radius: 1.0 }
    }

    // 方法(借 &self)
    fn area(&self) -> f64 {
        match self {
            Shape::Circle { radius } => std::f64::consts::PI * radius * radius,
            Shape::Rect(w, h) => w * h,
            Shape::Dot => 0.0,
        }
    }
}

fn main() {
    let p = Point { x: 1, y: 2 };
    let d = Meters(3.5);
    let _m = Marker;
    println!("point=({}, {}) meters={}", p.x, p.y, d.0);

    let shapes = [Shape::unit_circle(), Shape::Rect(2.0, 3.0), Shape::Dot];
    for s in &shapes {
        println!("area={:.4}", s.area());
    }
}
```

输出:
```
point=(1, 2) meters=3.5
area=3.1416
area=6.0000
area=0.0000
```

## 要点
- 三种 struct:具名字段 / tuple struct(`.0` 访问)/ unit struct(零大小,做标记)。
- enum 是 sum type:每个变体可带不同数据,`match` 时被穷尽地解构。
- `impl` 块里:有 `self`/`&self`/`&mut self` 的是方法,无的是关联函数(用 `Type::fn()` 调)。
- 构造器惯例用关联函数 + `Self` 返回,而非裸字段构造(便于加不变量校验)。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`pat-exhaustive-enum`](../rules/pat-exhaustive-enum.md)、[`type-option-nullable`](../rules/type-option-nullable.md)
