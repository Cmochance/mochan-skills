# 模块与可见性

> `mod` 划分命名空间,默认私有;`pub` 对外暴露、`pub(crate)` 限本 crate;`use` 引入路径缩短引用。

下例把多个模块写在一个文件里(可直接 `cargo run`);真实项目里每个 `mod foo` 常对应 `foo.rs` 或 `foo/mod.rs`。

```rust
mod geometry {
    // pub:对外可见
    pub struct Circle {
        pub radius: f64,
    }

    impl Circle {
        pub fn new(radius: f64) -> Self {
            Circle { radius }
        }
        pub fn area(&self) -> f64 {
            std::f64::consts::PI * self.radius * self.radius
        }
    }

    // 嵌套模块 + crate 级可见(本 crate 任意处可用,对外部 crate 不可见)
    pub(crate) mod util {
        pub(crate) fn round2(x: f64) -> f64 {
            (x * 100.0).round() / 100.0
        }
    }

    // 私有:仅本模块内可见(此处未对外用,加 _ 前缀避免 dead_code 警告)
    fn _internal_seed() -> f64 {
        1.0
    }
}

// use 缩短路径
use geometry::util::round2;
use geometry::Circle;

fn main() {
    let c = Circle::new(2.0);
    // 通过完整路径也可访问
    let exact = c.area();
    println!("area={} rounded={}", exact, round2(exact));
}
```

输出:
```
area=12.566370614359172 rounded=12.57
```

## 要点
- 一切默认私有;只有标了 `pub` 的项能被父模块外访问——封装是默认值。
- `pub(crate)` 适合"内部共享但不进公共 API"的项;`pub(super)` 限父模块。
- struct 字段可见性独立于 struct 本身:`pub struct` 的字段仍需各自 `pub`。
- `use` 只是引入名字别名,不改可见性;惯例 `use` 类型到名字、`use` 模块到函数(`util::round2`)。

## 关联
- 概览:[`../project-cargo.md`](../project-cargo.md)
- 规则:[`proj-pub-crate-internal`](../rules/proj-pub-crate-internal.md)、[`proj-pub-use-reexport`](../rules/proj-pub-use-reexport.md)、[`proj-mod-by-feature`](../rules/proj-mod-by-feature.md)
