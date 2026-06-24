> **来源**:本文逐字移植自《Rust Design Patterns》(https://github.com/rust-unofficial/patterns) 的 `src/idioms/pass-var-to-closure.md`,许可 **MPL-2.0**。
> 本文件依 MPL-2.0 继续以该许可开放;移植仅添加了本头部说明,正文未改。文中跨章节链接指向上游原书。
> 完整许可见仓库根 [`NOTICE`](../../NOTICE)。

---

# Pass variables to closure

## Description

By default, closures capture their environment by borrowing. Or you can use a
`move`-closure to move the whole environment. However, often you want to move
just some variables to the closure, give it a copy of some data, pass by
reference, or perform some other transformation.

Use variable rebinding in a separate scope for that.

## Example

Use

```rust
use std::rc::Rc;

let num1 = Rc::new(1);
let num2 = Rc::new(2);
let num3 = Rc::new(3);
let closure = {
    // `num1` is moved
    let num2 = num2.clone();  // `num2` is cloned
    let num3 = num3.as_ref();  // `num3` is borrowed
    move || {
        *num1 + *num2 + *num3;
    }
};
```

instead of

```rust
use std::rc::Rc;

let num1 = Rc::new(1);
let num2 = Rc::new(2);
let num3 = Rc::new(3);

let num2_cloned = num2.clone();
let num3_borrowed = num3.as_ref();
let closure = move || {
    *num1 + *num2_cloned + *num3_borrowed;
};
```

## Advantages

Copied data are grouped together with the closure definition, so their purpose
is more clear, and they will be dropped immediately even if they are not
consumed by the closure.

The closure uses the same variable names as the surrounding code, whether data
are copied or moved.

## Disadvantages

Additional indentation of the closure body.
