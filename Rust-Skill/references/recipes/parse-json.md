# 解析 / 生成 JSON

> 一句话:`serde_json` 解析到强类型 struct、动态访问 `Value`、生成与流式。

## 依赖

```toml
serde = { version = "1", features = ["derive"] }
serde_json = "1"
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use anyhow::Result;

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]   // Rust snake_case <-> JSON camelCase
struct User {
    id: u64,
    display_name: String,
    #[serde(default)]                // 缺字段不报错,用 Default
    tags: Vec<String>,
}

fn parse_to_struct(s: &str) -> Result<User> {
    let user: User = serde_json::from_str(s)?;   // 强类型,字段不匹配即报错
    Ok(user)
}

fn dynamic_access(s: &str) -> Result<()> {
    // 结构未知 / 只取个别字段:用 Value 动态访问
    let v: Value = serde_json::from_str(s)?;
    // 索引返回 &Value(缺失得 Value::Null),配合 as_* 取原生类型
    if let Some(name) = v["display_name"].as_str() {
        println!("name = {name}");
    }
    let id = v.get("id").and_then(Value::as_u64).unwrap_or(0);
    println!("id = {id}");
    Ok(())
}

fn generate() -> Result<String> {
    // json! 宏写字面量,或 to_string / to_string_pretty 序列化类型
    let u = User { id: 7, display_name: "Ada".into(), tags: vec!["admin".into()] };
    let _compact = serde_json::to_string(&u)?;
    let pretty = serde_json::to_string_pretty(&json!({
        "ok": true,
        "user": u,
    }))?;
    Ok(pretty)
}
```

## 要点 / 坑

- 优先**强类型 struct**:编译期保证字段,比到处 `v["x"].as_str().unwrap()` 安全得多。
- 结构真不固定才用 `Value`;`v["missing"]` 不 panic 而得 `Null`,但 `v[0]` 对非数组也得 `Null`——用 `.get()` 更显式。
- 整数溢出:JSON number 超 `u64`/`i64` 范围解析会失败;大数用 `serde_json::Number` 或字符串。
- 流式读大文件:`serde_json::Deserializer::from_reader(reader).into_iter::<T>()` 逐条反序列化,别整文件读进内存。
- 浮点 `NaN`/`Inf` 不是合法 JSON,序列化会失败或变 `null`,数值边界自己控。

## 关联

- 概览:[`../serde-data.md`](../serde-data.md)
- 配置解析:[`parse-config`](parse-config.md)
- 规则:[`serde-rename-all`](../rules/serde-rename-all.md)、[`serde-default-compat`](../rules/serde-default-compat.md)、[`serde-try-from-validate`](../rules/serde-try-from-validate.md)
