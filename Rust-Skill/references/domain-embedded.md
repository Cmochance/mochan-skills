# 嵌入式 / no_std / 裸机(embedded-hal / cortex-m / embassy)

在没有操作系统、内存受限的 MCU 上跑 Rust:`#![no_std]`、硬件抽象、中断、固定容量集合、async 嵌入式框架。

适用:写 `#![no_std]`/`#![no_main]` 固件、选 HAL/PAC、处理中断、在无堆环境管内存、选并发模型(裸轮询 / RTIC / embassy)、`defmt` 日志、probe-rs 烧录调试。

---

## no_std 基线

裸机程序去掉 std(它依赖 OS:堆/线程/文件/网络),只留 `core`(+ 可选 `alloc`):

```rust
#![no_std]
#![no_main]
use panic_halt as _;       // panic 处理器:必须有一个
#[cortex_m_rt::entry]
fn main() -> ! { loop { /* ... */ } }
```

- **必须提供 panic handler**:`panic-halt`(死循环)、`panic-abort`,或调试期 `panic-probe`(配 defmt 打印 panic 信息)。
- `entry` 返回 `!`(永不返回);没有 `std::` 任何东西可用——`Vec`/`String`/`HashMap`/`println!`/`std::time` 全没了。
- **要不要堆**:多数固件**无堆**(确定性 + 省 RAM)。确实要动态分配再 `extern crate alloc;` + 配一个全局 allocator(如 `embedded-alloc`),但优先用固定容量结构避开堆。

## 分层:PAC → HAL → BSP

- **PAC**(Peripheral Access Crate):`svd2rust` 从芯片厂的 SVD 文件生成,寄存器级类型安全访问。底层但啰嗦。
- **HAL**(Hardware Abstraction Layer):芯片家族的 HAL crate(如 `stm32f4xx-hal`、`rp2040-hal`、`esp-hal`、`nrf-hal`)封装 PAC,提供 GPIO/SPI/I2C/UART/timer 等友好 API。
- **`embedded-hal`**:跨芯片的 **trait 抽象**(`SpiBus`/`I2c`/`OutputPin`/`DelayNs`…)。驱动 crate(传感器/屏幕)只依赖这些 trait → **同一个驱动可在任意实现了 trait 的 HAL 上跑**,这是嵌入式 Rust 生态可移植性的核心。写驱动就面向 `embedded-hal` trait,别绑死某个 HAL。
- **BSP**(Board Support):具体开发板的引脚映射封装。

## 并发模型(选型)

| 模型 | 适合 | 取舍 |
|---|---|---|
| **裸轮询 + 中断** | 最简单的固件 | 全手动,状态机靠你写;中断与主循环共享数据要 `critical-section` + `Mutex<Cell<_>>` |
| **RTIC** | 硬实时、抢占式任务调度 | 基于中断优先级的静态调度,编译期保证无数据竞争;心智模型独特 |
| **embassy** | 现代默认 / 异步外设 | `async`/`await` 写并发,执行器无需 OS;HAL(`embassy-stm32` 等)原生 async;生态活跃 |

**推荐**:新项目优先看 **embassy**——async 让「等外设」不阻塞、代码线性好读,且它的 HAL 覆盖主流芯片。需要强硬实时保证或极致确定性调度时上 RTIC。最简单的玩具/极小 footprint 才裸轮询。

## 内存与固定容量集合

无堆环境用 **`heapless`**:栈/static 上的固定容量容器——`heapless::Vec<T, N>`、`String<N>`、`spsc::Queue`(单生产者单消费者无锁队列,中断↔主循环传数据常用)。容量 `N` 是编译期常量,满了返回 `Err` 而非增长。

其它要点:

