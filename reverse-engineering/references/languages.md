# 按语言/运行时分的逆向要点

本域按"目标用什么语言/运行时编译"分类逆向打法。每种给:**识别特征**(怎么认出来)、**专用工具**、**典型坑**、**还原思路**。

适用于已授权的逆向 / 安全研究 / CTF 场景。

涵盖:Go、Rust、.NET(IL/dnSpy)、Swift/Objective-C、WebAssembly、Python 字节码(pyc)、JVM/Kotlin、C/C++、内核/驱动(LKM/Rootkit/sys)。

---

## Go

Go 二进制在 CTF / 恶意样本里越来越常见(CLI 工具、网络服务、C2 客户端)。静态链接 runtime 导致体积巨大、函数上万、字符串格式特殊。

### 识别特征

```bash
file binary | grep -i "go"
strings binary | grep -E "runtime\.|go\.buildid|GOROOT"
strings binary | grep "^go1\."          # 嵌入的 Go 版本
rabin2 -z binary | grep -i "runtime"
```

- 极大的静态二进制(hello world 也 ~2MB);C 同类只有 ~20KB
- 嵌入 `go.buildid` section、`runtime.gopanic`、`runtime.*` 符号(strip 后仍残留)
- 入口是 `main.main` 而非 `main`;有 `GOROOT`/`GOPATH`/`/usr/local/go/src/` 路径串
- 函数数量 5000–50000+(整个 runtime + 标准库都被链进来)

### 专用工具

| 工具 | 用途 |
|------|------|
| **GoReSym**(Mandiant) | 解析 pclntab/moduledata,恢复函数名/类型/接口/源文件路径,可导 IDA 脚本 |
| **redress**(goretk) | 分析 stripped Go 二进制,恢复源树/包/类型/接口 |
| **GoResolver**(Volexity) | 用 CFG 相似度自动去混淆 Garble 二进制 |
| **GoStringUngarbler**(Google) | 专恢复 Garble 加密字符串 |
| **go_parser**(IDA 插件) | 解析 moduledata/pclntab/类型信息、标记 Go 字符串 |
| **AlphaGolang** / **IDAGolangHelper** | IDAPython 脚本集 |
| IDA 9.2+ | 原生改进了 Go 反编译 |
| **dlv** / Frida | 动态调试 / Hook runtime 函数 |

### 关键结构

- **pclntab(PC Line Table)**:最重要的结构,函数名↔地址映射、源文件路径、行号、栈帧大小。即使 strip 也通常存在(runtime 依赖它)。magic:`0xFFFFFFF0`(Go 1.16+)/ `0xFFFFFFFB`(Go 1.18+),或让 GoReSym 自动定位。
- **moduledata**:pclntab 指针、类型信息表、itab(接口表)、全局变量信息。
- **内存布局**:
  - `GoString` = `{ptr, int64 len}`(16B,**非 null 结尾**)
  - `GoSlice` = `{ptr, len, cap}`(24B)
  - `GoInterface` = `{type, data}`(16B,type 指向 itab)
  - map/channel = 指向 `runtime.hmap` / `runtime.hchan`

### 反编译常见模式

- defer:`runtime.deferproc` 注册 / `runtime.deferreturn` 退出时 LIFO 执行(关注清理/擦 key)
- error:函数返回 `(result, error)` 双值;`test rax,rax` + `jne` 即 `if err != nil`
- 字符串拼接:`runtime.concatstrings`;格式化看 `.rodata` 里 `%s%d` 等
- goroutine:`runtime.newproc`;channel:`chansend1`/`chanrecv1`/`selectgo`/`closechan`
- embed.FS(Go 1.16+):编译期嵌入文件,grep `embed`,按 PK/PNG 等文件头搜原始数据
- crypto:imports/strings 找 `crypto/aes`、`crypto/sha256`、`encoding/hex`、`encoding/base64`

### 还原思路(分场景)

