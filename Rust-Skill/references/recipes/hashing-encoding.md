# 哈希与编码

> 一句话:`sha2`/`blake3` 算哈希,`base64`(0.22 Engine API)与 `hex` 编解码。

## 依赖

```toml
sha2 = "0.10"     # SHA-256/512,RustCrypto 系列,统一 Digest trait
blake3 = "1"      # 更快的现代哈希,带便捷顶层 API
base64 = "0.22"   # 注:0.22 改用 Engine API,老教程的 encode/decode 顶层函数已弃用
hex = "0.4"
# 版本以 docs.rs 最新为准
```

## 做法

```rust
use sha2::{Sha256, Digest};
use base64::Engine;                          // 0.22 必须 use 这个 trait
use base64::engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD};
use anyhow::Result;

// SHA-256:RustCrypto 的 update/finalize 流式接口
fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);                     // 可多次 update 累积大数据
    let digest = hasher.finalize();          // GenericArray<u8, 32>
    hex::encode(digest)                       // 转 64 字符十六进制串
}

// blake3:顶层便捷函数,比 SHA-2 快很多
fn blake3_hex(data: &[u8]) -> String {
    let hash = blake3::hash(data);           // 一行搞定
    hash.to_hex().to_string()                // blake3 自带 to_hex
}

// base64:0.22 用 Engine,选标准还是 URL-safe 看用途
fn base64_roundtrip(data: &[u8]) -> Result<()> {
    let encoded = STANDARD.encode(data);               // 含 +/= ,适合非 URL 场景
    let url = URL_SAFE_NO_PAD.encode(data);            // -_ 无填充,适合放 URL/JWT
    let decoded = STANDARD.decode(&encoded)?;          // 解码失败返回 Err
    assert_eq!(decoded, data);
    println!("{encoded} | {url}");
    Ok(())
}

// hex:字节 <-> 十六进制
fn hex_roundtrip(data: &[u8]) -> Result<()> {
    let s = hex::encode(data);
    let back = hex::decode(&s)?;             // 奇数长度/非法字符报错
    assert_eq!(back, data);
    Ok(())
}
```

## 要点 / 坑

- **`base64` 0.22 改了 API**:不再有顶层 `encode/decode`,要 `use base64::Engine` + 选 engine(`STANDARD` / `URL_SAFE_NO_PAD`)。照老教程会编不过。
- 选对 base64 字母表:URL/JWT/文件名用 `URL_SAFE_NO_PAD`(`-_` 无 `=` 填充),普通用 `STANDARD`;两端必须一致否则解不回。
- 哈希要**密码存储**别用 SHA-256/blake3(太快易暴破);用 `argon2`/`bcrypt` 加盐慢哈希(查 docs.rs)。
- RustCrypto `Digest` 是统一 trait:换 `Sha512`/`Sha3_256` 只改类型,`update`/`finalize` 接口不变。
- 校验哈希/MAC 相等用**常量时间比较**(`subtle` crate 的 `ct_eq`),普通 `==` 有时序侧信道风险。

## 关联

- 概览:[`../domain-systems.md`](../domain-systems.md)
- 压缩:[`compression`](compression.md)、字符串:[`string-manipulation`](string-manipulation.md)
- 规则:[`api-from-not-into`](../rules/api-from-not-into.md)、[`err-question-mark`](../rules/err-question-mark.md)