- 大缓冲区放 `static`(配同步原语)或 `static mut`(unsafe,尽量避免);别在小栈上放大数组。
- 中断与主线程共享可变状态:`critical-section` 的 `Mutex<RefCell<T>>` / `Mutex<Cell<T>>`(这里的 `Mutex` 是临界区互斥,非 std 那个)。
- 关注**栈深度**:递归、大局部、深调用链会栈溢出(无 OS 保护页,溢出是静默腐败)。`flip-link` 把栈放在 RAM 低端,溢出时撞到边界而非踩数据,能更早发现。

## 日志与调试

- **`defmt`**:嵌入式专用日志,**延迟格式化**(设备只发索引 + 原始数据,主机端解码),比 `core::fmt` 省 flash/带宽巨多——MCU 上字符串格式化很贵。配 `defmt-rtt`(走 RTT)输出。
- **probe-rs**:烧录 + 调试 + RTT 读取的统一工具(`cargo embed` / `probe-rs run`),取代老的 OpenOCD+gdb 组合,体验好得多。
- `.cargo/config.toml` 设 `target`(如 `thumbv7em-none-eabihf`)和 runner(`probe-rs run --chip ...`),`cargo run` 即烧即跑。

## 典型坑

- **手贱用 std**:依赖了某个 crate 默认 `std` feature → 链接失败。所有依赖加 `default-features = false`,确认有 `no_std` 支持。
- **格式化/浮点开销**:`core::fmt`(尤其浮点 `{}`)拉进一大坨代码 + 慢。用 `defmt`,浮点慎用(无 FPU 的芯片是软件模拟,极慢)。
- **栈溢出静默腐败**:没有 OS 保护页,溢出直接踩内存导致诡异 bug。控制递归/大局部,用 `flip-link`。
- **忘了 panic handler / 没设 allocator 却用了 alloc**:链接期报缺符号。
- **中断里共享数据没同步**:直接读写全局 = 数据竞争/撕裂。走 `critical-section` + `Mutex<Cell>`。
- **驱动绑死具体 HAL**:写传感器驱动时直接 import 某 HAL 类型,丧失可移植性。面向 `embedded-hal` trait 泛型化。
- **`opt-level` 太低**:debug build 在 MCU 上可能放不下 flash 或太慢;嵌入式常给 dev profile 也开 `opt-level = "s"`/`1`。

## 关联知识库

- 规则:固定容量/小型化内存——[`rules/mem-arrayvec.md`](rules/mem-arrayvec.md)、[`rules/mem-smallvec.md`](rules/mem-smallvec.md)、[`rules/mem-compact-string.md`](rules/mem-compact-string.md)、[`rules/mem-thinvec.md`](rules/mem-thinvec.md)、[`rules/mem-smaller-integers.md`](rules/mem-smaller-integers.md)、[`rules/mem-with-capacity.md`](rules/mem-with-capacity.md);格式化开销 [`rules/mem-avoid-format.md`](rules/mem-avoid-format.md)
- 概览:[`unsafe-ffi.md`](unsafe-ffi.md)(寄存器/`static mut`/裸指针/`MaybeUninit` 与 C 厂商库 FFI);`rules/_index.md` 的 `unsafe-*`(尤其 [`rules/unsafe-safety-comment.md`](rules/unsafe-safety-comment.md)、[`rules/unsafe-minimize-scope.md`](rules/unsafe-minimize-scope.md))
- 数值:`rules/_index.md` 的 `num-*`(溢出/饱和/`NonZero`,定点运算常用)

## 参考

- The Embedded Rust Book、Embedonomicon(`#![no_std]`/`#![no_main]`/启动流程深挖)
- `embedded-hal` 文档(看 trait 列表)、各芯片 HAL crate(stm32xxxx-hal/rp2040-hal/esp-hal/nrf-hal)
- embassy 官网 + book;RTIC book;`heapless` / `defmt` / `critical-section` 文档
- probe-rs 文档、`flip-link` README;target triple 用 `rustup target list` 查,版本以 docs.rs / crates.io 当前为准
