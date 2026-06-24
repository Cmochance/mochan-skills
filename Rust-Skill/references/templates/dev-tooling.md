# 开发工具配置模板

## `rust-toolchain.toml`(钉住工具链,团队一致)

```toml
[toolchain]
channel = "1.83.0"          # 或 "stable" / "nightly-2025-01-01"
components = ["rustfmt", "clippy", "rust-analyzer"]
targets = ["wasm32-unknown-unknown"]   # 按需
```

## `.cargo/config.toml`(项目级 cargo 配置)

```toml
# 别名,少打字
[alias]
b = "build"
t = "nextest run"           # 需装 cargo-nextest
c = "clippy --all-targets --all-features"
lint = "clippy --all-targets --all-features -- -D warnings"

# 更快的链接器(按平台装好对应 linker)
[target.x86_64-unknown-linux-gnu]
linker = "clang"
rustflags = ["-C", "link-arg=-fuse-ld=mold"]   # mold 链接器,大项目显著加速

# 交叉编译目标的 runner / linker 也放这
```

## `clippy.toml`(项目 lint 阈值)

```toml
# 例:认知复杂度阈值、允许的命名等
cognitive-complexity-threshold = 30
# avoid-breaking-exported-api = false
```

并在 crate 根用属性开 lint(或用 workspace lints,见 `cargo-project.md`):

```rust
#![warn(clippy::all, clippy::pedantic)]
#![allow(clippy::module_name_repetitions)]   // 个别 pedantic 太吵的显式关掉
```

## `justfile`(任务跑批,比 Makefile 顺手)

```makefile
# 装 just:cargo install just;跑:just check
default: check

check:
    cargo fmt --all -- --check
    cargo clippy --all-targets --all-features -- -D warnings
    cargo nextest run

fmt:
    cargo fmt --all

# 改了 unsafe 再跑
miri:
    cargo +nightly miri test

bench:
    cargo bench

# 清死依赖 + 安全审计
audit:
    cargo machete
    cargo deny check
```

## `bacon.toml`(后台自动 check/test,开发回路)

```toml
# 装:cargo install bacon;跑:bacon(默认 clippy);bacon test
default_job = "clippy"
[jobs.clippy]
command = ["cargo", "clippy", "--all-targets", "--all-features"]
need_stdout = false
```

> 关联:`toolchain-and-mcp.md`(工具目录)、`project-cargo.md`。