1. **未 strip**:`GoReSym -t -d -p binary > syms.json` → 导入 IDA/Ghidra → 过滤 `runtime.*` 和标准库 → 从 `main.main` 开始。
2. **strip 后**:GoReSym 仍能靠 pclntab 恢复;失败则 `redress -src/-pkg/-type` → IDA + go_parser 自动恢复。
3. **Garble 混淆**(函数名随机化、字符串加密、移除路径):`GoResolver`(CFG 签名匹配恢复标准库名)+ `GoStringUngarbler`(解密字符串)+ 动态 Hook;或编译同版本 hello world 做 binary-diff 对掉 runtime。
4. **CGo 混合**:识别 `_cgo_*` / `crosscall2` / `_cgo_topofstack` 作为 Go↔C 分界,两侧分别用 go_parser 和常规 IDA。

### 典型坑

- 函数太多 → 按包名过滤,只看 `main.*` 和业务包。
- 字符串识别不全 → Go 串非 null 结尾,IDA/Ghidra 默认会漏;用 go_parser/GoReSym 恢复。
- 伪代码难读(defer/goroutine/interface)→ IDA 9.2+ 改进或动态辅助。
- 跨版本 pclntab 格式不同 → GoReSym 覆盖 Go 1.2–1.23+。

### C2 客户端 UUID 重打(BSidesSF 2026 "see-two")

Go 用 `-ldflags -X main.x=...` 注入的字符串直接进数据段。`go version -m client_binary | grep ldflags` 取出嵌入 UUID,因 Go 串是定长 backing array,等长字节替换即得合法 patched 二进制(`data.replace(old_uuid, new_uuid)`),mTLS 证书不绑 UUID,可注册成新客户端枚举 C2。

---

## Rust

现代 CTF 常见于 crypto/系统/安全工具题。默认静态链接、体积大;泛型单态化导致大量相似函数。

### 识别特征

```bash
strings binary | grep "core::panicking"   # panic 基础设施
strings binary | grep "/rustc/"           # 源路径 /rustc/<commit>/library/
strings binary | grep "rustc"             # 编译器版本
```

- `_ZN` 前缀的 Itanium ABI mangled 符号(同 C++),module path 风格如 `_ZN4main4main17h...`
- ELF 里有 `.rustc` section

### 专用工具

```bash
cargo install rustfilt
nm binary | rustfilt | grep main     # 解 Rust 专属 mangling(c++filt 也能解大多数)
cargo install cargo-bloat            # 按函数分析体积
cargo bloat --release -n 50
```

- Ghidra:Script Manager 搜 "Demangler" 开 DemangleAllScript
- 社区脚本:`AmateursCTF/ghidra-rust`

### 常见模式

- `Option<T>` = `{discriminant(0=None,1=Some), value}`;`Result<T,E>` = `{discriminant(0=Ok,1=Err), union}`。反汇编里 `cmp byte [..],0` + `je` 即判 None/Err。
- `Vec<T>` = `{ptr, cap, len}`(同 Go slice 但字段序不同);`String` = `{ptr, cap, len}`(24B 堆);`&str` = `{ptr, len}`(16B,可指任意)。
- 看 `alloc::string::String::from`(建 String)、`core::str::from_utf8`(字节→str)。
- 迭代器链 `.iter().map().filter().collect()` 编译成 loop fusion + 内联闭包,找 `core::iter::adapters::map/filter`。

### 还原思路

**panic 信息是金矿**:即使 release build 也含源文件路径、行号、描述串。先跑 `strings binary | grep "panicked"` 和 `grep "called .unwrap().. on"`。

**serde_json schema 恢复**(PascalCTF 2026 "Curly Crab"):反汇编 serde 生成的 `Visitor`,`visit_map`/`visit_seq` 暴露期望 key 和类型;visitor 方法名揭示值类型(`visit_str`=string、`visit_u64`=number、`visit_bool`=bool、`visit_seq`=array);按 schema 顺序拼接 key 常即 flag。

### 典型坑

单态化使泛型函数按类型复制,会有很多长得几乎一样的函数,别误以为是重复代码。

---

## .NET(IL / dnSpy)

托管字节码(IL),反编译质量极高,通常能近乎还原 C# 源码。

### 识别特征

- PE 含 CLR header / `mscoree.dll` 导入;字符串含 `System.`、`mscorlib`
- NativeAOT(原生编译):找 `System.Private.CoreLib` 字符串,类型元数据仍在但被重排,搜长度前缀的 UTF-16 模式

### 专用工具

