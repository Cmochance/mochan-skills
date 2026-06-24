# 数据库访问(sqlx + PgPool)

> 一句话:用 `sqlx` 建连接池、`query!` 做编译期校验的查询、事务、把行 map 到 struct。

## 依赖
```toml
# 版本以 docs.rs 最新为准
sqlx = { version = "0.8", features = ["runtime-tokio", "postgres", "macros"] }
tokio = { version = "1", features = ["full"] }
```

## 做法
```rust
use sqlx::postgres::PgPoolOptions;

#[derive(Debug)]
struct User { id: i64, name: String }

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // 连接池:全程复用一个 Pool,clone 只复制句柄
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect("postgres://user:pass@localhost/mydb").await?;

    // query_as! 编译期校验 SQL + 列类型,直接 map 到 struct
    // 需要 DATABASE_URL 环境变量或离线 .sqlx/ 缓存,否则 cargo 编不过
    let user = sqlx::query_as!(
        User,
        "SELECT id, name FROM users WHERE id = $1",
        1i64
    )
    .fetch_one(&pool).await?;
    println!("{user:?}");

    // 事务:成功 commit,出错(? 提前返回)自动 rollback
    let mut tx = pool.begin().await?;
    sqlx::query!("INSERT INTO users (name) VALUES ($1)", "alice")
        .execute(&mut *tx).await?;
    sqlx::query!("UPDATE counters SET n = n + 1 WHERE k = 'users'")
        .execute(&mut *tx).await?;
    tx.commit().await?; // 不 commit 而 drop = 自动 rollback

    Ok(())
}
```

## 要点 / 坑
- `query!`/`query_as!` 在**编译期**连数据库校验 SQL 与类型:需 `DATABASE_URL` 或预生成的离线缓存(`cargo sqlx prepare` 产 `.sqlx/`)。不想编译期连库用运行时版 `sqlx::query(...)`(无校验)。
- `Pool` 内部是 `Arc`,**构造一次全程 clone 复用**,别每次开新池。
- 事务用 `&mut *tx` 传给 query;`tx` drop 未 commit 即 rollback——靠 `?` 提前返回天然得到回滚。
- feature 要选对 runtime + driver(如 `runtime-tokio` + `postgres`);MySQL/SQLite 换对应 feature。

## 关联
- 概览:[`../domain-systems.md`](../domain-systems.md)
- 规则:[`err-anyhow-app`](../rules/err-anyhow-app.md)、[`err-question-mark`](../rules/err-question-mark.md)
