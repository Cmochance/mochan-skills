# 正则匹配

> 一句话:`regex` 做匹配/捕获组/替换,用 `LazyLock`/`once_cell` 编译一次复用。

## 依赖

```toml
regex = "1"
# once_cell = "1"   # 若 MSRV < 1.80,用它代替 std::sync::LazyLock
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use std::sync::LazyLock;   // Rust 1.80+;更老的工具链用 once_cell::sync::Lazy
use regex::Regex;

// 编译一次,全局复用 —— Regex::new 较贵,别在循环/热路径里反复 new
static EMAIL: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?P<user>[\w.+-]+)@(?P<domain>[\w-]+\.[\w.-]+)").unwrap());

fn demo(text: &str) {
    // 是否匹配
    if EMAIL.is_match(text) {
        // 取第一个匹配的命名捕获组
        if let Some(caps) = EMAIL.captures(text) {
            // 命名组用 name 取,返回 Option<Match>
            let user = caps.name("user").map(|m| m.as_str()).unwrap_or("");
            let domain = &caps["domain"];   // 索引语法:组不存在会 panic,确定存在才用
            println!("{user} @ {domain}");
        }
    }

    // 遍历所有匹配
    for caps in EMAIL.captures_iter(text) {
        println!("命中: {}", &caps[0]);     // [0] 是整个匹配
    }

    // 替换:$user/$domain 引用命名组;replace_all 替换全部
    let masked = EMAIL.replace_all(text, "$user@***");
    println!("{masked}");                   // 返回 Cow<str>,无匹配时零拷贝
}
```

## 要点 / 坑

- **`Regex::new` 编译开销大**:务必 `LazyLock`/`once_cell` 编译一次复用,别在循环或每次调用里 `new`。
- `caps["name"]` 索引语法**组不存在会 panic**;不确定用 `caps.name("x")` 拿 `Option`。
- `regex` crate **不支持** 回溯特性(lookahead/lookbehind/反向引用),换来线性时间保证;真要这些用 `fancy-regex`(查 docs.rs)。
- `(?i)` 不区分大小写、`(?s)` 让 `.` 匹配换行、`(?m)` 多行模式——内联 flag 比重复写模式干净。
- 替换返回 `Cow<str>`,无匹配时不分配;别无脑 `.to_string()` 丢掉这个优化。

## 关联

- 概览:[`../serde-data.md`](../serde-data.md)(文本处理相关)
- 字符串:[`string-manipulation`](string-manipulation.md)
- 规则:[`perf-collect-once`](../rules/perf-collect-once.md)、[`own-cow-conditional`](../rules/own-cow-conditional.md)
