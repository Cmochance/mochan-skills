# 遍历目录

> 一句话:列目录、递归子树、按 glob 模式找文件。

## 依赖

```toml
walkdir = "2"   # 递归遍历,处理符号链接/深度限制
glob = "0.3"    # shell 风格通配
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use std::fs;
use std::path::Path;
use anyhow::Result;
use walkdir::WalkDir;

fn list_one_level(dir: &Path) -> Result<()> {
    // 单层:fs::read_dir,每项是 io::Result<DirEntry>
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let ty = entry.file_type()?;          // 比 metadata 便宜,不跟随符号链接
        let kind = if ty.is_dir() { "dir" } else { "file" };
        println!("{kind}: {}", entry.path().display());
    }
    Ok(())
}

fn walk_recursive(root: &Path) -> Result<usize> {
    let mut rust_files = 0;
    // 递归:WalkDir 帮你处理深度/错误,别手写递归栈
    for entry in WalkDir::new(root).max_depth(10) {
        let entry = entry?;                    // 遇到无权限目录等错误这里冒出来
        if entry.file_type().is_file()
            && entry.path().extension().is_some_and(|e| e == "rs")
        {
            rust_files += 1;
        }
    }
    Ok(rust_files)
}

fn find_by_glob() -> Result<()> {
    // glob 模式:** 跨目录,* 单层
    for path in glob::glob("src/**/*.rs")? {
        println!("{}", path?.display());       // 每项 Result<PathBuf, GlobError>
    }
    Ok(())
}
```

## 要点 / 坑

- `fs::read_dir` **不递归**且顺序**不保证**;要稳定输出自己收集后 `sort`。
- `entry.file_type()` 比 `entry.metadata()` 快,且默认不跟随符号链接;需要跟随用 `metadata()`。
- `WalkDir` 默认跟随符号链接关闭,`follow_links(true)` 打开时小心**环路**(它会检测但有代价)。
- `glob` 的 `**` 只在路径分隔处匹配;模式语法和 shell 略有差异,不确定查 docs.rs。
- 大目录树用 WalkDir 的迭代器**惰性**特性,边遍历边处理,别先 `collect` 全部。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 路径处理:[`path-handling`](path-handling.md)
- 规则:[`perf-iter-lazy`](../rules/perf-iter-lazy.md)、[`err-question-mark`](../rules/err-question-mark.md)
