# binary-reverse — PE/ELF/Mach-O 原生二进制静态逆向

原生二进制(PE/ELF/Mach-O,x86/x64/ARM/ARM64/MIPS/RISC-V)的静态逆向:工具选型、侦察→识别→反编译→定位→标注的工作流、关键命令、标注纪律。前提是对**已授权或自有**对象操作。

## 工具选型(先决定用哪个,别同时全开)

| 场景 | 首选 | 理由 |
|---|---|---|
| 快速侦察(格式/架构/字符串/导入) | `rabin2` / `file` / `readelf` / `otool` | CLI 噪音低,几秒出方向 |
| 命令行反汇编 + 脚本化 + 轻量 patch | radare2(`r2` + r2pipe) | 无 GUI,可批处理 / 自动化 |
| 高质量反编译(伪代码)+ 交互标注 | IDA Pro(配 ida-pro-mcp)/ Ghidra | Hex-Rays/Ghidra 反编译器最成熟 |
| 免费反编译器 | Ghidra(headless 可脚本) | 开源、多架构、可 headless 跑脚本 |
| 多反编译器对照 | dogbolt.org | 一个输出难读时换另一个,交叉验证 |
| 自动解 flag-checker / 满足约束的输入 | angr(符号执行) | 有明确成功/失败分支的校验器 |
| 跨架构 / 重反调试 / 无硬件模拟 | Qiling(基于 Unicorn,带 OS 层) | ARM/MIPS/RISC-V 在 x86 上跑;反调试默认失效 |
| 纯 CPU 模拟解密一段 blob | Unicorn | 没有 OS 依赖时最轻 |

互补关系:r2 侦察快,IDA/Ghidra 反编译深;r2 发现可疑字符串/地址后,需要伪代码或更强 xref 时切到 IDA/Ghidra。

工具按需装,缺则给官方命令让用户装,**不自动改全局环境、不自动注册 MCP**(见 `tools-and-mcp.md`)。路径以本机实际为准。

## 典型工作流(侦察 → 识别 → 反编译 → 定位 → 标注)

1. **快速侦察(几分钟)**:格式 / 位数 / 架构 / 入口点 / 字符串 / 导入导出。优先 plaintext flag、明文密钥、URL、错误消息。
2. **识别关键函数**:从字符串交叉引用、危险/网络/加密导入、入口流程三个口子入手;高 xref 计数的函数通常是核心逻辑。
3. **反编译目标函数**:看伪代码理解逻辑;读不懂换反编译器(dogbolt 对照)。
4. **定位逻辑**:用 xref / 调用图 / 数据流追踪(向后追密钥来源、向前追数据去向)收敛到判断点。
5. **持续标注**:边分析边重命名函数/变量、加注释,提升后续分析准确度(标注纪律见下)。
6. **必要时验证/解密**:用 Python(capstone/lief)、模拟(Unicorn/Qiling)、符号执行(angr)辅助计算,而非纯靠盯反汇编。

## 快速侦察命令

```bash
file binary                  # 类型、架构、是否 strip/PIE
rabin2 -I binary             # 综合信息(格式/位数/架构/入口/保护)
checksec --file=binary       # 安全特性(NX/Canary/PIE/RELRO,pwn 相关)

# 字符串(很多简单目标 flag/密钥直接是明文)
strings -a binary | less
rabin2 -z binary             # 数据段字符串
rabin2 -zz binary            # 全文件字符串

# 导入/导出/符号/节
rabin2 -i binary             # 导入(网络/文件/加密/注入/注册表 API 是线索)
rabin2 -E binary             # 导出
nm binary; readelf -s binary # 符号
readelf -S binary; objdump -h binary  # 节头

# 反汇编
objdump -M intel -d binary
aarch64-linux-gnu-objdump -d binary    # ARM64 交叉反汇编
```

## radare2(r2 / rabin2 / rasm2 / radiff2)

原则:**先侦察后深挖**;先 `aaa` 不要一上来 `aaaa`;**改前默认只读**,确需修改才 `-w` 并提醒备份。

```bash
# 交互分析
r2 sample            # 只读打开;调试用 r2 -d
> aaa                # 常规自动分析(样本大就先只分析入口附近)
> afl                # 列函数        afl~main / afl~sym.  过滤
> iz                 # 列字符串(数据段)   iz~http / iz~error
> iS  / is           # 节区 / 符号
> s entry0 / s main  # 跳转到地址
> pdf                # 反汇编当前函数      pd 20 反汇编 20 条
> axt <addr>         # 查谁引用该地址/字符串(交叉引用)
> px 64 / psz / pxa  # hex / 当前地址字符串 / 友好 hex 视图
> VV                 # 可视化图模式
> q

# 非交互一把梭
r2 -A -q -c "afl;iz;ii;q" sample

# 子工具
rabin2 -I/-z/-i/-E/-S/-s sample   # 信息/字符串/导入/导出/节/符号
rasm2 -d "9090"                   # 反汇编字节
rasm2 -a x86 -b 64 "xor eax,eax"  # 汇编
radiff2 old new; radiff2 -C old new  # 二进制 diff(-C 按函数)
rahash2 -a sha256 sample          # 哈希
rax2 0x401000 / rax2 -s hello     # 进制 / 编码转换

# patch(明确要改时)
r2 -w sample
> s 0x401000
> wa nop / wa jmp 0x401050        # 写汇编
> wx 9090                         # 写原始字节
> wq                              # 写入退出;改后再 pdf 验证
```

