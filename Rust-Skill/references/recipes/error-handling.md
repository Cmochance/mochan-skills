# 错误处理实战(thiserror 库 + anyhow 应用)

> 一句话:库里用 `thiserror` 定义具体错误枚举,应用里用 `anyhow` 加 context,`?` 全程贯穿。

## 依赖
```toml
# 版本以 docs.rs 最新为准
thiserror = "2"   # 库:定义可匹配的错误类型
anyhow = "1"      # 应用:聚合 + context,不必逐一定义
```

## 做法
```rust
// ===== 库侧:用 thiserror 定义具体错误,调用方可 match =====
mod store {
    use thiserror::Error;

    #[derive(Error, Debug)]
    pub enum StoreError {
        #[error("找不到 key: {0}")]      // Display 文案,小写开头、不带句号
        NotFound(String),
        #[error("IO 失败")]
        Io(#[from] std::io::Error),       // #[from] 自动生成 From,? 可直接转换
    }

    pub fn load(key: &str) -> Result<String, StoreError> {
        if key.is_empty() {
            return Err(StoreError::NotFound(key.to_string()));
        }
        let content = std::fs::read_to_string(format!("/data/{key}"))?; // io::Error 经 #[from] 自动转
        Ok(content)
    }
}

// ===== 应用侧:用 anyhow 聚合,.context() 补现场信息 =====
use anyhow::{Context, Result};

fn run(key: &str) -> Result<usize> {
    let data = store::load(key)
        .with_context(|| format!("加载配置 {key} 失败"))?; // 失败时附带这层语义
    let parsed: usize = data.trim().parse()
        .context("配置内容不是合法数字")?;
    Ok(parsed)
}

fn main() -> Result<()> {
    let n = run("size")?;       // main 返 Result:错误链会被打印
    println!("size = {n}");
    Ok(())
}
```

## 要点 / 坑
- **分工**:库(被别人依赖)用 `thiserror` 给具体可 match 的类型;应用(顶层)用 `anyhow::Result` 省去逐个建类型,`.context()` 加排查线索。库里别用 `anyhow`(逼调用方丢失类型信息)。
- `#[from]` 自动生成 `From`,让 `?` 在不同错误类型间无缝转换;消息文案小写开头、不带句号(惯例)。
- `.context()` / `.with_context()` 每层补一句"在做什么时失败",最终打印成错误链——比裸 `?` 好排查得多。
- 别 `unwrap()`/`expect()` 兜底可恢复错误;`expect` 只用于"逻辑上不可能发生、发生即 bug"处并写清原因。

## 关联
- 概览:[`../error-handling.md`](../error-handling.md)
- 规则:[`err-thiserror-lib`](../rules/err-thiserror-lib.md)、[`err-anyhow-app`](../rules/err-anyhow-app.md)、[`err-context-chain`](../rules/err-context-chain.md)、[`err-from-impl`](../rules/err-from-impl.md)、[`err-question-mark`](../rules/err-question-mark.md)
