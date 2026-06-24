# 处理 CSV

> 一句话:`csv` crate 配合 serde 读到 struct、写出、自定义分隔符、大文件流式。

## 依赖

```toml
csv = "1"
serde = { version = "1", features = ["derive"] }
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use serde::{Deserialize, Serialize};
use anyhow::Result;

#[derive(Debug, Deserialize, Serialize)]
struct Record {
    name: String,
    #[serde(rename = "age")]
    age: u32,
    city: String,
}

// 读:从文件路径流式反序列化到 struct,逐行,不全量进内存
fn read_records(path: &str) -> Result<Vec<Record>> {
    let mut rdr = csv::Reader::from_path(path)?;   // 默认有表头,用表头名映射字段
    let mut out = Vec::new();
    for result in rdr.deserialize() {              // 迭代器,惰性
        let rec: Record = result?;                 // 每行一个 Result
        out.push(rec);
    }
    Ok(out)
}

// 写:序列化 struct,自动写表头
fn write_records(path: &str, recs: &[Record]) -> Result<()> {
    let mut wtr = csv::Writer::from_path(path)?;
    for rec in recs {
        wtr.serialize(rec)?;                       // 第一条自动写 header
    }
    wtr.flush()?;                                  // 必须 flush,内部有缓冲
    Ok(())
}

// 自定义分隔符(TSV)/ 无表头
fn read_tsv_headerless(path: &str) -> Result<()> {
    let mut rdr = csv::ReaderBuilder::new()
        .delimiter(b'\t')
        .has_headers(false)
        .from_path(path)?;
    for result in rdr.records() {                  // StringRecord:无 struct 时按下标取
        let rec = result?;
        let first = rec.get(0).unwrap_or_default();
        println!("col0 = {first}");
    }
    Ok(())
}
```

## 要点 / 坑

- `deserialize()` **流式惰性**,大文件别先 `collect` 再处理;边读边算省内存。
- 默认**有表头**且按表头名匹配字段;无表头务必 `has_headers(false)`,否则第一行数据被当 header 丢掉。
- 字段类型不匹配(如 `age` 列是 `"abc"`)在该行 `result?` 处报错,带行号,定位方便。
- 写入有缓冲,**结束必须 `flush()`**(或让 `Writer` drop,但 drop 吞错误);否则尾部数据丢失。
- 含逗号/换行/引号的字段 `csv` 自动加引号转义,别自己拼字符串造 CSV。

## 关联

- 概览:[`../serde-data.md`](../serde-data.md)
- 读写文件:[`read-write-files`](read-write-files.md)
- 规则:[`perf-iter-lazy`](../rules/perf-iter-lazy.md)、[`serde-rename-all`](../rules/serde-rename-all.md)
