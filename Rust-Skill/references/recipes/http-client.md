# HTTP 客户端(reqwest)

> 一句话:用 `reqwest` 发 GET/POST、带 header 与超时、收发 JSON、把错误用 `?` 传播。

## 依赖
```toml
# 版本以 docs.rs 最新为准
reqwest = { version = "0.12", features = ["json"] }   # async 版默认带 rustls
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
anyhow = "1"
# 同步阻塞版另加 feature:reqwest = { version = "0.12", features = ["json", "blocking"] }
```

## 做法
```rust
use serde::{Deserialize, Serialize};
use std::time::Duration;

#[derive(Deserialize, Debug)]
struct Todo { id: u64, title: String }

#[derive(Serialize)]
struct NewTodo<'a> { title: &'a str }

// 复用 Client(内含连接池),别每次请求都新建
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(10)) // 整请求超时
        .build()?;

    // GET + 反序列化 JSON
    let todo: Todo = client
        .get("https://example.com/todos/1")
        .header("Accept", "application/json")
        .send().await?
        .error_for_status()?      // 把 4xx/5xx 转成 Err,而非静默拿错误体
        .json().await?;
    println!("{todo:?}");

    // POST JSON body
    let created: Todo = client
        .post("https://example.com/todos")
        .json(&NewTodo { title: "买菜" })
        .send().await?
        .error_for_status()?
        .json().await?;
    println!("created id={}", created.id);
    Ok(())
}
```

同步阻塞版(无 runtime,适合脚本/CLI):`reqwest::blocking::Client::new().get(url).send()?.json()?;`,API 与 async 几乎一致,只是去掉 `.await`。注意:**别在 tokio async 上下文里调 blocking 版**(会 panic 或堵线程)。

## 要点 / 坑
- `Client` 持有连接池,**构造一次全程复用**;到处 `Client::new()` 丢失 keep-alive。
- `send().await?` 只在网络/超时失败时 `Err`;HTTP 4xx/5xx 默认是成功的响应,要 `error_for_status()` 才转错误。
- 超时分层:`.timeout()` 是整请求;还有 `connect_timeout()` 单独管连接阶段。
- `features = ["json"]` 才有 `.json()`;不开则只能 `.text()` / `.bytes()`。

## 关联
- 概览:[`../domain-systems.md`](../domain-systems.md)
- 规则:[`err-question-mark`](../rules/err-question-mark.md)、[`err-anyhow-app`](../rules/err-anyhow-app.md)
