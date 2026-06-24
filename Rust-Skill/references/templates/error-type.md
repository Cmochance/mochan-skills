# 错误类型模板

## 库:thiserror(typed、可匹配)

```rust
use thiserror::Error;

/// 库对外暴露的错误类型——让调用方能 `match` 具体分支。
#[derive(Debug, Error)]
pub enum MyError {
    #[error("config file not found: {path}")]
    ConfigNotFound { path: String },

    #[error("invalid value for `{key}`: {value}")]
    InvalidValue { key: String, value: String },

    /// 包裹下游错误并保留 source 链(`?` 自动 From)。
    #[error("io error")]
    Io(#[from] std::io::Error),

    #[error("parse error")]
    Parse(#[from] std::num::ParseIntError),
}

pub type Result<T> = std::result::Result<T, MyError>;

pub fn load(path: &str) -> Result<i64> {
    let text = std::fs::read_to_string(path)?;   // io::Error -> MyError::Io
    let n: i64 = text.trim().parse()?;            // ParseIntError -> MyError::Parse
    Ok(n)
}
```

要点:
- `#[from]` 自动生成 `From`,让 `?` 直接转换;`#[source]` 标注非 from 的来源字段。
- `#[error("...")]` 的消息**小写开头、不带句号**(对齐 `rules/err-lowercase-msg`)。
- 别在库里用 `anyhow`(抹掉类型,调用方没法 match)。见 `rules/err-thiserror-lib`、`rules/err-custom-type`。

## 应用:anyhow(动态、带 context)

```rust
use anyhow::{Context, Result, bail, ensure};

fn run(path: &str) -> Result<()> {
    let cfg = std::fs::read_to_string(path)
        .with_context(|| format!("reading config {path}"))?;   // 加上下文

    ensure!(!cfg.is_empty(), "config {path} is empty");        // 条件不满足即 Err

    let port: u16 = cfg.trim().parse()
        .context("config must be a port number")?;

    if port < 1024 {
        bail!("port {port} is privileged");                    // 提前返回错误
    }
    Ok(())
}

fn main() -> Result<()> {
    run("app.toml")    // main 返回 Result,自动打印错误链 + 非零退出
}
```

要点:
- 应用顶层用 `anyhow`/`eyre`,关键边界用 `.context()`/`.with_context()` 留线索。
- 库与应用分层:库 thiserror → 应用 anyhow(`?` 自动把库 error 装进 anyhow)。
- 关联:`error-handling.md`、`rules/err-anyhow-app`、`rules/err-context-chain`。