- **dnSpy** — 反编译 + 动态调试 + 编辑回写,首选
- **ILSpy** / **dotPeek**(JetBrains) — 纯反编译
- **de4dot** — .NET 反混淆(对抗 ConfuserEx 等)

### 还原思路 + 典型坑

`RijndaelManaged` 出现时,**先查 Key 和 IV 是否同值**——这是常见 CTF 套路。常见两段式:硬编码字节数组先 XOR 去混淆(可能多遍,如 `0x25` 再 `0x58` 等价单次 `0x7D`),Base64 解码,再 AES-256-CBC 解(Key=IV)。XOR 那层往往只是真 crypto 前的简单混淆。

```python
from Crypto.Cipher import AES
from base64 import b64decode
data = bytearray(encrypted_bytes)
for i in range(len(data)):
    data[i] ^= 0x7D                 # 合并 XOR key
ct = b64decode(bytes(data))
key = b"...32字节..."               # 提取出的 key,补齐 32B
pt = AES.new(key, AES.MODE_CBC, iv=key).decrypt(ct)
```

混淆样本先 de4dot 过一遍再丢 dnSpy;dnSpy 可直接下断点动态调试观察解密后的明文。

---

## Swift / Objective-C(Mach-O)

macOS/iOS 原生。ObjC 全靠 `objc_msgSend` 动态分发;Swift 用 witness table。

### 识别特征

```bash
otool -l binary | grep "swift"        # __swift5_* sections → Swift
strings binary | grep "swift"
# ObjC: __objc_methname / __objc_classname section、objc_msgSend 调用
```

- Swift mangled 名以 `s` 前缀;`swift_` runtime 符号
- ObjC:`@interface`/selector 字符串在 `__objc_methname`

### 专用工具

```bash
class-dump binary > classes.h         # dump @interface/@protocol/方法签名
# 替代:dsdump(更快,Swift+ObjC 都支持)、otool -oV(dump ObjC 段)
swift demangle 's14MyApp...'          # 解 Swift 符号(或 xcrun swift-demangle)
otool -l binary                       # load commands / segments / dylibs
otool -L binary                       # 链接的动态库
```

- Ghidra:Analysis Options 开 "Objective-C" 和 "Swift" 分析器(能解 `__swift5_types`/`__swift5_proto` 类型描述符)
- lldb 运行时检视:`expression -l objc -O -- [NSClassFromString(@"X") new]`

### 反汇编模式

- **ObjC**:`objc_msgSend(receiver, selector, ...)` 是核心。x86-64 下 RDI=self、RSI=selector(方法名 char*)。交叉引用 selector 串定位实现。
- **Swift**:value witness table(VWT)做类型操作,protocol witness table(PWT)做动态分发(类似 vtable)。关注 `swift_allocObject`(堆分配)、`swift_release`(引用计数)、`swift_once`(惰性初始化)、`swift_bridgeObjectRetain`(ObjC↔Swift 桥接)。
- 字符串:小串(≤15B)内联在 16B buffer / tagged pointer;大串堆分配 ptr+len+flags。

### iOS IPA 典型坑

```bash
unzip app.ipa -d extracted/ && ls extracted/Payload/*.app/
otool -l .../binary | grep -A4 "LC_ENCRYPTION_INFO"   # cryptid=1 即 FairPlay 加密
```

App Store 二进制被 FairPlay 加密(cryptid=1),静态反编译前需在越狱机上 dump 解密版(`frida-ios-dump` / Clutch / bfdecrypt),再 class-dump。越狱检测(查 Cydia/`/bin/sh`/`/etc/apt`、fork 成功、substrate)可用 Frida hook `access` 把对应路径返回 -1 绕过。

---

## WebAssembly(WASM)

### 识别特征

`.wasm` 文件头 `\0asm`;浏览器题里 JS 调用 `WebAssembly.instantiate`;导出函数名如 `flagChecker`/`validate`/`check`。

### 专用工具(wabt 套件)

```bash
wasm2wat module.wasm -o module.wat       # 转可读文本格式
wat2wasm module.wat -o module.wasm       # 回编(改完重打)
wasm-decompile module.wasm -o out.c      # 反编译成 C-like 伪代码
wasm-objdump -x module.wasm              # 看 section/导入导出/函数签名

# wabt 的 wasm2c:转 C 再编译成本机可执行,方便上 angr/调试/插桩
wasm2c checker.wasm -o checker.c
gcc -O3 checker.c wasm-rt-impl.c -o checker
```

