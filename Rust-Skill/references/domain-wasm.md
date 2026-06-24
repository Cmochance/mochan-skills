# WASM(wasm-bindgen / wasm-pack / wasm32 / 体积优化)

把 Rust 编到 WebAssembly:浏览器里跑 / WASI 运行时、与 JS 互操作、控制产物体积。

适用:选 wasm32 目标、`wasm-bindgen` 做 Rust↔JS 绑定、`wasm-pack` 打包、调试 panic、压体积、传复杂类型、选前端框架(Leptos/Yew/Dioxus)。

---

## 目标三元组(先选对)

| target | 跑在哪 | 用它当 |
|---|---|---|
| `wasm32-unknown-unknown` | 浏览器 / 嵌入宿主 | 前端 / 给 JS 当库;无 OS,std 大半不可用,靠 `web-sys` 调浏览器 API |
| `wasm32-wasip1`(原 `wasm32-wasi`) | WASI 运行时(wasmtime/wasmer)、边缘函数、插件 | 要文件/时钟/随机等系统能力,WASI 提供受限 syscall;std 大部分可用 |
| `wasm32-unknown-emscripten` | 移植 C/Emscripten 生态 | 少用,除非接 Emscripten 工具链 |

**最常见是 `wasm32-unknown-unknown` + 浏览器**。下文以它为主;WASI 场景 std 行为更接近原生(但仍无线程/部分网络)。

## wasm-bindgen:Rust ↔ JS

`wasm32-unknown-unknown` 本身只能传数字(i32/i64/f32/f64),传字符串/对象/闭包都要 **`wasm-bindgen`** 生成胶水代码:

- `#[wasm_bindgen]` 标在函数/struct/impl 上 → 导出给 JS 调用;标在 `extern "C"` 块上 → 导入 JS 函数给 Rust 调。
- **`js-sys`**:JS 内置对象/标准库的绑定(`Array`/`Object`/`Promise`/`Date`/`Map`…)。
- **`web-sys`**:浏览器 Web API 绑定(DOM/`fetch`/`WebSocket`/Canvas/WebGL…),按 feature 开启需要的接口(`web-sys` 很大,只开用到的 feature 控编译时间和体积)。
- `wasm-bindgen-futures`:把 JS `Promise` 和 Rust `Future` 互转(`async` 互操作)。

## 打包:wasm-pack

`wasm-pack build` 一条龙:编译到 wasm + 跑 `wasm-bindgen` 生成 JS/TS 胶水 + 生成 npm 包。`--target` 选产物形态:

- `bundler`(默认):给 webpack/vite/rollup 等 bundler 消费。
- `web`:直接 `<script type="module">` import,无需 bundler。
- `nodejs`:Node 环境。

非前端、纯 WASI 库可直接 `cargo build --target wasm32-wasip1`,不必 wasm-pack。前端框架(下)通常有自己的构建工具(trunk/dioxus-cli)封装这步。

## 调试

- **`console_error_panic_hook`**:默认 wasm panic 在浏览器只给一句模糊报错;装这个 hook 后 panic 打印到 `console.error`(带 message)。开发期必加(`std::panic::set_hook`)。
- 日志:`web-sys` 的 `console::log_1`,或 `tracing-wasm` / `console_log` crate 把 `log`/`tracing` 接到浏览器 console。
- 源码映射有限,定位靠 panic message + 日志为主。

## 体积优化(WASM 很在意产物大小)

产物要走网络下载,体积直接影响加载。手段从高 ROI 到精修:

