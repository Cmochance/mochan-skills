# 临时文件与目录

> 一句话:`tempfile` 创建临时文件/目录,作用域结束自动清理。

## 依赖

```toml
tempfile = "3"
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use std::io::{Read, Seek, SeekFrom, Write};
use tempfile::{tempdir, NamedTempFile};
use anyhow::Result;

// 匿名临时文件:无路径,drop 即删,适合纯临时缓冲
fn anon_temp() -> Result<()> {
    let mut f = tempfile::tempfile()?;     // 进程退出/drop 自动消失
    writeln!(f, "scratch data")?;
    f.seek(SeekFrom::Start(0))?;           // 写完想读要先 rewind
    let mut s = String::new();
    f.read_to_string(&mut s)?;
    Ok(())
}

// 具名临时文件:有路径,可交给别的进程/API,仍 drop 自动删
fn named_temp() -> Result<()> {
    let mut f = NamedTempFile::new()?;
    write!(f, "config = true")?;
    let path = f.path().to_owned();        // 把路径传给需要文件名的 API
    println!("临时文件在 {}", path.display());
    // f 在此 drop -> 文件删除;若想保留改名用 f.persist("final.toml")?
    Ok(())
}

// 临时目录:整棵子树 drop 时递归删除,测试里隔离文件操作最常用
fn temp_dir() -> Result<()> {
    let dir = tempdir()?;                  // 唯一命名,自动清理
    let file_path = dir.path().join("a.txt");
    std::fs::write(&file_path, b"hi")?;
    // ... 在 dir 里随便造文件 ...
    Ok(())                                 // dir drop -> 整个目录及内容删除
}
```

## 要点 / 坑

- 清理靠 **`Drop`**:`TempDir`/`NamedTempFile` 的句柄**别提前 drop 或丢弃返回值**,否则文件当场就被删了(常见错误:`let _ = tempdir()?`)。
- 进程被 `SIGKILL` 等强杀时 Drop 不跑,临时文件可能残留;系统重启或 `/tmp` 清理兜底。
- 想保留结果用 `NamedTempFile::persist(path)`(原子 rename,跨设备会失败需同盘)或 `TempDir::keep()`(旧版叫 `into_path`,查 docs.rs)。
- 把临时文件路径给外部进程时用 `NamedTempFile`(匿名 `tempfile()` 在多数平台**没有可用路径**)。
- 测试中用 `tempdir()` 做隔离沙箱,各测试互不污染,比写死 `/tmp/test` 安全。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 读写文件:[`read-write-files`](read-write-files.md)、测试夹具:[`../testing.md`](../testing.md)
- 规则:[`test-fixture-raii`](../rules/test-fixture-raii.md)、[`mem-drop-order`](../rules/mem-drop-order.md)
