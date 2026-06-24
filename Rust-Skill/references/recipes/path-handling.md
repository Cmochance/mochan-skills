# 路径处理

> 一句话:用 `Path`/`PathBuf` 拼接、取扩展名/文件名、跨平台,别拼字符串。

## 依赖

```toml
# 全是 std::path,无需依赖
```

## 做法

```rust
use std::path::{Path, PathBuf};

fn path_demo(base: &Path) {
    // join:自动用平台分隔符,别手拼 "a/" + "b"
    let cfg: PathBuf = base.join("config").join("app.toml");

    // 取各部分(都返回 Option,因为路径可能没有该部分)
    let ext = cfg.extension().and_then(|e| e.to_str());   // Some("toml")
    let stem = cfg.file_stem().and_then(|s| s.to_str());  // Some("app")(不含扩展名)
    let name = cfg.file_name().and_then(|s| s.to_str());  // Some("app.toml")
    let parent = cfg.parent();                            // Some(.../config)
    println!("{ext:?} {stem:?} {name:?} {parent:?}");

    // 改扩展名(返回 bool 表示是否成功)
    let mut bak = cfg.clone();
    bak.set_extension("toml.bak");

    // 判断绝对/相对、拼出绝对路径
    if cfg.is_relative() {
        // current_dir() 返回 io::Result,这里略
    }

    // 跨平台:用 components() 迭代而非 split('/');用 MAIN_SEPARATOR 而非字面 '/'
    for comp in cfg.components() {
        // comp 是 Component 枚举:RootDir / Normal(os_str) / ParentDir ...
        let _ = comp;
    }
}

// 规范化:fs::canonicalize 解析 .. 和符号链接,但要求路径真实存在且返回 io::Result
fn real_path(p: &Path) -> std::io::Result<PathBuf> {
    std::fs::canonicalize(p)
}
```

## 要点 / 坑

- 路径分量**不保证是合法 UTF-8**(`OsStr`);要 `&str` 用 `.to_str()`(返回 `Option`)或 `.to_string_lossy()`。
- `join` 一个**绝对路径**会**丢弃** base:`Path::new("/a").join("/b")` == `/b`,小心来自用户的绝对输入。
- `extension()` 对 `.gitignore` 返回 `None`(无 stem 的纯隐藏文件);对 `a.tar.gz` 只返回 `gz`。
- `canonicalize` 要求文件**存在**且会解析符号链接;只想去掉 `..` 而不触盘用 `path-clean` 等 crate(查 docs.rs)。
- 跨平台别 hardcode `/`;比较路径用 `Path` 的方法而非字符串比较(大小写/分隔符差异)。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 读写文件:[`read-write-files`](read-write-files.md)
- 规则:[`type-option-nullable`](../rules/type-option-nullable.md)、[`anti-string-for-str`](../rules/anti-string-for-str.md)