1. **release profile**:`opt-level = "z"`(或 `"s"`,体积优先)、`lto = true`、`codegen-units = 1`、`panic = "abort"`(去掉展开代码),`strip = true`。见 [`rules/opt-lto-release.md`](rules/opt-lto-release.md)、[`rules/opt-codegen-units.md`](rules/opt-codegen-units.md)。
2. **`wasm-opt`**(binaryen):后处理 `.wasm` 再压一轮(`wasm-pack` 可自动跑),通常还能省可观体积。
3. **`twiggy`**:分析 `.wasm` 里谁占体积,定位大头(常是格式化/panic 文案/某个臃肿依赖)。
4. **allocator**:历史上用 `wee_alloc` 换更小分配器,但它**已不再维护**、有已知问题——现在多数情况直接用默认 allocator + 上面几步即可;要换优先评估其它在维护的方案,别无脑套 `wee_alloc`。
5. 砍依赖:`default-features = false`,只开 `web-sys` 实际用到的 feature。

## 传复杂类型

跨 JS 边界每次调用有序列化开销。复杂结构(嵌套 struct/集合)用 **`serde-wasm-bindgen`** 在 Rust 类型与 JS 值间转(配合 serde 派生,见 [`serde-data.md`](serde-data.md)),比手动拆字段干净。但**高频小调用别滥用**——边界开销累积,热路径尽量传基本类型或批量传。`gloo` 提供一套更友好的浏览器 API 封装(timers/storage/events/net),少写 raw `web-sys`。

## 前端框架

要在 WASM 里写整个前端 UI:

| 框架 | 风格 |
|---|---|
| **Leptos** | 细粒度响应式(signals),SSR + hydration 强,性能好 |
| **Yew** | 类 React(组件 + 虚拟 DOM),生态较早较成熟 |
| **Dioxus** | 类 React,跨平台(web/desktop/mobile 同一套) |

选型看团队偏好:要极致性能 + SSR 倾向 Leptos;熟 React 心智、要多端复用看 Dioxus;Yew 资料最多。它们都封装了 wasm-bindgen/构建细节。

## 典型坑

- **产物太大**:没配 release profile / 没跑 wasm-opt,几 MB 的 wasm。按上面体积清单逐步压,`twiggy` 定位大头。
- **用了不支持的 std**:`wasm32-unknown-unknown` 没有线程(`std::thread` panic/不可用)、没有文件系统、`std::time::Instant`/`SystemTime` 在浏览器要走 `web-sys` 的 `performance.now()`/`Date`,网络要走 `fetch`(`web-sys`)。编译过 ≠ 运行时不 panic。
- **没装 panic hook**:线上 panic 只看到 `unreachable executed`,无从下手。开发期必装 `console_error_panic_hook`。
- **JS 边界高频调用**:每次跨界有开销,热循环里频繁调 JS/传大对象会拖慢。批量化、把热逻辑留在 Rust 侧。
- **无脑 `wee_alloc`**:已废弃,可能引新问题;先靠 profile + wasm-opt,真要换分配器评估在维护的。
- **`web-sys` 全 feature 打开**:编译慢 + 体积涨。只开用到的接口 feature。

## 关联知识库

- 概览:[`serde-data.md`](serde-data.md)(`serde-wasm-bindgen` 传复杂类型)、[`performance.md`](performance.md)(profile/体积/热路径)、[`unsafe-ffi.md`](unsafe-ffi.md)(JS 边界本质是另一种 FFI,`#[wasm_bindgen]` 胶水的 ABI 约束)
- 规则:`rules/_index.md` 的 `opt-*`(尤其 [`rules/opt-lto-release.md`](rules/opt-lto-release.md)、[`rules/opt-codegen-units.md`](rules/opt-codegen-units.md))、`perf-*`、`serde-*`;格式化开销 [`rules/mem-avoid-format.md`](rules/mem-avoid-format.md)(panic 文案也占体积)

## 参考

- The `wasm-bindgen` Guide、Rust and WebAssembly Book
- `wasm-bindgen` / `js-sys` / `web-sys` / `wasm-bindgen-futures` 文档(docs.rs);`serde-wasm-bindgen`、`gloo` README
- wasm-pack 文档;binaryen(`wasm-opt`)、`twiggy`、`console_error_panic_hook` 项目页
- Leptos / Yew / Dioxus 各自官网;target 用 `rustup target add wasm32-unknown-unknown`,API/版本以 docs.rs 当前为准
