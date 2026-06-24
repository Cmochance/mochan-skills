# 类型转换

> `From`/`Into` 是不会失败的转换(实现 `From` 自动得 `Into`);`TryFrom`/`TryInto` 是可能失败的(返 `Result`);`AsRef` 廉价借用转换;`str::parse` 经 `FromStr` 把字符串解析成类型。

```rust
use std::convert::TryFrom;

// 实现 From,自动获得 Into
struct Celsius(f64);
struct Fahrenheit(f64);

impl From<Celsius> for Fahrenheit {
    fn from(c: Celsius) -> Self {
        Fahrenheit(c.0 * 9.0 / 5.0 + 32.0)
    }
}

// TryFrom:带校验的可失败转换
struct Percent(u8);

impl TryFrom<i32> for Percent {
    type Error = String;
    fn try_from(v: i32) -> Result<Self, Self::Error> {
        if (0..=100).contains(&v) {
            Ok(Percent(v as u8))
        } else {
            Err(format!("{v} out of 0..=100"))
        }
    }
}

// AsRef:写一个函数同时接受 &str / String / &String
fn shout(s: impl AsRef<str>) -> String {
    s.as_ref().to_uppercase()
}

fn main() {
    let f: Fahrenheit = Celsius(100.0).into(); // From -> Into
    println!("100C = {}F", f.0);

    println!("{:?}", Percent::try_from(50).map(|p| p.0)); // Ok(50)
    println!("{:?}", Percent::try_from(150).map(|p| p.0)); // Err(...)

    println!("{} {}", shout("hi"), shout(String::from("bye")));

    // parse 经 FromStr;turbofish 或类型标注指定目标
    let n = "42".parse::<i32>().unwrap();
    let pi: f64 = "3.14".parse().unwrap();
    println!("n={n} pi={pi}");
}
```

输出:
```
100C = 212F
Ok(50)
Err("150 out of 0..=100")
HI BYE
n=42 pi=3.14
```

## 要点
- 实现 `From` 而非 `Into`:标准库有 blanket impl 让你自动获得 `Into`(且 `?` 靠 `From` 转错误)。
- 失败的转换走 `TryFrom`/`TryInto`(返 `Result`),别在 `From` 里偷偷 panic。
- `AsRef<str>`/`AsRef<Path>` 让 API 灵活接受多种引用类型,零拷贝。
- `parse()` 是 `FromStr` 的入口;目标类型用 `.parse::<T>()` 或 `let x: T = ...parse()?` 指定。

## 关联
- 概览:[`../types-traits-generics.md`](../types-traits-generics.md)
- 规则:[`api-from-not-into`](../rules/api-from-not-into.md)、[`conv-tryfrom-fallible`](../rules/conv-tryfrom-fallible.md)、[`conv-fromstr-parsing`](../rules/conv-fromstr-parsing.md)、[`api-impl-asref`](../rules/api-impl-asref.md)
