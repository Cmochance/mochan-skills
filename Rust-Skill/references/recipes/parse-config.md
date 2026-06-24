# 解析配置文件

> 一句话:TOML/YAML 反序列化到 struct,分层配置用 `figment`/`config` 叠加默认值+文件+环境变量。

## 依赖

```toml
serde = { version = "1", features = ["derive"] }
toml = "0.8"          # TOML(Cargo.toml 即此格式)
serde_yaml = "0.9"    # YAML —— 注:该 crate 已停止维护,新项目可看 serde_yml / serde_norway,选型查 docs.rs
figment = { version = "0.10", features = ["toml", "env"] }  # 分层配置
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use serde::Deserialize;
use anyhow::Result;

#[derive(Debug, Deserialize)]
struct Config {
    #[serde(default = "default_port")]
    port: u16,
    host: String,
    #[serde(default)]
    debug: bool,
}
fn default_port() -> u16 { 8080 }

// 单文件 TOML
fn from_toml(text: &str) -> Result<Config> {
    let cfg: Config = toml::from_str(text)?;
    Ok(cfg)
}

// 单文件 YAML(注意 crate 维护状态)
fn from_yaml(text: &str) -> Result<Config> {
    let cfg: Config = serde_yaml::from_str(text)?;
    Ok(cfg)
}

// 分层:默认值 -> 文件覆盖 -> 环境变量覆盖(APP_PORT 等),figment 合并
fn layered() -> Result<Config> {
    use figment::{Figment, providers::{Format, Toml, Env, Serialized}};
    let cfg: Config = Figment::new()
        .merge(Serialized::defaults(serde_json::json!({ "host": "127.0.0.1" })))
        .merge(Toml::file("app.toml"))      // 文件不存在则跳过,不报错
        .merge(Env::prefixed("APP_"))       // APP_PORT=9090 覆盖
        .extract()?;
    Ok(cfg)
}
```

## 要点 / 坑

- 缺省值靠 `#[serde(default)]`/`default = "fn"`,别让必填字段缺失时给个不友好的反序列化报错。
- `serde_yaml` 长期**未维护**;评估 `serde_yml`/`serde_norway` 等 fork,以 docs.rs 当前状态为准,别想当然。
- 分层配置的**优先级顺序 = merge 调用顺序**,后 merge 的覆盖先 merge 的;搞错顺序环境变量盖不住文件。
- 环境变量都是字符串,`figment`/`config` 会按目标类型解析,`APP_PORT=abc` 会在 `extract()` 报错——错误信息友好。
- TOML 不支持 `null`;可选字段用 `Option<T>` + 省略键,而非写 `key = null`。

## 关联

- 概览:[`../serde-data.md`](../serde-data.md)
- JSON:[`parse-json`](parse-json.md)、环境变量:[`env-and-args`](env-and-args.md)
- 规则:[`serde-default-compat`](../rules/serde-default-compat.md)、[`api-serde-optional`](../rules/api-serde-optional.md)
