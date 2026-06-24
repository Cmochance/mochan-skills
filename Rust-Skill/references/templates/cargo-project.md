# Cargo 项目骨架

## 二进制项目

```
myapp/
├── Cargo.toml
├── src/
│   ├── main.rs        # 入口:只做参数解析 + 调 lib
│   └── lib.rs         # 真正逻辑放这,便于测试与复用
└── tests/
    └── cli.rs         # 集成测试
```

```toml
# Cargo.toml
[package]
name = "myapp"
version = "0.1.0"
edition = "2021"
rust-version = "1.74"          # MSRV,按需
license = "MIT OR Apache-2.0"
description = "一句话描述"
repository = "https://github.com/you/myapp"

[dependencies]
anyhow = "1"
clap = { version = "4", features = ["derive"] }

[dev-dependencies]
assert_cmd = "2"
predicates = "3"

[profile.release]
lto = "thin"
codegen-units = 1
strip = true
```

```rust
// src/main.rs — 入口薄,逻辑在 lib
use anyhow::Result;

fn main() -> Result<()> {
    myapp::run()
}
```

```rust
// src/lib.rs
use anyhow::Result;

pub fn run() -> Result<()> {
    // 真正逻辑;可被集成测试直接调
    Ok(())
}
```

## 库项目

```toml
[package]
name = "mylib"
version = "0.1.0"
edition = "2021"
license = "MIT OR Apache-2.0"
description = "..."
categories = ["..."]
keywords = ["..."]

[dependencies]
thiserror = "2"

[features]
default = []
serde = ["dep:serde"]          # 可选集成做成 feature

[dependencies.serde]
version = "1"
features = ["derive"]
optional = true
```

```rust
// src/lib.rs
#![warn(missing_docs)]          // 公共 API 强制文档
//! crate 级文档:这个库做什么、怎么用。

/// 公共类型示例。
#[derive(Debug, Clone)]
pub struct Thing;
```

## Workspace(多 crate)

```
myworkspace/
├── Cargo.toml          # workspace 根
├── crates/
│   ├── core/           # 库
│   ├── cli/            # 二进制,依赖 core
│   └── macros/         # 过程宏(proc-macro = true)
```

```toml
# 根 Cargo.toml
[workspace]
resolver = "2"
members = ["crates/*"]

[workspace.package]            # 共享元数据
version = "0.1.0"
edition = "2021"
license = "MIT OR Apache-2.0"

[workspace.dependencies]       # 统一版本,子 crate 用 { workspace = true }
serde = { version = "1", features = ["derive"] }
tokio = { version = "1", features = ["full"] }

[workspace.lints.clippy]       # 统一 lint(子 crate 加 [lints] workspace = true 继承)
all = "warn"
```

```toml
# crates/cli/Cargo.toml
[package]
name = "mycli"
version.workspace = true
edition.workspace = true
license.workspace = true

[dependencies]
core = { path = "../core" }
serde.workspace = true

[lints]
workspace = true
```

> 关联:`project-cargo.md`(feature/MSRV/发布)、`rules/_index.md` 的 `proj-*` 类。
