# CLI 参数解析(clap derive)

> 一句话:用 `clap` 的 derive 宏定义 `Parser`、子命令 enum、参数校验,返回 `ExitCode`。

## 依赖
```toml
# 版本以 docs.rs 最新为准
clap = { version = "4", features = ["derive"] }
```

## 做法
```rust
use clap::{Parser, Subcommand};
use std::process::ExitCode;

#[derive(Parser)]
#[command(name = "mytool", version, about = "示例 CLI")]
struct Cli {
    /// 全局开关:-v / --verbose,可叠加(-vv)提升级别
    #[arg(short, long, action = clap::ArgAction::Count)]
    verbose: u8,

    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand)]
enum Command {
    /// 加法:mytool add 1 2
    Add { a: i64, b: i64 },
    /// 问候:mytool greet --name alice [--times 3]
    Greet {
        #[arg(long)]
        name: String,
        /// value_parser 自带范围校验,越界 clap 直接报错退出
        #[arg(long, default_value_t = 1, value_parser = clap::value_parser!(u8).range(1..=10))]
        times: u8,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse(); // 解析失败 clap 自动打 usage 并 exit(2)
    match cli.cmd {
        Command::Add { a, b } => println!("{}", a + b),
        Command::Greet { name, times } => {
            for _ in 0..times { println!("Hello, {name}!"); }
        }
    }
    ExitCode::SUCCESS // 失败路径 return ExitCode::FAILURE
}
```

## 要点 / 坑
- `Cli::parse()` 解析失败(缺参/越界/`--help`)会自己打印信息并 `exit`,正常逻辑不必管这些。
- doc 注释(`///`)自动变成 `--help` 里的说明文字——写清楚就有好帮助。
- 校验优先用 clap 内建:`value_parser!(T).range(..)`、`required`、`conflicts_with`、自定义 `value_parser = fn`;别 parse 完再手写 if 校验。
- 返回 `ExitCode` 让退出码可控;需要更丰富的错误链可改 `-> anyhow::Result<()>`(错误打印到 stderr,非零退出)。

## 关联
- 概览:[`../domain-cli.md`](../domain-cli.md)
- 规则:[`conv-fromstr-parsing`](../rules/conv-fromstr-parsing.md)、[`api-parse-dont-validate`](../rules/api-parse-dont-validate.md)
