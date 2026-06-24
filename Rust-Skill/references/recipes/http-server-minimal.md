# axum 最小 HTTP 服务

> 一句话:用 `axum` 起一个带路由、`Json` 提取/返回、共享 `State` 的最小服务。

## 依赖
```toml
# 版本以 docs.rs 最新为准
axum = "0.8"
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
```

## 做法
```rust
use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};

// 共享状态:Arc 跨 handler 共享,内部可变用 Mutex。
// 临界区纯同步、不跨 .await,用 std::sync::Mutex 即可。
#[derive(Clone)]
struct AppState {
    counter: Arc<Mutex<u64>>,
}

#[derive(Serialize)]
struct CountResp { count: u64 }

#[derive(Deserialize)]
struct AddReq { by: u64 }

async fn show(State(st): State<AppState>) -> Json<CountResp> {
    let count = *st.counter.lock().unwrap(); // 取值后锁立即释放,不跨 await
    Json(CountResp { count })
}

async fn add(State(st): State<AppState>, Json(req): Json<AddReq>) -> Json<CountResp> {
    let count = {
        let mut g = st.counter.lock().unwrap();
        *g += req.by;
        *g
    }; // guard 在块末 drop,后面没有 .await 持着它
    Json(CountResp { count })
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let state = AppState { counter: Arc::new(Mutex::new(0)) };
    let app = Router::new()
        .route("/count", get(show))
        .route("/count", post(add))
        .with_state(state);

    let listener = tokio::net::TcpListener::bind("127.0.0.1:3000").await?;
    axum::serve(listener, app).await?;
    Ok(())
}
```

## 要点 / 坑
- handler 是 `async fn`,返回任意实现 `IntoResponse` 的类型;`Json<T>` 既是提取器又是响应。
- `State<S>` 的 `S` 要 `Clone`(handler 各拿一份),共享数据放 `Arc` 里、clone 只复制指针。
- `Json(req)` 提取器**必须放参数列表最后**(它消费 body)。
- 别在 handler 里持 `std::sync::Mutex` guard 跨 `.await`——extract→release,见关联规则。

## 关联
- 概览:[`../domain-web.md`](../domain-web.md)
- 规则:[`own-arc-shared`](../rules/own-arc-shared.md)、[`anti-lock-across-await`](../rules/anti-lock-across-await.md)
