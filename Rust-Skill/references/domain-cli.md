# CLI 工具(clap / 配置 / 输出 / 退出码)

用 Rust 写命令行程序:参数解析、子命令、配置层叠、彩色/进度输出、交互、错误与退出码。参数解析默认 **clap**(derive 风格)。

适用:定义参数/子命令、参数校验与默认值、读环境变量/配置文件、彩色或进度条输出、交互式提示、给出合适退出码、为 CLI 写测试、生成 shell 补全。

---

## 参数解析:clap(derive vs builder)

clap 是事实标准,两种 API:

- **derive(推荐默认)**:`#[derive(Parser)]` 标在 struct 上,字段即参数;`#[command(...)]` 配 name/version/about,`#[arg(...)]` 配单个参数(short/long/default/env)。声明式、可读、改起来快。
- **builder**:运行时用 `Command::new().arg(Arg::new(...))` 拼。需要**运行时动态**决定参数集(插件/根据配置生成)时才用,否则 derive 更省事。

子命令用 enum + `#[derive(Subcommand)]`,在主 struct 里放一个 `#[command(subcommand)]` 字段:

```rust
#[derive(Parser)]
#[command(version, about)]
struct Cli { #[command(subcommand)] cmd: Cmd }

#[derive(Subcommand)]
enum Cmd { Add { name: String }, Remove { #[arg(long)] force: bool } }
```

参数细节(都在 `#[arg(...)]`):`default_value_t`(类型化默认)、`env = "VAR"`(回退环境变量)、`value_enum`(限定枚举值)、`value_parser`(自定义解析/校验)、`required`/`conflicts_with`/`requires`(约束关系)。校验失败 clap 自己打印 usage 并以非零码退出,不用你处理。

## 配置层叠(优先级)

CLI 配置通常多来源叠加,典型优先级 **命令行参数 > 环境变量 > 配置文件 > 内置默认**:

- clap 的 `#[arg(env = ...)]` 已天然覆盖「参数 > env」两层。
- 文件配置用 `config` 或 `figment`(支持 toml/yaml/json/env 多源合并),反序列化进 serde struct(见 [`serde-data.md`](serde-data.md))。
- 合并策略:先加载文件 → env 覆盖 → clap 解析的命令行参数最后覆盖(`Option<T>` 字段为 `Some` 才覆盖)。

别把所有东西塞进 50 个 `--flag`;复杂配置走文件 + 少量高频参数走命令行。

## 输出:彩色 / 进度 / 表格

- **彩色**:`owo-colors`(零依赖、`.green()` 链式)或 `anstyle`(clap 自家配色体系)。务必尊重 `NO_COLOR` 环境变量和「非 TTY 时关色」(`std::io::IsTerminal`),否则管道里全是转义码。
- **进度条/spinner**:`indicatif`(`ProgressBar`/`MultiProgress`)。长任务才用,别给秒级任务加。
- **表格**:`comfy-table` / `tabled`。
- **结构化输出**:支持 `--json` 时直接 serde 序列化到 stdout,方便下游脚本消费。人读输出走 stderr 或带色,机器读输出走 stdout 纯文本。

## 错误与退出码

CLI 的错误处理用 **anyhow**(应用层,不需要给调用方匹配的错误类型,见 [`rules/err-anyhow-app.md`](rules/err-anyhow-app.md)):`fn main() -> anyhow::Result<()>`,内部 `?` 一路传播,`anyhow` 在 main 返回 Err 时打印错误链(含 `.context(...)` 累加的上下文,见 [`rules/err-context-chain.md`](rules/err-context-chain.md))并退出码 1。

要精确控制退出码,返回 `std::process::ExitCode`:

```rust
fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => { eprintln!("error: {e:#}"); ExitCode::from(2) }
    }
}
```

原则:**别 `panic!`/`unwrap()` 当退出**(panic 打丑陋的 backtrace + 退 101,对用户不友好);预期错误走 `Result` + 清晰 stderr 消息 + 合适退出码(约定:0 成功、1 通用错误、2 用法错误)。`unwrap`/`expect` 只用于「真 bug」断言(见 [`rules/err-expect-bugs-only.md`](rules/err-expect-bugs-only.md))。

## 交互

需要提示输入/确认/选择时用 `dialoguer`(`Input`/`Confirm`/`Select`/`Password`)。但**交互要可跳过**:非 TTY(管道/CI)或带了 `--yes`/`--non-interactive` 时不应卡住等输入,改用参数默认或直接失败。

## 测试 CLI

- **assert_cmd**:在测试里跑编译出的二进制,断言 stdout/stderr/退出码。配 `predicates` 做输出匹配。
- **trycmd / snapbox**:用 `.trycmd`/`.md` 文件做声明式快照测试(命令 + 期望输出),适合大量 CLI 行为回归。
- clap 本身的解析逻辑可单测:对 `Cli::parse_from(["prog", "--flag"])` 断言解析结果,不必跑子进程。

## 补全与 man

- **shell 补全**:`clap_complete` 从 `Command` 生成 bash/zsh/fish/powershell 补全脚本(常做成隐藏子命令 `completions <shell>` 或 build.rs 生成)。
- **man page**:`clap_mangen` 生成 roff man page。

## 典型坑

- **panic 当错误退出**:`unwrap()` 失败给用户一坨 backtrace + 退 101。预期错误用 `Result` + 友好消息。
- **彩色码污染管道**:没判 TTY/`NO_COLOR`,重定向到文件全是 `\x1b[...`。用判 TTY 的库或显式检查。
- **交互卡死 CI**:`dialoguer` 在无 TTY 环境阻塞。提供 `--yes` 类开关 + 检测非交互。
- **builder 写成裹脚布**:静态参数集硬用 builder API,几百行样板。能 derive 就 derive。
- **退出码乱**:全靠 `process::exit(1)` 散落各处,绕过析构。用 `main -> ExitCode`/`Result` 收口,让 RAII 正常清理。
- **配置覆盖顺序搞反**:env 覆盖了本应最高优先级的命令行参数。明确「default < file < env < arg」并测它。

## 关联知识库

- 概览:[`error-handling.md`](error-handling.md)(anyhow vs thiserror、`?`、context)、[`project-cargo.md`](project-cargo.md)(bin/lib 拆分、`proj-lib-main-split`、feature)、[`serde-data.md`](serde-data.md)(配置文件反序列化)
- 规则:`rules/_index.md` 的 `err-*`(尤其 [`rules/err-anyhow-app.md`](rules/err-anyhow-app.md)、[`rules/err-expect-bugs-only.md`](rules/err-expect-bugs-only.md)、[`rules/err-context-chain.md`](rules/err-context-chain.md))、`proj-*`(bin/lib 组织);参数解析/枚举值配 [`rules/conv-fromstr-parsing.md`](rules/conv-fromstr-parsing.md)
- 模板:见 `templates/`(Cargo 项目骨架、error 类型),CLI 入口可直接套

## 参考

- clap 文档(docs.rs/clap,看 derive 教程与 `#[arg]`/`#[command]` 全属性);clap_complete / clap_mangen
- anyhow / `std::process::ExitCode` 标准库文档
- owo-colors / anstyle / indicatif / dialoguer / config / figment 各自 README
- assert_cmd / trycmd / snapbox 测试库文档;版本/API 以 docs.rs 当前版本为准