r2frida 联动:`r2 frida://spawn/./binary`,`\dt strcmp` trace、`\dm` 看内存映射(动态侧细节见 dynamic 域)。

## IDA Pro(含 ida-pro-mcp 工作流)

IDA Pro 是商业软件需手动安装。可选搭配 `ida-pro-mcp`(社区项目 `mrexodia/ida-pro-mcp`,**不是** PyPI 上的 `ida-mcp`)把 IDA 能力通过 MCP 暴露,工具前缀 `idapro_*`。是否注册 MCP 由用户决定(见 `tools-and-mcp.md`),启用后流程:

1. **概览**:`idapro_survey_binary(detail_level="minimal")` — 架构、入口点(main/WinMain/DllMain)、函数数、字符串、段、导入分类(加密/网络/文件IO/注册表)、高 xref 热门函数。
2. **深入函数**:`idapro_analyze_function(addr)` 一次拿伪代码+字符串+常量+调用者+被调用者+块;或 `idapro_decompile(addr)` / `idapro_disasm(addr, max_instructions=N)`。
3. **交叉引用 / 数据流**:`idapro_xrefs_to(addrs)` 查谁引用;`idapro_callgraph(roots, max_depth)` 调用链;`idapro_trace_data_flow(addr, direction="backward")` 追密钥/输入来源。
4. **搜索**:`idapro_find_regex(pattern)` 搜字符串(`key|password|secret`、`https?://`);`idapro_find_bytes(["48 89 ?? 24 ??"])` 字节模式(支持 `??` 通配)。
5. **标注**:`idapro_set_comments` / `idapro_rename`(批量重命名函数/全局/局部/栈变量,反汇编+反编译双向同步)。
6. **类型/栈帧**:`idapro_declare_type` 声明结构体、`idapro_set_type` 应用原型、`idapro_stack_frame` 看栈帧(确认缓冲区大小,漏洞分析有用)。
7. **patch**:`idapro_patch_asm`(`nop` / `jmp` / `mov eax,1; ret`)、`idapro_patch` 写字节。
8. **进制转换用 `idapro_int_convert`,不要手算。**

典型分析流(注册验证类):找 `serial|license|register|valid` 字符串 → `xrefs_to` 定位验证函数 → `analyze_function` 理解逻辑 → `callgraph` 看调用链 → 必要时 `patch_asm` 条件跳转。漏洞分析类:`entity_query(kind="imports", filter="strcpy|sprintf|gets")` 找危险函数 → `xrefs_to` 找调用点 → `stack_frame` 确认缓冲区 → `trace_data_flow` 确认用户可控。

ida-pro-mcp 实践注意:大文件/GUI 程序打开可能很慢(分析进行中不等于卡死,设超时耐心等);System32 等无权限路径需复制副本再开;遇到「No database bound」是还没打开文件。

## Ghidra

```bash
# headless 批分析 + 脚本(Jython/Python)
analyzeHeadless /path/to/project tmp -import binary -postScript script.py
```

- GUI 反编译 + 图视图 + hex 编辑一体;Swift/Objective-C/ARM-Thumb 需在 Analysis Options 启用对应分析器。
- Jython 脚本可批量:按指令模式(如出现 CPUID)重命名函数、抽取函数内所有 XOR 常量、批量反编译搜索 `strcmp`/`memcmp` 调用。
- 内置 EmulatorHelper 可模拟执行一段函数解密数据(写寄存器/内存 → setBreakpoint → run → readMemory 取结果)。
- Cutter(Rizin GUI)内置 r2ghidra 反编译,可作免费替代。

## GDB(静态结论的动态验证)

```bash
gdb ./binary
start                  # 跑到 main,顺带强制 PIE 基址解析
b *main+0xca           # PIE 下用相对断点(基址随机,别用绝对地址)
b *0x401234            # 非 PIE 绝对地址
run / c / si / ni      # 运行/继续/单步/步过
x/s $rsi               # 看字符串    x/20x $rsp 看栈    x/10i $rip 看指令
info registers; set $eax=0
gdb -ex 'start' -ex 'b *main+0x198' -ex 'run' ./binary   # 一行自动化
```

- **内存 dump 策略**:让程序自己算出答案再 dump。在最终比较处下断,输入正确长度的任意值,`x/s $rsi` 读出已算好的预期值。
- **诱饵 flag**:有的目标在真检查前放多个假目标,断点要下在**最终**比较,不是前面的。
- **比较方向**:`transform(input)==stored` → 逆 transform;`transform(stored)==input` → flag 就是对 stored 做一次 transform。
- 条件断点 `b *0x401234 if $rax==0x41`、watchpoint `watch *(int*)0x601050`、`commands`+`silent`+`continue` 静默日志、`rr` 反向调试(步过关键点后倒回而非重启)。pwndbg/GEF 增强(`context`/`vmmap`/`search`)。

