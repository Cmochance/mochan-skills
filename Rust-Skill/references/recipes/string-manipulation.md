# 字符串处理

> 一句话:切分/拼接/大小写/trim/格式化,以及 Unicode 正确的字符与字素切分。

## 依赖

```toml
# 核心全是 std
unicode-segmentation = "1"   # 按"用户感知字符"(grapheme)切分,处理 emoji/组合字符
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use unicode_segmentation::UnicodeSegmentation;

fn demo() {
    let s = "  Hello, World, Rust  ";

    // trim / 切分:split 返回惰性迭代器
    let trimmed = s.trim();                                  // "Hello, World, Rust"
    let parts: Vec<&str> = trimmed.split(", ").collect();    // ["Hello", "World", "Rust"]

    // 拼接:join 比循环 += 高效;大量拼接预分配 String::with_capacity
    let joined = parts.join(" | ");
    let mut buf = String::with_capacity(64);
    for p in &parts { buf.push_str(p); buf.push('\n'); }

    // 大小写(ASCII 廉价;含非 ASCII 用 Unicode 版,可能改变长度)
    let _ = "Ä".to_lowercase();          // Unicode-aware
    let _ = "abc".to_ascii_uppercase();  // 仅 ASCII,更快

    // 查找 / 替换 / 前后缀
    let _ = trimmed.contains("World");
    let _ = trimmed.replace("Rust", "🦀");
    let _ = trimmed.strip_prefix("Hello");   // 返回 Option<&str>

    // 格式化:format! 分配 String;写进已有 buffer 用 write!
    let n = 42;
    let _ = format!("value = {n:>5}");        // 右对齐宽 5

    // Unicode 正确性:chars() 按 Unicode scalar,可能把一个 emoji 拆成多个码点
    let flag = "👨‍👩‍👧";
    println!("chars = {}", flag.chars().count());                 // 不是 1
    println!("graphemes = {}", flag.graphemes(true).count());     // 用户看到的 1 个

    let _ = (joined, buf);
}
```

## 要点 / 坑

- Rust `String` 是 **UTF-8**;**不能按字节下标** `s[0]`(不编译)。要第 n 个字符用 `s.chars().nth(n)`。
- "字符数"有三层:字节(`.len()`)、码点(`.chars().count()`)、字素(`.graphemes()`)——emoji/组合字符下三者不同,选对再比较/截断。
- 截断字符串别按字节切(可能切在 UTF-8 多字节中间 panic);用 `char_indices()` 找合法边界或 `chars().take(n)`。
- `split` 返回**惰性迭代器**,能直接链 `map`/`filter`,别急着 `collect`。
- 重度拼接 `String::with_capacity` 预分配,避免反复 realloc;循环里写文本用 `write!(&mut s, ...)`。

## 关联

- 概览:[`../serde-data.md`](../serde-data.md)
- 正则:[`regex-matching`](regex-matching.md)
- 规则:[`anti-string-for-str`](../rules/anti-string-for-str.md)、[`mem-write-over-format`](../rules/mem-write-over-format.md)、[`mem-with-capacity`](../rules/mem-with-capacity.md)
