# 生命周期实战

> 生命周期标注让编译器确认引用不悬垂;多数函数靠省略规则自动推断,只有"返回引用""struct 持引用""多引用需关联"时才手写 `'a`。

```rust
// 返回引用:返回值生命周期必须来自某个输入参数
fn longest<'a>(a: &'a str, b: &'a str) -> &'a str {
    if a.len() >= b.len() {
        a
    } else {
        b
    }
}

// 省略:单输入引用 -> 输出引用,编译器自动绑定,无需写 'a
fn first_line(s: &str) -> &str {
    s.lines().next().unwrap_or("")
}

// struct 持有引用:S 不能活过它借的数据
struct Excerpt<'a> {
    part: &'a str,
}

impl<'a> Excerpt<'a> {
    fn part(&self) -> &str {
        self.part
    }
}

fn main() {
    let s1 = String::from("hello there");
    let s2 = String::from("hi");
    println!("longest={}", longest(&s1, &s2));

    println!("first_line={}", first_line("line1\nline2"));

    let novel = String::from("Call me Ishmael. Some years ago...");
    let first_sentence = novel.split('.').next().unwrap();
    let ex = Excerpt { part: first_sentence }; // ex 不能活过 novel
    println!("excerpt={}", ex.part());
}
```

输出:
```
longest=hello there
first_line=line1
excerpt=Call me Ishmael
```

## 要点
- `longest` 必须写 `'a`:有两个输入引用,编译器无法自己判断输出借哪个,得显式关联。
- `first_line` 不用写:省略规则(单输入引用 → 输出绑定到它)覆盖了。
- struct 存引用 = 生命周期传染:`Excerpt<'a>` 处处带 `'a`;多数情况改存 owned `String`/`Arc` 更省心。
- 编译器拒绝返回局部引用(E0515)——返回 owned 值,而不是借走即将 drop 的局部。

## 关联
- 概览:[`../ownership-lifetimes.md`](../ownership-lifetimes.md)
- 规则:[`own-lifetime-elision`](../rules/own-lifetime-elision.md)
