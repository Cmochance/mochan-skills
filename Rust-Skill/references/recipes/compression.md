# 压缩与解压

> 一句话:`flate2` 做 gzip/deflate 字节流,`zip` 读写 zip 归档。

## 依赖

```toml
flate2 = "1"   # gzip / zlib / deflate,基于 miniz_oxide 纯 Rust 后端
zip = "2"      # zip 归档读写;API 跨版本有变动,以 docs.rs 为准
```

## 做法

```rust
use std::io::{Read, Write};
use flate2::Compression;
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use anyhow::Result;

// gzip 压缩一段字节
fn gzip_bytes(data: &[u8]) -> Result<Vec<u8>> {
    let mut enc = GzEncoder::new(Vec::new(), Compression::default());
    enc.write_all(data)?;
    let compressed = enc.finish()?;        // finish 刷出尾部,别忘
    Ok(compressed)
}

// gzip 解压
fn gunzip_bytes(gz: &[u8]) -> Result<Vec<u8>> {
    let mut dec = GzDecoder::new(gz);
    let mut out = Vec::new();
    dec.read_to_end(&mut out)?;
    Ok(out)
}

// 流式压缩文件 -> .gz(包 Writer/Reader,不全量进内存)
fn gzip_file(src: &str, dst: &str) -> Result<()> {
    let mut input = std::fs::File::open(src)?;
    let output = std::fs::File::create(dst)?;
    let mut enc = GzEncoder::new(output, Compression::default());
    std::io::copy(&mut input, &mut enc)?;  // copy 走 8KB 缓冲,流式
    enc.finish()?;
    Ok(())
}

// 读 zip 归档中的某个文件
fn read_from_zip(zip_path: &str, name: &str) -> Result<String> {
    let file = std::fs::File::open(zip_path)?;
    let mut archive = zip::ZipArchive::new(file)?;
    let mut entry = archive.by_name(name)?;   // 按内部路径取条目
    let mut s = String::new();
    entry.read_to_string(&mut s)?;
    Ok(s)
}
```

## 要点 / 坑

- `GzEncoder` **必须 `finish()`**(或确保 drop)才会写出压缩尾部;漏了得到的是**截断/损坏**的 gz。
- 大文件用 `std::io::copy` + Encoder/Decoder **流式**处理,别 `read_to_end` 整个进内存再压。
- `flate2` 默认纯 Rust 后端(`miniz_oxide`),可换 `zlib`/`zlib-ng` feature 提速(需 C 工具链),按需查 docs.rs。
- `zip` crate 跨版本 **API 变动较多**(`ZipWriter::start_file` 签名、压缩方法枚举等);照本配方前核对版本。
- 解压**不可信** zip 警惕 zip-slip(条目名含 `../` 写出目录外)和 zip-bomb(超高压缩比);校验 `entry.name()`、限制解压总量。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 读写文件:[`read-write-files`](read-write-files.md)、哈希校验:[`hashing-encoding`](hashing-encoding.md)
- 规则:[`perf-io-buffering`](../rules/perf-io-buffering.md)、[`err-question-mark`](../rules/err-question-mark.md)
