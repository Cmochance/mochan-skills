# GitHub Actions CI 模板

放 `.github/workflows/ci.yml`。覆盖格式、lint、测试,并在 stable + MSRV 两条工具链上跑。

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

# 同一分支新 push 取消旧 run,省额度
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

env:
  CARGO_TERM_COLOR: always
  RUSTFLAGS: "-D warnings"     # 把警告当错误,CI 兜底

jobs:
  fmt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with: { components: rustfmt }
      - run: cargo fmt --all -- --check

  clippy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with: { components: clippy }
      - uses: Swatinem/rust-cache@v2      # 缓存依赖编译,大幅提速
      - run: cargo clippy --all-targets --all-features

  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        rust: [stable]
        include:
          - os: ubuntu-latest
            rust: "1.74"     # MSRV:与 Cargo.toml 的 rust-version 一致
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@master
        with: { toolchain: "${{ matrix.rust }}" }
      - uses: Swatinem/rust-cache@v2
      - run: cargo test --all-features --workspace
```

可选加固 job(按需启用):

```yaml
  # 依赖安全/许可审计
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - run: cargo install cargo-deny --locked
      - run: cargo deny check

  # UB 检测(改了 unsafe 时)
  miri:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@nightly
        with: { components: miri }
      - run: cargo miri test
```

要点:
- `Swatinem/rust-cache` 几乎必加,否则每次全量编译依赖。
- MSRV 用 `include` 单独跑一条,别让整个 matrix 都装老工具链。
- `dtolnay/rust-toolchain` 比官方 action 轻、快。
- 关联:`project-cargo.md`、`toolchain-and-mcp.md`。
