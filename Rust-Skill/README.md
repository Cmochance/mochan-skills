# Rust-Skill

Rust 编程的统一**方法论 + 主题路由 + 三层知识库**。把 Rust 任务变成「先分类路由 → 看准则与用例 → 写出惯用代码 → cargo 验证」的可重复工作流。

/ Unified **methodology + topic routing + three-tier knowledge base** for Rust programming. Turns a Rust task into a repeatable flow: route by topic → consult rules & examples → write idiomatic code → verify with cargo.

## 结构 / Structure

```
Rust-Skill/
├── SKILL.md                  # 路由入口:核心姿态 / 工作方式 / 路由速查 / 完成清单
├── config.example.json       # 工具链/MCP 配置样例(复制为 config.local.json 填本机值)
├── NOTICE                    # 第三方来源与许可归属
└── references/
    ├── routing.md            # 三维路由矩阵(问题层级 / 用户意图 / crate·工具链)
    ├── error-codes.md        # rustc 错误码 E0xxx → 根因域速查
    ├── toolchain-and-mcp.md  # cargo/clippy/miri/nextest/expand + LSP/MCP
    ├── <概览子域>.md          # 所有权/类型trait/错误/并发async/unsafe/宏 +
    │                         #   api/性能/测试/cargo/可观测/serde +
    │                         #   web/cli/embedded/wasm/systems
    ├── rules/                # 265 条习惯/反模式规则(26 类)+ _index.md
    ├── recipes/              # 任务配方("怎么用 Rust 做 X")+ _index.md
    ├── examples/             # 概念可跑用例 + _index.md
    ├── deep/                 # 设计模式书高保真移植(MPL-2.0)+ _index.md
    └── templates/            # Cargo 项目 / error 类型 / bench / CI 模板
```

## 用法 / Usage

1. 触发:任务涉及写/重构 Rust、借用检查器报错、async/trait/unsafe/宏、Cargo 工程、性能/测试时,本 skill 自动相关。
2. 先按 `SKILL.md` 的路由速查或 `references/routing.md` 定位子域。
3. 顺着子域概览链到 `rules/`(地道写法 + 反模式)、`recipes/`(任务配方)、`examples/`(概念示例)。
4. 写完按 `SKILL.md` 完成清单自检:`cargo fmt && clippy && test` 三连。

## 设计取向 / Design

- **惯用优于聪明**:优先生态既有惯用法,不为绕借用检查器堆 `clone`/`unwrap`/`Box<dyn>`。
- **类型表达约束**:能编译期拦的错不留到运行期。
- **不确定就验证**:签名/版本/宏展开查 docs.rs、`cargo expand`,不凭记忆编。
- **router-first**:先路由再写,知识按需加载,不预载全部。

## 来源 / Credits

架构思路借鉴 `actionbook/rust-skills`(仅结构,无文字拷贝);规则库逐字移植
`leonardomso/rust-skills`(MIT);配方/用例/深度层借鉴 Rust Cookbook(CC0)、
Rust by Example(MIT/Apache)、Rust Design Patterns(MPL-2.0)。完整归属见 [`NOTICE`](NOTICE)。
