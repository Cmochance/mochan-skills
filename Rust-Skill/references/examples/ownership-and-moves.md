# 所有权与移动

> 每个值有唯一所有者;非 `Copy` 类型赋值/传参是 move,原变量失效。借用 `&`/`&mut` 让你用而不夺走所有权。

```rust
fn takes_ownership(s: String) -> usize {
    s.len() // s 在此函数结束时被 drop
}

fn borrows(s: &str) -> usize {
    s.len() // 只读借用,不夺所有权
}

fn append(s: &mut String) {
    s.push_str("!"); // 可变借用,原地改
}

fn main() {
    let s1 = String::from("hi");
    let s2 = s1; // move:s1 失效,不能再用 s1
    // println!("{s1}"); // 编译错误 E0382: value borrowed after move

    let len = borrows(&s2); // 借用,s2 仍可用
    println!("{s2} len={len}");

    let mut owned = s2.clone(); // 显式 clone:需要第二份独立数据时才用
    append(&mut owned);
    println!("after append: {owned}");

    let consumed = takes_ownership(owned); // owned 被移走
    println!("consumed len={consumed}");

    // Copy 类型(i32)按位复制,不 move
    let n = 5;
    let m = n;
    println!("n={n} m={m}"); // n 仍可用
}
```

输出:
```
hi len=2
after append: hi!
consumed len=3
n=5 m=5
```

## 要点
- move 后原变量失效(E0382);需要原变量继续用就**借用**而不是移动。
- 决策顺序:借用够吗 → 是 `Copy` 小类型吗 → 重构所有权 → **最后才 `clone`**(显式、有理由)。
- 函数签名表达意图:`&T` 只读、`&mut T` 改、`T` 夺走所有权(常见于消费型 API)。
- 同一时刻:多个 `&` 或唯一一个 `&mut`,二者不可兼得(别名 ⊕ 可变)。

## 关联
- 概览:[`../ownership-lifetimes.md`](../ownership-lifetimes.md)
- 规则:[`own-borrow-over-clone`](../rules/own-borrow-over-clone.md)、[`own-clone-explicit`](../rules/own-clone-explicit.md)、[`own-copy-small`](../rules/own-copy-small.md)
