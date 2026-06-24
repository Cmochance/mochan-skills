# 测试 / 基准 模板

## 单元测试(同文件 `#[cfg(test)]`)

```rust
pub fn add(a: i64, b: i64) -> i64 { a + b }

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn adds_positive() {
        assert_eq!(add(2, 3), 5);
    }

    #[test]
    fn handles_negative() {
        assert_eq!(add(-2, 3), 1);
    }

    #[test]
    #[should_panic(expected = "divide by zero")]
    fn panics_on_zero() { /* ... */ }
}
```

## 集成测试(`tests/` 目录,黑盒测 public API)

```rust
// tests/api.rs — 每个文件是独立 crate,只能用 pub API
use mylib::Thing;

#[test]
fn public_flow_works() {
    let t = Thing::new();
    assert!(t.is_valid());
}
```

```rust
// tests/cli.rs — 测二进制(assert_cmd)
use assert_cmd::Command;

#[test]
fn prints_help() {
    Command::cargo_bin("myapp").unwrap()
        .arg("--help")
        .assert()
        .success()
        .stdout(predicates::str::contains("Usage"));
}
```

## Property-based(proptest)

```rust
proptest::proptest! {
    #[test]
    fn roundtrip(s in ".*") {
        let encoded = encode(&s);
        let decoded = decode(&encoded).unwrap();
        proptest::prop_assert_eq!(decoded, s);   // 对任意输入往返一致
    }
}
```

## 基准(criterion,统计严谨——别用 `Instant` 手搓)

```toml
# Cargo.toml
[dev-dependencies]
criterion = { version = "0.5", features = ["html_reports"] }

[[bench]]
name = "my_bench"
harness = false
```

```rust
// benches/my_bench.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion};

fn bench_add(c: &mut Criterion) {
    c.bench_function("add 2+3", |b| {
        b.iter(|| mylib::add(black_box(2), black_box(3)))
    });
}

criterion_group!(benches, bench_add);
criterion_main!(benches);
```
跑:`cargo bench`;对比基线由 criterion 自动记录。

## 编译失败用例(trybuild)——测宏/类型约束的负向行为

```rust
// tests/compile_fail.rs
#[test]
fn ui() {
    trybuild::TestCases::new().compile_fail("tests/ui/*.rs");
}
```

> 关联:`testing.md`、`rules/_index.md` 的 `test-*` 类、`macros.md`(宏测试)。
