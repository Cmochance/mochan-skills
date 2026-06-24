# 读写文件

> 一句话:整体/逐行读、缓冲写,把文件 IO 写地道。

## 依赖

```toml
# 全是 std,无需额外依赖
anyhow = "1"   # 应用层错误传播,版本以 docs.rs 最新为准
```

## 做法

```rust
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write};
use anyhow::{Context, Result};

fn rw_demo(path: &str, out: &str) -> Result<()> {
    // 1) 整体读成 String —— 小文件最省事
    let text = fs::read_to_string(path)
        .with_context(|| format!("读取 {path} 失败"))?;
    println!("共 {} 字节", text.len());

    // 2) 逐行读 —— 大文件别一次性塞进内存,BufReader 减少 syscall
    let file = File::open(path).with_context(|| format!("打开 {path}"))?;
    let reader = BufReader::new(file);
    let mut non_empty = 0usize;
    for line in reader.lines() {
        let line = line?;            // 每行是 io::Result<String>
        if !line.trim().is_empty() {
            non_empty += 1;
        }
    }
    println!("非空行 {non_empty}");

    // 3) 整体写 —— fs::write 覆盖写,自动创建/截断
    fs::write(out, b"hello\nworld\n").with_context(|| format!("写 {out}"))?;

    // 4) 缓冲写 —— 多次小写入务必包 BufWriter,否则每次 write 一个 syscall
    let f = File::create(out)?;
    let mut w = BufWriter::new(f);
    for i in 0..1000 {
        writeln!(w, "line {i}")?;    // writeln! 走 Write trait,不分配
    }
    w.flush()?;                      // drop 也会 flush,但 flush 的错误会被吞,显式 flush 才能 ? 传播
    Ok(())
}
```

## 要点 / 坑

- `fs::read_to_string` 要求是合法 UTF-8;二进制用 `fs::read`(返回 `Vec<u8>`)。
- `BufReader::lines()` 会**剥掉换行符**且每行**分配新 `String`**;极致性能用 `read_line(&mut buf)` 复用缓冲。
- `BufWriter` 的 `Drop` 会 flush 但**忽略错误**——关心写入成败必须手动 `flush()?`。
- `fs::write` 覆盖而非追加;追加用 `OpenOptions::new().append(true).open(path)`。
- 路径拼接别用字符串 `+`,用 `Path`/`PathBuf`,见关联。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 路径处理:[`path-handling`](path-handling.md)
- 规则:[`perf-io-buffering`](../rules/perf-io-buffering.md)、[`err-context-chain`](../rules/err-context-chain.md)