### 模式 + 还原思路

- 线性内存是一个大数组(wasm2c 里叫 `w2c_memory`),所有指针都是该数组里的偏移。
- 运行时错误 → `wasm_rt_trap(N)`。
- 先看导出函数定位校验入口;wasm2c 转出本机二进制后可直接 angr 符号执行或 gdb 调试,比硬读 wat 快。

---

## Python 字节码(pyc / 反编译)

### 识别特征

`.pyc` 文件头是 magic number + 时间戳/size(Python 3.7+ 16 字节头);PyInstaller 打包的 EXE 解包后得一堆 `.pyc`。

### 专用工具(按版本选)

- **uncompyle6**:Python 2.x–3.8
- **pycdc**(zrax,源码编译 `cmake . && make`):Python 3.9+
- **decompyle3** / **pylingual**(在线):补充
- PyInstaller 解包:`pyinstxtractor.py`
- `dis` 模块直接读字节码(反编译失败时的 ground truth)

### 还原思路

字节码题往往把算法明摆在栈操作里,**反编译失败也能读 dis 输出**:
- `LOAD_CONST` + `COMPARE_OP` → 期望值
- `BINARY_XOR`/`BINARY_ADD` → 变换
- `BUILD_TUPLE`/`BUILD_LIST`(全常量)→ 目标数组
- `FOR_ITER` + `BINARY_SUBSCR` → 遍历输入字符;`CALL` on `ord` → 字符转 int

```bash
# 直接 dis 一个去头的 pyc
python -c "import dis,marshal; dis.dis(marshal.loads(open('x.pyc','rb').read()[16:]))"
```

### 典型坑

- **Opcode 重映射**:反编译报 opcode 错。样本自带改过的解释器/`opcode.pyc`。最快修法:在 PyInstaller bundle 里找改过的 `opcode.pyc`,与原版 diff,把目标 `.pyc` patch 回标准 opcode 再反编译。捷径:若样本自带定制 `./py` 解释器,把 uncompyle 装进它自己的环境用样本运行时反编译。
- **版本专属字节码**(VuwCTF 2025 "A New Machine"):题目盯死某 alpha/beta 版(如 3.14.0a4),alpha 的 opcode 与稳定版不同 → 必须**编译那个确切版本**来 dis。
- **Pyarmor 8/9**:运行时解密包装。用 `Lil-House/Pyarmor-Static-Unpack-1shot` 静态解(不执行样本码),输出 `.1shot.` 反汇编+实验性反编译,**以反汇编为准**。签名:payload 以 `PY`+六位数字开头(Pyarmor 7 及更早的 `PYARMOR` 格式不支持)。PyInstaller bundle 先解包再喂 1shot。

---

## JVM / Kotlin

Kotlin 编译成 JVM 字节码(Android/服务端)或 Kotlin/Native。

### 识别特征

```bash
strings classes.dex | grep "kotlin"      # kotlin.Metadata 注解、kotlin/jvm/internal/*
strings binary | grep "konan"            # Kotlin/Native
```

### 专用工具

```bash
jadx classes.dex            # Kotlin/DEX 最佳
cfr classes.jar --kotlin    # CFR Kotlin 模式
fernflower classes.jar out/ # IntelliJ 反编译器
```

### 模式

- Kotlin 标记:companion object → `ClassName$Companion`;data class → `copy()/component1()`;到处 `Intrinsics.checkNotNull()`;`when` → `tableswitch`/`lookupswitch`;sealed class → 链式 instanceof。
- **协程**编译成状态机:`invokeSuspend(result)` 里 `switch(this.label)`,每个 suspend 点是一个 state。跟着状态机走理解异步流。
- **Kotlin/Native**:LLVM 后端,无反射元数据,反汇编像 C/C++;ARC 引用计数(非 GC);关注 `InitRuntime`/`CreateStablePointer`;比 JVM 形态难逆很多。

---

## C / C++(原生)

### C 反汇编模式速查

