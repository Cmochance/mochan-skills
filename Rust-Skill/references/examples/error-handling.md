# 错误处理

> 可恢复错误用 `Result<T, E>`、可空用 `Option<T>`;`?` 自动传播并 `From` 转换错误类型;组合子(`map`/`and_then`/`unwrap_or`)避免显式 match。

```rust
use std::fmt;

// 最小自定义 error:实现 Display + Error 即可被 ? 链入
#[derive(Debug)]
enum ParseErr {
    Empty,
    NotNumber(String),
}

impl fmt::Display for ParseErr {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ParseErr::Empty => write!(f, "empty input"),
            ParseErr::NotNumber(s) => write!(f, "not a number: {s}"),
        }
    }
}
impl std::error::Error for ParseErr {}

fn parse_positive(s: &str) -> Result<u32, ParseErr> {
    if s.is_empty() {
        return Err(ParseErr::Empty);
    }
    let n: u32 = s.parse().map_err(|_| ParseErr::NotNumber(s.to_string()))?; // ? 传播
    Ok(n)
}

fn first_word(s: &str) -> Option<&str> {
    s.split_whitespace().next() // 空串 -> None
}

fn main() {
    // ? 在返回 Result 的函数里传播;main 也可返回 Result
    for input in ["42", "", "abc"] {
        match parse_positive(input) {
            Ok(n) => println!("ok {n}"),
            Err(e) => println!("err: {e}"),
        }
    }

    // Option 组合子:不写 match
    let len = first_word("hello world").map(|w| w.len()).unwrap_or(0);
    println!("first word len={len}");

    // and_then 串联可能失败的步骤
    let doubled = parse_positive("10").map(|n| n * 2).unwrap_or(0);
    println!("doubled={doubled}");
}
```

输出:
```
ok 42
err: empty input
err: not a number: abc
first word len=5
doubled=20
```

## 要点
- 库返 `Result<T, 自定义 E>`(实现 `Error`);应用层可用 `anyhow` 兜底,二分明确。
- `?` 在 `Err` 时提前 return,并对错误做 `From` 转换——比手写 match 短得多。
- `Option`/`Result` 的组合子:`map`(变换成功值)、`and_then`(链下一个 fallible)、`unwrap_or`(给默认)。
- 别 `unwrap()` 一把梭:那是"逻辑上不可能 None"的断言;能恢复就用 `?` 或组合子。

## 关联
- 概览:[`../error-handling.md`](../error-handling.md)
- 规则:[`err-custom-type`](../rules/err-custom-type.md)、[`err-question-mark`](../rules/err-question-mark.md)、[`err-result-over-panic`](../rules/err-result-over-panic.md)、[`err-thiserror-lib`](../rules/err-thiserror-lib.md)
