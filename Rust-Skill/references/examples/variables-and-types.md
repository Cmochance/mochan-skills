# 变量与基本类型

> `let` 默认不可变,`mut` 才可变;基本标量类型(整数/浮点/bool/char)+ 复合(元组/数组)由编译器推断,必要时显式标注。

```rust
fn main() {
    let x = 5; // 不可变,推断为 i32
    let mut y = 10; // mut 才能改
    y += x;

    // shadowing:同名 let 重新绑定,可换类型
    let spaces = "   ";
    let spaces = spaces.len(); // 现在是 usize,不是 &str

    // 显式类型标注(推断不出时必须写,如 parse)
    let n: u64 = "42".parse().unwrap();
    let pi: f64 = 3.14;
    let yes: bool = true;
    let ch: char = '中'; // char 是 4 字节 Unicode 标量值

    // 元组:异构定长,可解构
    let point = (1, 2.5, 'A');
    let (a, b, _c) = point;

    // 数组:同构定长,栈上分配
    let arr = [10, 20, 30];
    let zeros = [0u8; 4]; // [0, 0, 0, 0]

    println!("y={y} spaces={spaces} n={n} pi={pi} yes={yes} ch={ch}");
    println!("a={a} b={b} arr[1]={} zeros.len()={}", arr[1], zeros.len());
}
```

输出:
```
y=15 spaces=3 n=42 pi=3.14 yes=true ch=中
a=1 b=2.5 arr[1]=20 zeros.len()=4
```

## 要点
- 不可变是默认值;`mut` 是显式选择。这让"哪些状态会变"在类型层面可见。
- shadowing ≠ `mut`:它创建新变量、可换类型;`mut` 原地改、类型不变。
- 整数默认 `i32`,浮点默认 `f64`;字面量可加后缀(`42u64`、`3.14f32`)消除歧义。
- 数组 `[T; N]` 长度是类型一部分、栈分配;要变长用 `Vec<T>`(见 collections)。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`own-copy-small`](../rules/own-copy-small.md)
