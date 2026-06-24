# Trait 基础

> trait 是共享行为的契约;可给默认方法,为任意类型实现;`impl Trait` 让函数接受"任何满足契约的类型"。

```rust
trait Greet {
    fn name(&self) -> String;

    // 默认方法:实现者可不重写,直接复用
    fn hello(&self) -> String {
        format!("Hello, {}!", self.name())
    }
}

struct Dog;
struct Robot {
    id: u32,
}

impl Greet for Dog {
    fn name(&self) -> String {
        "Dog".to_string()
    }
    // 不写 hello,用默认实现
}

impl Greet for Robot {
    fn name(&self) -> String {
        format!("Robot#{}", self.id)
    }
    fn hello(&self) -> String {
        format!("BEEP {}", self.name()) // 重写默认
    }
}

// impl Trait 作参数:静态分发,接受任何 Greet
fn announce(g: &impl Greet) {
    println!("{}", g.hello());
}

fn main() {
    announce(&Dog);
    announce(&Robot { id: 7 });
}
```

输出:
```
Hello, Dog!
BEEP Robot#7
```

## 要点
- 默认方法减少样板:实现者只填必需的方法,共性逻辑写在 trait 里。
- 孤儿规则:`impl Trait for Type` 需 trait 或 type 至少一个属于本 crate(否则用 newtype 包一层)。
- `&impl Greet` 参数 = 单态化静态分发(零成本);要在同一容器存不同类型用 `dyn`(见 trait-objects)。
- 方法解析靠类型,不靠继承;Rust 无类继承,组合 + trait 取而代之。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`trait-default-methods`](../rules/trait-default-methods.md)、[`trait-dyn-vs-generic`](../rules/trait-dyn-vs-generic.md)
