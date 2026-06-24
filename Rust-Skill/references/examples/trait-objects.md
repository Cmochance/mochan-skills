# Trait 对象(dyn)

> `dyn Trait` 在运行期通过虚表分发,让不同具体类型存进同一容器;代价是间接调用 + 需 `Box`/`&` 包装(动态分发 vs 泛型的静态分发)。

```rust
trait Draw {
    fn draw(&self) -> String;
}

struct Button {
    label: String,
}
struct Slider {
    pos: u8,
}

impl Draw for Button {
    fn draw(&self) -> String {
        format!("[{}]", self.label)
    }
}
impl Draw for Slider {
    fn draw(&self) -> String {
        format!("|{}|", "=".repeat(self.pos as usize))
    }
}

// 静态分发:单态化,每个 T 一份代码,无虚表
fn render_static(d: &impl Draw) -> String {
    d.draw()
}

fn main() {
    // 动态分发:异构集合,运行期查虚表
    let widgets: Vec<Box<dyn Draw>> = vec![
        Box::new(Button { label: "OK".into() }),
        Box::new(Slider { pos: 3 }),
    ];
    for w in &widgets {
        println!("{}", w.draw());
    }

    // 对照:静态分发只能传单一已知类型
    println!("static: {}", render_static(&Button { label: "Go".into() }));
}
```

输出:
```
[OK]
|===|
static: [Go]
```

## 要点
- 何时用 `dyn`:需要把不同类型放进同一 `Vec`/字段,或想缩短编译/减少代码膨胀。
- 何时用泛型(`impl Trait`/`<T>`):类型在编译期确定、要零成本与内联。
- object safety:trait 能做 `dyn` 的前提是方法不返回 `Self`、无泛型方法等(否则编译报错)。
- `dyn Trait` 是 unsized,必须经 `Box<dyn>`/`&dyn`/`Rc<dyn>` 等胖指针使用。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`trait-dyn-vs-generic`](../rules/trait-dyn-vs-generic.md)、[`trait-object-safety`](../rules/trait-object-safety.md)