| 源码 | 反汇编特征 |
|------|-----------|
| `if-else` | `cmp` + `jcc` |
| `switch` | 跳转表 `jmp [rax*8+table]` 或连续 `cmp` |
| `for`/`while`/`do-while` | 条件判断位置区分(顶部=while,底部=do-while) |
| 函数指针调用 | `call rax` / `call [reg+off]` |
| struct 访问 | `[reg+固定偏移]`(如 `[rdi+0x10]`) |
| `malloc`+用 | `call malloc` → 存寄存器 → 后续 reg+偏移访问 |
| 字符串比较 | `call strcmp` / `repe cmpsb` |

### C++ 特有模式

| 源码 | 反汇编特征 |
|------|-----------|
| 虚函数调用 | `mov rax,[rcx]`(取 vtable)→ `call [rax+off]` |
| 构造函数 | 分配内存 → 写 vtable 指针 → 初始化成员 |
| this 指针 | 第一个参数(rcx/rdi)是对象指针 |
| 多重继承 | 对象内多个 vtable 指针(偏移不同) |
| RTTI | vtable 前 -8 偏移是 `type_info` 指针 |
| 异常 | `__cxa_throw` / `_CxxThrowException` |
| `std::string` | SSO:≤15 char 内联,`{ptr, size, union{cap, buf[16]}}` |
| `std::vector` | `{begin, end, capacity_end}` 三指针 |
| `std::map` | 红黑树节点 `{left,right,parent,color,key,value}` |
| `std::unordered_map` | 哈希表 `{bucket_array, size, load_factor_max,...}` |

### vtable / 结构体还原

- 找 vtable:`.rodata`/`.rdata` 里连续函数指针数组;构造函数 `mov [rcx], offset vtable`。vtable[0] 通常是析构(或 deleting dtor),其余按偏移标注。
- 多个 vtable 共享前几个条目 → 继承关系;vtable 前 -8 是 RTTI(未 strip 时)。`c++filt _ZTI7MyClass` → typeinfo。
- struct 恢复:从访问偏移推字段(`[rdi+0x00]`=field_0…),从 `malloc(0x30)` 推大小,从构造函数推全字段;IDA "Create struct from selection"。

### 编译器 / 优化级别指纹

| 编译器 | 特征 |
|--------|------|
| MSVC | `_security_cookie`、`__fastcall`、Rich Header |
| GCC | `__stack_chk_fail`、`.note.GNU-stack` |
| Clang/LLVM | 类 GCC、优化模式不同、`__asan_*`(开 sanitizer 时) |
| MinGW | GCC 特征 + Windows API |
| AOSP Clang | `__android_log_print`、PGO 标记 |

| 优化级别 | 特征 |
|---------|------|
| -O0 | 冗余 mov、变量全在栈、不内联 |
| -O2 | 循环展开、内联、尾调用优化 |
| -O3/-Os | 激进内联、SIMD 向量化 |
| PGO | 冷代码分到 `.text.cold` |
| LTO | 跨模块内联、全局死代码消除 |

---

## 内核 / 驱动(LKM / Rootkit / sys)

### Windows 驱动(.sys)

| 类型 | 特征 | 分析重点 |
|------|------|---------|
| WDM | 老式,手动管 IRP | DriverEntry → 设备创建 → Dispatch 例程 |
| KMDF/WDF | 现代框架,事件驱动 | `WdfDriverCreate` → `EvtDriverDeviceAdd` → Queue/IO 回调 |
| Minifilter | 文件系统过滤 | `FltRegisterFilter` → Pre/Post 回调 |

**WDM 分析流程**:
1. 找 `DriverEntry`(IDA 自动,或搜 `IoCreateDevice`/`IoCreateSymbolicLink`)。
2. 找设备名 `\Device\X` 和符号链接 `\DosDevices\X`。
3. 找 Dispatch:`DriverObject->MajorFunction[IRP_MJ_DEVICE_CONTROL] = DispatchIoctl`(用户态 `DeviceIoControl` 的入口)。
4. 分析 IOCTL:`switch(IoControlCode)` 分发。`CTL_CODE(DeviceType, Function, Method, Access)`,Method ∈ {BUFFERED, IN_DIRECT, OUT_DIRECT, NEITHER}。
5. 找漏洞:用户缓冲区未验长度→溢出;`METHOD_NEITHER` 直接用用户指针→任意读写;IOCTL 没检权限→非特权可调。

