# 智能指针

> `Box<T>`(堆分配 / 递归类型)、`Rc<T>`(单线程多所有者)、`RefCell<T>`(运行期借用检查 / 内部可变),组合 `Rc<RefCell<T>>` 实现"共享 + 可变"。

```rust
use std::cell::RefCell;
use std::rc::Rc;

// 递归类型必须 Box:否则大小无法在编译期确定
enum List {
    Cons(i32, Box<List>),
    Nil,
}

fn sum(list: &List) -> i32 {
    match list {
        List::Cons(v, next) => v + sum(next),
        List::Nil => 0,
    }
}

fn main() {
    let list = List::Cons(1, Box::new(List::Cons(2, Box::new(List::Nil))));
    println!("list sum={}", sum(&list));

    // Rc:多所有者共享只读,引用计数
    let shared = Rc::new(vec![10, 20, 30]);
    let a = Rc::clone(&shared); // 计数+1,不复制数据
    let b = Rc::clone(&shared);
    println!("rc count={} len={}", Rc::strong_count(&shared), a.len());
    let _ = b;

    // Rc<RefCell<T>>:多所有者 + 内部可变
    let cell = Rc::new(RefCell::new(0));
    let cell2 = Rc::clone(&cell);
    *cell.borrow_mut() += 5;
    *cell2.borrow_mut() += 3; // 通过另一份所有权改同一数据
    println!("cell={}", cell.borrow());
}
```

输出:
```
list sum=3
rc count=3 len=3
cell=8
```

## 要点
- `Box`:把值放堆上;递归类型(链表/树)必须用它打破"无限大小"。
- `Rc` 共享只读、引用计数;`Rc::clone` 廉价(只 +1 计数),`Rc::strong_count` 查当前所有者数。
- `RefCell` 把借用检查移到运行期:同时 `borrow_mut` + `borrow` 会 panic(`already borrowed`)。
- 多线程要换成 `Arc<Mutex<T>>`(`Rc`/`RefCell` 非 `Send`/`Sync`,见 threads-basics)。

## 关联
- 概览:[`../ownership-lifetimes.md`](../ownership-lifetimes.md)
- 规则:[`own-rc-single-thread`](../rules/own-rc-single-thread.md)、[`own-refcell-interior`](../rules/own-refcell-interior.md)、[`mem-box-large-variant`](../rules/mem-box-large-variant.md)
