# 模式匹配

> `match` 必须穷尽,编译期保证没漏分支;`if let`/`let else`/`while let` 是单分支简写;模式支持解构、守卫、`@` 绑定、`|`。

```rust
enum Msg {
    Quit,
    Move { x: i32, y: i32 },
    Write(String),
}

fn describe(code: i32) -> &'static str {
    match code {
        0 => "zero",
        n @ 1..=9 => { // @ 绑定:既匹配范围又拿到值
            let _ = n;
            "single digit"
        }
        n if n < 0 => "negative", // 守卫:额外布尔条件
        _ => "big",
    }
}

fn main() {
    let msgs = [Msg::Quit, Msg::Move { x: 1, y: 2 }, Msg::Write("hi".into())];
    for m in &msgs {
        match m {
            Msg::Quit => println!("quit"),
            Msg::Move { x, y } => println!("move {x},{y}"), // 解构字段
            Msg::Write(s) => println!("write {s}"),
        }
    }

    // if let:只关心一个变体
    let maybe = Some(7);
    if let Some(v) = maybe {
        println!("got {v}");
    }

    // let else:取不到就提前 return/break(这里 break)
    let mut it = [1, 2].into_iter();
    while let Some(v) = it.next() {
        print!("{v} ");
    }
    println!();

    for c in [-3, 0, 5, 100] {
        println!("{c} -> {}", describe(c));
    }
}
```

输出:
```
quit
move 1,2
write hi
got 7
1 2 
-3 -> negative
0 -> zero
5 -> single digit
100 -> big
```

## 要点
- `match` 穷尽:漏分支编译报错;用 `_` 兜底但别滥用(枚举变体增加时,无 `_` 能逼你处理新变体)。
- `|` 合并多模式、`1..=9` 范围、`@` 同时绑值、`if` 守卫加条件——可组合。
- `if let`/`while let` 是只关心单一变体时的简写;`let else { ... }` 在不匹配时走发散分支(return/break/panic)。
- 解构与借用一致:`match m`(借)里拿到的是 `&` 引用,需要所有权用 `match m.clone()` 或值匹配。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`pat-exhaustive-enum`](../rules/pat-exhaustive-enum.md)、[`pat-let-else`](../rules/pat-let-else.md)、[`pat-at-bindings`](../rules/pat-at-bindings.md)、[`pat-matches-macro`](../rules/pat-matches-macro.md)
