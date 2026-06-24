# 执行外部命令(std::process::Command)

> 一句话:用 `Command` 调外部程序、捕获 stdout/stderr、检查退出码、串管道。

## 依赖
```toml
# 全部来自标准库
```

## 做法
```rust
use std::process::{Command, Stdio};
use std::io::Write;

fn main() -> std::io::Result<()> {
    // —— 1. 一把跑完、捕获输出 ——
    let out = Command::new("git")
        .args(["rev-parse", "--short", "HEAD"])
        .output()?; // 阻塞到结束,捕获 stdout+stderr+status
    if out.status.success() {
        let sha = String::from_utf8_lossy(&out.stdout);
        println!("HEAD = {}", sha.trim());
    } else {
        eprintln!("git failed: {}", String::from_utf8_lossy(&out.stderr));
        std::process::exit(out.status.code().unwrap_or(1));
    }

    // —— 2. 写 stdin + 读 stdout(管道)——
    let mut child = Command::new("grep")
        .arg("foo")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()?;
    child.stdin.take().unwrap().write_all(b"foo\nbar\nfoobar\n")?; // 写完 drop → 关 stdin
    let out = child.wait_with_output()?; // 等结束并收 stdout
    print!("{}", String::from_utf8_lossy(&out.stdout)); // foo / foobar

    // —— 3. 只关心成功与否(status())——
    let ok = Command::new("test").args(["-f", "Cargo.toml"]).status()?.success();
    println!("Cargo.toml exists: {ok}");
    Ok(())
}
```

异步版用 `tokio::process::Command`(API 几乎相同,方法加 `.await`),适合在 async 服务里调外部命令而不堵 runtime。

## 要点 / 坑
- `output()` 阻塞到结束并捕获全部输出;`status()` 不捕获、继承父进程的 stdio;`spawn()` 拿 `Child` 做交互/管道。
- **退出码**:`status.success()` 判成败,`status.code()` 取码(被信号杀死返 `None`)。
- 写 stdin 后**要 drop/关闭它**(`take()` + 写完离开作用域),否则子进程的读会一直等不到 EOF 而卡死。
- `Command::new("...")` 不走 shell,**不做** glob/管道/变量展开;要 shell 特性显式 `sh -c "..."`(注意注入风险)。

## 关联
- 概览:[`../domain-systems.md`](../domain-systems.md)
- 规则:[`err-question-mark`](../rules/err-question-mark.md)
