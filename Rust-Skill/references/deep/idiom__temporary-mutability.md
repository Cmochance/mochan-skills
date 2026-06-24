> **来源**:本文逐字移植自《Rust Design Patterns》(https://github.com/rust-unofficial/patterns) 的 `src/idioms/temporary-mutability.md`,许可 **MPL-2.0**。
> 本文件依 MPL-2.0 继续以该许可开放;移植仅添加了本头部说明,正文未改。文中跨章节链接指向上游原书。
> 完整许可见仓库根 [`NOTICE`](../../NOTICE)。

---

# Temporary mutability

## Description

Often it is necessary to prepare and process some data, but after that data are
only inspected and never modified. The intention can be made explicit by
redefining the mutable variable as immutable.

It can be done either by processing data within a nested block or by redefining
the variable.

## Example

Say, vector must be sorted before usage.

Using nested block:

```rust,ignore
let data = {
    let mut data = get_vec();
    data.sort();
    data
};

// Here `data` is immutable.
```

Using variable rebinding:

```rust,ignore
let mut data = get_vec();
data.sort();
let data = data;

// Here `data` is immutable.
```

## Advantages

Compiler ensures that you don't accidentally mutate data after some point.

## Disadvantages

Nested block requires additional indentation of block body. One more line to
return data from block or redefine variable.
