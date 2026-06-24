# 工具链与 MCP — 目录 + 用前查证

写/验 Rust 用到的工具目录。**工具是否可用、版本、路径以本机为准**(见本机 `config.local.json`),别猜。缺的给官方安装命令让用户装,不自动改全局配置。

> 用前查证:`rustc -V` / `cargo -V` / `<tool> --version`。组件类用 `rustup component list --installed`。

## 核心工具链(rustup 管理)

| 工具 | 作用 | 装/查 |
|---|---|---|
| **rustup** | 工具链管理(stable/nightly/MSRV、target) | `rustup show` / `rustup update` |
| **cargo** | 构建/依赖/测试/发布 | 随工具链;`cargo -V` |
| **rustc** | 编译器;`--explain E0xxx` 看错误码 | `rustc -V` |
| **rustfmt** | 格式化 | `rustup component add rustfmt`;`cargo fmt` |
| **clippy** | lint(地道性/性能/正确性) | `rustup component add clippy`;`cargo clippy -- -D warnings` |
| **rust-analyzer** | LSP(补全/跳转/类型提示) | `rustup component add rust-analyzer` 或编辑器插件 |

## 高频生态工具(cargo install)

| 工具 | 作用 | 何时用 |
|---|---|---|
| **cargo-nextest** | 更快的测试 runner、更好输出 | 测试多/想要并行与重试。`cargo nextest run` |
| **cargo-expand** | 看宏展开后的代码 | 调 `macro_rules!`/derive/proc-macro。见 `macros.md` |
| **cargo-miri** | UB 检测解释器 | 改了 unsafe/FFI 后。`cargo miri test`。见 `unsafe-ffi.md` |
| **cargo-udeps** / **cargo-machete** | 找未用依赖 | 精简 `Cargo.toml`(machete 不需 nightly) |
| **cargo-edit** | `cargo add/rm/upgrade` | 改依赖(新 cargo 已内置 `add`) |
| **cargo-watch** / **bacon** | 文件变更自动 check/test | 开发回路;bacon 体验更佳 |
| **cargo-flamegraph** | 火焰图 profiling | 性能定位。见 `performance.md` |
| **criterion**(dev-dep) | 统计严谨的基准测试 | 性能结论要数据。见 `testing.md` |
| **hyperfine** | 命令级基准(CLI 整体耗时) | 比较二进制/命令耗时 |
| **cargo-deny** | 许可/安全公告/重复依赖审计 | CI 合规。`cargo deny check` |
| **cargo-audit** | RustSec 漏洞公告扫描 | 依赖安全 |
| **cargo-llvm-cov** / **tarpaulin** | 覆盖率 | 看测试覆盖 |
| **cargo-semver-checks** | 发布前 API 破坏性检查 | 库发版。见 `project-cargo.md` |
| **sccache** | 编译缓存 | 大项目/CI 加速 |
| **trybuild**(dev-dep) | 测"应该编译失败"的用例 | 宏/类型约束的负向测试 |

## 验证命令组合(交付前三连)

```bash
cargo fmt --all -- --check        # 格式
cargo clippy --all-targets --all-features -- -D warnings   # lint
cargo nextest run     # 或 cargo test   # 测试
# 改了 unsafe:
cargo +nightly miri test
# 性能改动:
cargo bench           # criterion;或 hyperfine 比命令
```

## MCP / LSP 集成(opt-in,默认不自动注册)

| 能力 | 怎么接 | 说明 |
|---|---|---|
| **rust-analyzer LSP** | 本会话已有 `LSP` 工具 / 编辑器内置 | 跳转定义、找引用、类型查询;比 grep 准。重构/找符号优先用 |
| **serena**(语义代码工具) | 本会话 `mcp__serena__*` | `find_symbol`/`find_referencing_symbols`/`get_symbols_overview` 做符号级导航与改写 |
| **codegraph** | 本会话 `mcp__codegraph__*` | 已索引代码图;"X 怎么工作/谁调用 X/改 X 影响啥"先用它,比 grep 省 |
| **docs.rs** | WebFetch `https://docs.rs/<crate>` | 查 crate API/版本/签名,**别凭记忆编签名** |
| **std 文档** | WebFetch `https://doc.rust-lang.org/std/` | 标准库 API |

> 启用任何 MCP 前用户确认并注册到对应客户端配置;端口/路径以本机实际为准。代码导航能用 LSP/serena/codegraph 就别用 grep 硬扫。

## 常用 `Cargo.toml` 配置片段

```toml
# 发布构建优化(体积/速度权衡见 performance.md / domain-wasm.md)
[profile.release]
opt-level = 3
lto = "thin"          # 或 "fat" 更激进
codegen-units = 1     # 更慢编译、更快运行
panic = "abort"       # 去掉 unwind,体积更小(注意:abort 后无法 catch_unwind)
strip = true          # 去符号

# 开发期也想要点优化(如跑测试慢)
[profile.dev.package."*"]
opt-level = 2         # 依赖优化、自己代码仍 debug

# MSRV 声明(最低支持 rustc 版本)
[package]
rust-version = "1.74"
```
