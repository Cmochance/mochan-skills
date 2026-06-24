# Cargo / workspace / feature / build.rs / 条件编译 / 发布

Rust 的工程层。本域讲怎么组织多 crate、用 feature 切功能、写 `build.rs`、条件编译、发布到 crates.io、管 MSRV 与依赖卫生。

适用:建 workspace、设计 feature flags、写/精简 `build.rs`、`#[cfg(...)]` 条件编译、查/去重依赖、`cargo publish` 与 semver、声明 MSRV、清死依赖与安全审计。

---

## workspace(多 crate 工程)

- **何时用**:crate 多到该拆(库 + 多 bin、共享内部 crate)就建 workspace;小项目保持单 crate 扁平。→ [`proj-workspace-large`](rules/proj-workspace-large.md)、[`proj-flat-small`](rules/proj-flat-small.md)
- **结构**:根 `Cargo.toml` 写 `[workspace] members = [...]` + `resolver = "2"`(edition 2021+ 默认);所有成员**共享一个 `Cargo.lock`** 和 `target/`。
- **共享依赖版本**:`[workspace.dependencies]` 集中声明,成员用 `dep.workspace = true` 引用,避免版本漂移。→ [`proj-workspace-deps`](rules/proj-workspace-deps.md)
- **共享 lint**:`[workspace.lints]` 统一 lint 配置,成员 `[lints] workspace = true`。→ [`lint-workspace-lints`](rules/lint-workspace-lints.md)
- **lib/bin 拆分**:逻辑放 `lib.rs`(可测可复用),`main.rs`/`bin/` 只做薄壳。→ [`proj-lib-main-split`](rules/proj-lib-main-split.md)、[`proj-bin-dir`](rules/proj-bin-dir.md)

## feature flags(加性原则)

- **加性(additive)是铁律**:开启任一 feature 只能**增加**编译内容,不能移除/改变已有行为;否则 workspace 里多个 crate 共用依赖时,feature 求并集会互相破坏。避免互斥 feature。→ [`proj-feature-additive`](rules/proj-feature-additive.md)
- **`default` feature**:常用集合放 `default = [...]`;消费者可 `default-features = false` 精简,再按需 opt-in。
- **可选依赖**:`optional = true` 的依赖默认不编;feature 里用 `dep:cratename` 显式开,用 `cratename?/feat` 传递性 enable。
- **测全组合**:别只测 default;关键 feature 组合 + `--no-default-features` 都要 CI 跑(`cargo hack` 可帮你跑笛卡尔积)。
- serde 等大依赖设成 optional feature,见 [`serde-data.md`](serde-data.md) 的 `api-serde-optional`。

## build.rs(构建脚本)

- **用途**:生成代码(从 schema/protobuf)、编译链接 C 库、探测环境、注入编译期常量。
- **保持最小**:`build.rs` 拖慢每次构建且难调试;能用普通宏/`include!`/`const` 解决就别上。→ [`proj-build-rs-minimal`](rules/proj-build-rs-minimal.md)
- **增量正确性**:输出 `cargo:rerun-if-changed=path` / `cargo:rerun-if-env-changed=VAR` 精确声明依赖,否则要么不重跑(stale)要么每次重跑(慢)。
- 生成物写进 `OUT_DIR`(由 cargo 提供),源码里 `include!(concat!(env!("OUT_DIR"), "/gen.rs"))`。

## 条件编译 `#[cfg(...)]`

- 常见谓词:`#[cfg(target_os = "linux")]`、`#[cfg(feature = "x")]`、`#[cfg(test)]`、`#[cfg(unix)]`/`#[cfg(windows)]`、`#[cfg(debug_assertions)]`。
- `cfg!(...)` 宏在表达式里返回 bool(两分支都编译,只是运行时选);`#[cfg]` 属性直接增删代码。
- **windows-only 代码是 CI 盲区**:非 Windows runner 根本不编它,deps 升级 breaking 漏检——需在 Windows runner 上真编。
- 用 `[lints.rust] unexpected_cfgs` / `cargo:rustc-check-cfg` 让 rustc 检查 cfg 名拼写。→ [`lint-cfg-check`](rules/lint-cfg-check.md)