```python
def decode_ioctl(code):
    device_type = (code >> 16) & 0xFFFF
    access      = (code >> 14) & 0x3
    function    = (code >> 2)  & 0xFFF
    method      = code & 0x3
    methods = {0:"BUFFERED",1:"IN_DIRECT",2:"OUT_DIRECT",3:"NEITHER"}
    access_t= {0:"ANY",1:"READ",2:"WRITE",3:"READ|WRITE"}
    return f"DevType={device_type:#x} Func={function:#x} Method={methods[method]} Access={access_t[access]}"
```

工具:**Driver Buddy Reloaded**(IDA 插件,自动识别 IOCTL/Dispatch/设备名)、FLIRT/Lumina(识别 WDK 库函数)、**WinDbg + IDA** 联动。已知漏洞驱动查 **LOLDrivers**(loldrivers.io)。

**WinDbg 内核调试**:被调试机 `bcdedit /debug on` + `bcdedit /dbgsettings net hostip:.. port:50000`;常用 `!analyze -v`、`lm`、`!drvobj \Driver\X`、`dt nt!_DRIVER_OBJECT`、`bp module!func`。

### Linux 内核模块(.ko / LKM)

关键函数:`init_module`/`module_init`(加载)、`cleanup_module`/`module_exit`(卸载)。关键结构:`file_operations`(字符设备 open/read/write/ioctl)、`net_device_ops`、`block_device_operations`。

**分析流程**:
1. 确认:`file module.ko` → "ELF 64-bit ... **relocatable**"(注意不是 executable)。
2. 找 init/exit:`readelf -s module.ko | grep -E "init_module|cleanup_module"`,模块信息在 `.modinfo` section(`modinfo` 也能看)。
3. 找 `file_operations`:搜 `register_chrdev`/`cdev_add`/`misc_register` → 定位 fops → ioctl/read/write 处理函数。
4. 分析 ioctl:`unlocked_ioctl`/`compat_ioctl` 里 `switch(cmd)`。

工具:`crash`(内核 dump)、`volatility3`(内存取证 Linux profile)、`dmesg`/`journalctl`、`lsmod`/`/proc/modules`、`strace`(用户态视角)。
GDB+QEMU 调试:`qemu-system-x86_64 -kernel bzImage -s -S ...` → `gdb vmlinux -ex "target remote :1234"`;`lx-symbols`/`lx-dmesg`/`p init_task`(需 `scripts/gdb/`)。

### Rootkit 常见技术与检测

| 技术 | 特征 | 检测 |
|------|------|------|
| syscall table hook | 改 `sys_call_table` 条目 | 内存表 vs 磁盘 vmlinux 对比 |
| VFS hook | 改 `file_operations` 函数指针 | 检查 fops 指针是否指向内核代码段外 |
| Netfilter hook | `nf_register_net_hook` | 遍历 netfilter hook 链表 |
| kprobe/ftrace hook | 注册 kprobe/ftrace 回调 | 查 ftrace 注册列表 |
| eBPF rootkit | 加载恶意 BPF | `bpftool prog list` |
| DKOM | 直接改内核对象(进程链表) | 遍历 task_struct 对比 /proc |

逆向时重点找:改 `sys_call_table`(syscall hook)、改 /proc(隐藏进程/文件)、注册 netfilter hook(隐藏网络连接)、改 VFS(隐藏文件)。

参考:VoidSec Windows 驱动逆向方法论、Elastic Linux Rootkit 系列、Microsoft Windows-driver-samples、Trail of Bits "Devirtualizing C++"。

---

## 其他少见运行时(速记)

- **D 语言**:符号 `_D` 前缀 + 数字长度前缀名(`_D4mainQ...`),Phobos 库 `_D3std...`;编译期模板使函数被复制几百次(`enc!("N")`);demangle 用 `set language d`(GDB)或 dlang.org core_demangle。
- **Haskell(GHC)**:`libHSbase-*`/`libHSrts-*` 共享库、`hs_main` 入口、Z-encoding 符号(`zd`=`.`、`zi`=`$`);STG closure 模型(惰性求值+thunk)极难逆;`hsdecomp` 恢复 closure 结构;有 `.cmm` 时读它理解 thunk;失败可 monkey-patch 已知 `Main_main_info` 强制求值。
- **Kotlin/Native** 见上 JVM 段。