## 符号执行 / 模拟(angr / Qiling / Unicorn)

- **angr**:适合有明确成功/失败分支的 flag 校验器、迷宫/路径类、约束密集校验。最简形态只给 find/avoid 地址:
  ```python
  import angr
  proj = angr.Project('./binary', auto_load_libs=False)
  simgr = proj.factory.simgr()
  simgr.explore(find=0x401234, avoid=0x401256)   # 地址从反汇编/Ghidra 取
  if simgr.found:
      print(simgr.found[0].posix.dumps(0))        # fd 0 = stdin
  ```
  约束符号输入(printable ASCII + 已知前缀 `flag{`)、`proj.hook_symbol` 把 crypto/hash 用 SimProcedure 替换避免路径爆炸、DFS 技术。**不擅长**:重 crypto、浮点、复杂堆操作。
- **Qiling**:模拟整个 OS 层(syscall/文件系统/注册表),`ptrace(TRACEME)` 等反调试默认失效;能在 x86 上跑 ARM/MIPS/RISC-V。`ql.os.set_syscall("ptrace", ...)` / `ql.hook_address(...)` 跳过检查。适合外来架构、IoT 固件、重反调试、批量输入测试。
- **Unicorn**:纯 CPU 模拟,没有 OS。映射代码段+栈→`emu_start(start,end)`,`hook_add(UC_HOOK_CODE,...)` 追寄存器变化。处理 64→32 混合模式(retf/retfq)时手动拷贝 GPR/XMM。

## 标注纪律(逆向结论的硬要求)

- 结论必须带**地址 / 偏移 / 函数名**,不说「某个函数」。例:`sub_140001000 在 +0xCA 处比较 input 与 stored_key`。
- PIE/ASLR 下区分**文件偏移**与**运行时虚拟地址**;给运行时地址注明基址或用「相对 main 的偏移」表达,避免别人对不上。
- 进制转换用工具(`idapro_int_convert` / `rax2`)算,不手算,手算易错。
- 持续重命名 + 注释,把猜测变事实:重命名前可在名字带「?」或注释标置信度(已确认 / 推测 / 待验证)。
- 反编译器输出可能有 bug,关键构造用第二个反编译器(dogbolt)或反汇编核对后再下结论。

## ELF 结构与反分析速查

ELF Header 关键偏移(64-bit):`e_type`@0x10(2=EXEC,3=DYN/PIE/SO)、`e_machine`@0x12(0x3E=x86_64,0xB7=AArch64,0x28=ARM)、`e_entry`@0x18、`e_shoff`@0x28(strip 后可能为 0)、`e_phnum`@0x38。常见节:`.text`/`.rodata`/`.data`/`.bss`/`.plt`/`.got`/`.init_array`(构造函数,可能藏反调试)/`.dynsym`/`.dynstr`。

常见反分析手法 → 对抗:strip 去符号 → GoReSym(Go)/签名匹配/FLIRT;无 section header(`e_shoff=0`)→ 只靠程序头分析;损坏 PHDR → 手动修 `e_phnum` 或忽略;UPX(含 `UPX!` 串)→ `upx -d`;自定义壳/运行时解密 .text → 跑到解密后(`mprotect(PROT_EXEC)` 后)dump 内存当新二进制;ptrace 反调试 → LD_PRELOAD hook / patch / Qiling 模拟。自解压特征:入口附近 `mmap(W|X)` → memcpy/解压循环 → `mprotect` 改权限 → `br/jmp` 到新映射地址。

Mach-O 速查:`otool -l`(load commands,LC_MAIN=入口、LC_LOAD_DYLIB=依赖)、`otool -L`(链接库)、`lipo -info`(胖二进制架构)/`lipo -thin arch`(抽单架构);关键段 `__TEXT`(代码)/`__DATA`(全局)/`__LINKEDIT`(符号),`__cstring` 存 C 字符串。patch 后需重签:`codesign -f -s - binary`(ad-hoc,本地测试用)。

大型 ELF(5MB+)策略:侦察(`rabin2 -I` + `strings | grep -i error\|http\|/proc` + 导入导出)→ 结构(`readelf -l` 看 LOAD 段、入口是否有解压)→ 从字符串/syscall(mmap/ptrace/open)/网络函数(connect/send)三类口子定位 → 分而治之(自解压先脱、多模块按功能分块、多版本用 radiff2/BinDiff 对比)。

## 何时切到其他域

- 已经看懂二进制、剩下是堆/ROP/kernel 利用 → `pwn-exploit.md`。
- 目标是 Go/Rust/.NET/Swift/WASM/Python 字节码等语言特定形态 → `languages.md`。
- 壳/VM/混淆/反调试识别与去除、加密算法特征 → `patterns.md`。
- patch diff / N-day / CVE 复现 → `patch-diff-nday.md`。
- 命中 .so 但要从 APK 层入手 → `mobile-reverse.md`。
- 需要 Frida 等运行时插桩深入 → 动态分析域。