## 依赖卫生

- **查重复依赖**:`cargo tree -d` 列出同一 crate 的多版本共存(拖慢编译、撑大体积);能统一就统一。
- **临时改依赖**:`[patch.crates-io]` 指向 fork/本地路径调试上游 bug,不改 manifest 版本号。
- **清死依赖**:`cargo machete`(快,基于源码 `use` 扫描)/ `cargo udeps`(准,需 nightly,真编译看未用)找出 `Cargo.toml` 里没用到的依赖删掉。注意区分真阳性与 build-dep 误报。
- **安全审计**:`cargo audit`(RustSec 漏洞库)、`cargo deny`(漏洞 + license + 重复 + 来源策略,CI 集成)。

## 发布(crates.io)

- **版本走 semver**:`MAJOR.MINOR.PATCH`;破坏性变更升 major(0.x 下次版位算破坏性)。发布前 `cargo publish --dry-run` 验打包。
- **防意外破坏 API**:`cargo semver-checks` 对比上一版,自动检测 public API 的破坏性变更。
- **元数据齐全**:`description`/`license`/`repository`/`keywords`/`categories` 必填,否则 crates.io 页面残缺、搜不到。→ [`lint-cargo-metadata`](rules/lint-cargo-metadata.md)、[`doc-cargo-metadata`](rules/doc-cargo-metadata.md)、[`doc-crate-readme`](rules/doc-crate-readme.md)
- **撤回**:发错版本用 `cargo yank --version x.y.z`(已锁定者仍可用,新解析跳过);yank 不删代码、不可真删。

## MSRV(最低支持 Rust 版本)

- 在 `Cargo.toml` 声明 `rust-version = "1.74"`,cargo 会拒绝用更老 toolchain 编译并给清晰报错。→ [`proj-msrv-declare`](rules/proj-msrv-declare.md)
- 升 MSRV 视作半破坏性变更,记进 CHANGELOG;CI 加一个跑 MSRV toolchain 的 job 守住承诺。

## 典型坑

- **feature 非加性**:某 feature 关掉别的功能,被 workspace feature 并集坑——别人开了你没想到的组合就坏。
- **`build.rs` 漏 `rerun-if`**:改了输入不重新生成(stale 产物)或每次全量重跑(CI 慢)。
- **`cargo machete` 误删 build/传递依赖**:判据是源码出现 `use X::` 才算用了 X;build-dep 加 ignore 别删。
- **发布忘 `--dry-run`**:打包进了不该进的大文件,或漏了 `include`;`cargo publish` 不可逆(只能 yank)。
- **`cargo tree -d` 的重复无害化对待**:多版本常因生态滞后,不是都能消;能统一则统一,不能就接受。

## 关联知识库

- 规则:[`rules/_index.md`](rules/_index.md) 的 **工程(`proj-*`,14 条)** 类;cargo 元数据/lint `lint-cargo-metadata`/`doc-cargo-metadata`/`doc-crate-readme`/`lint-cfg-check`/`lint-workspace-lints`
- feature 与 serde 的 optional 依赖见 [`serde-data.md`](serde-data.md);模块/可见性组织见 `rules/` 的 `proj-mod-*`/`proj-pub-*`
- 工具(cargo 子命令、machete/udeps/audit/deny/semver-checks/hack)目录见 [`toolchain-and-mcp.md`](toolchain-and-mcp.md)

## 参考

- The Cargo Book(workspaces / features / build scripts / publishing / SemVer)——本域权威
- The Rust Reference:Conditional compilation(`cfg` 谓词全表)
- `cargo-machete`/`cargo-udeps`/`cargo-audit`/`cargo-deny`/`cargo-semver-checks`/`cargo-hack` 各自 README(用法以文档为准)
