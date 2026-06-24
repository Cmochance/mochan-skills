# 环境变量与命令行参数

> 一句话:`std::env` 读环境变量/参数,`dotenvy` 加载 `.env`,优雅处理缺失与默认值。

## 依赖

```toml
dotenvy = "0.15"   # 加载 .env 文件到进程环境(dotenv 的活跃 fork)
# 复杂参数解析用 clap,见 domain-cli.md
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use std::env;
use anyhow::{Context, Result};

fn demo() -> Result<()> {
    // 0) 先加载 .env(若存在);文件缺失不报错,生产环境通常不依赖它
    let _ = dotenvy::dotenv();   // 返回 Result,故意忽略"文件不存在"

    // 1) 读环境变量:var 返回 Result(未设置/非 UTF-8 都是 Err)
    let db_url = env::var("DATABASE_URL")
        .context("必须设置 DATABASE_URL")?;        // 必填:缺了就报错退出

    // 2) 带默认值:可选配置用 unwrap_or_else,别 ? 掉
    let port: u16 = env::var("PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(8080);                          // 缺失或解析失败都回落默认

    // 3) 命令行参数:args() 第 0 个是程序名,跳过
    let args: Vec<String> = env::args().skip(1).collect();
    if let Some(cmd) = args.first() {
        println!("子命令 = {cmd}");
    }

    println!("{db_url} :{port}");
    Ok(())
}
```

## 要点 / 坑

- `env::var` 在变量**未设置**或**含非 UTF-8** 时返回 `Err`;要原始字节用 `env::var_os`(返回 `Option<OsString>`)。
- 必填配置 `?`/`context` 让它早失败并给清晰提示;可选配置 `.ok().unwrap_or(default)`,别让缺失静默变空串。
- `dotenvy::dotenv()` 只在**进程启动早期**调一次有意义,且**不覆盖**已存在的真实环境变量(真实 env 优先级更高)。
- 参数解析超过两三个 flag 就上 `clap`(derive API),别手写 `args` 状态机——见关联。
- `set_var`/`remove_var` 在多线程下有数据竞争风险(新版 std 标记 `unsafe`);测试里改环境要串行,别并发。

## 关联

- 概览:[`../domain-cli.md`](../domain-cli.md)
- 配置:[`parse-config`](parse-config.md)
- 规则:[`err-context-chain`](../rules/err-context-chain.md)、[`type-option-nullable`](../rules/type-option-nullable.md)
