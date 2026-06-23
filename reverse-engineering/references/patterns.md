# 逆向模式识别知识库

> 目标:看到 **X 特征** → 判断 **是什么** → 知道 **怎么应对**。涵盖壳/打包器、代码混淆与 VM 保护、反调试/反 VM/反 DBI、加密算法指纹、以及 CTF 逆向常见套路。每条尽量给识别指纹 + 应对思路。安全研究默认在授权 / 受控环境(VM / Docker)中进行,疑似恶意样本绝不直接在主机跑。

---

## 一、壳 / 打包器(Packer)识别与脱壳

### 通用识别信号
- **熵值异常高**:整段 section 接近 8.0(`ent` / `binwalk -E` / Detect It Easy 看熵图),代码看起来是随机字节 → 已加壳/加密。
- **section 名异常**:`UPX0/UPX1`、`.vmp0/.vmp1`、`.themida`、`.aspack`、`.petite`、`.enigma` 等非标准名。
- **导入表极小**:只剩 `LoadLibrary` / `GetProcAddress`(或 Linux 下只剩 `dlopen`/`dlsym`)→ 真实 import 运行时解析。
- **入口点(EP)落在非 `.text` 的可写段**:典型脱壳壳行为。
- 用 **Detect It Easy (DIE)**、`yara` 规则、`peid`、`strings | grep -iE 'upx|vmprotect|themida'` 先做快速分类。

### 常见壳与应对
| 壳 / 打包器 | 识别指纹 | 应对思路 | 难度 |
|---|---|---|---|
| **UPX** | `UPX0/UPX1/UPX2` section,字符串含 `$Info: This file is packed with the UPX` | 优先 `upx -d`;魔改 UPX(改了 magic / header)则手动找 OEP:跟到 `popad` + 远跳后 dump | 低 |
| **ASPack / PECompact / Petite** | 对应 section 名,小型 stub | 找 OEP(常以一次大 `jmp`/`ret` 跳回原始 EP),ESP 定律(硬件断点在 `pushad` 后的栈地址),dump + 修 IAT(Scylla / ImpRec) | 中 |
| **VMProtect** | `.vmp0/.vmp1`,大量间接跳转,handler 表,寄存器虚拟机化 | 不要硬刚:聚焦关键算法点,在 VM 边界(进/出 handler)下断,trace 数据流;或用 VTIL / 反 VMProtect 工具半自动还原 | 高 |
| **Themida / WinLicense** | 多层、SDK API 字符串、强反调试 + 虚拟化 | 用对抗性插件(ScyllaHide / TitanHide)绕反调试,在真正业务逻辑处下断 dump;整体脱壳通常不现实 | 高 |
| **Enigma / Obsidium / .NET 加壳(ConfuserEx 等)** | 对应 SDK 痕迹;.NET 看 `de4dot` 是否能识别 | .NET 用 `de4dot` / `dnSpy` 动态;native 同上手动脱 | 中-高 |

### 手动脱壳通用流程(原生壳)
1. 跑起来到 OEP:ESP 定律 / 跟 `pushad`-`popad` 配对 / 在大跳转处停。
2. OEP 处 dump 内存映像(Scylla / x64dbg dump 插件)。
3. 修复 IAT(被壳间接化的导入)。
4. 重建 PE 头,验证可独立运行。
- 太复杂时换思路:**别脱壳,直接在解密后的内存里干活** —— 在业务逻辑处下断,内存里拿明文代码/数据。

---

## 二、代码混淆与 VM 保护识别

### 控制流平坦化(Control Flow Flattening,OLLVM 等)
**指纹**:一个大 `while(1)` + `switch(state)` 调度器;状态变量取一堆魔数(`if (i==0xA57D3848)... i=0x39ABA8E6;`);原始 if/else/loop 结构消失。
**应对**:
- 动态最省力:GDB 脚本在调度 `je`/比较处下断,记录状态变量取值序列,重建真实 CFG。
- 静态工具:**D-810**(IDA 插件,模式去混淆 + MBA 化简)、**GOOMBA**(Ghidra,自动反 OLLVM)、**Miasm**(符号执行)。

### 指令替换 / Mixed Boolean-Arithmetic(MBA)
**指纹**:简单运算被改写成等价的位运算+算术混合式,例如:
- `a ^ b` → `(a | b) & ~(a & b)`
- `a + b` → `a - (-b)`、`(x & y) + (x | y)`、`(x ^ y) + 2*(x & y)`
- `x | y` → `~(~x & ~y)`(德摩根)

常见等价化简表:
```text
(x & y) + (x | y)   == x + y
(x ^ y) + 2*(x & y) == x + y
(x | y) - (x & ~y)  == y
(x | y) & ~(x & y)  == x ^ y
```
**应对**:**SiMBA** / **Arybo** 自动化简 MBA 表达式;D-810 在 IDA 里直接化简;无工具时手算或 Z3 验证等价。

### 自定义 VM / 字节码解释器
**指纹**:程序自带一段 bytecode blob + 一个 dispatcher 大 `switch`(opcode → handler);有"寄存器数组 / 内存数组 / 指令指针"概念。RVA 派发变体:opcode 是指向 handler 的 RVA,handler 执行完读下一个 RVA 跳转。
**应对(标准流程)**:
1. 先逆 dispatcher,搞清 VM 结构(寄存器、内存、IP、opcode 含义)。
2. 写 disassembler 把 bytecode lift 成可读汇编。
3. 反编译 disassembly 理解真实算法,再写求解脚本。
- dispatcher 太复杂时改 **黑盒 fuzz**:发单条指令观察寄存器/内存变化,逐个 map opcode;变长指令集要测多个 bit 宽度(6-11 bit)对齐。

典型 opcode switch:
```c
case 1: *R[op1] *= op2; break;      // MUL
case 4: *R[op1] ^= mem[op2]; break; // XOR
case 7: if (R0) IP += op1; break;   // JNZ
case 10: R0 = getc(); break;        // INPUT
```

### 反汇编对抗(Anti-Disassembly)
| 技术 | 指纹 | 应对 |
|---|---|---|
| 不透明谓词(opaque predicate) | `x*x & 1` 恒为 0 这类恒真/恒假条件,看着数据相关实则固定 | Z3/SMT 证明分支恒定;手动删死分支 |
| Junk byte / 重叠指令 | 线性反汇编错位(插了假 `0xE8` CALL 头) | 切到图模式(IDA/Ghidra);从正确偏移 undefine 再分析 |
| 跳进指令中间(jump-in-the-middle) | `eb 01` 跳过 1 字节落进多字节指令中段 | 同上,从落点重新解码 |
| 函数分块(chunking) | 函数被无条件跳转拆成不连续块 | IDA "Append function tail" / Ghidra 在每块 Create function |
| `leave;ret` 链式调用 | 大量小代码块以 `leave;ret` 结尾、无对应 `call`;栈上交错放函数指针;IDA 报 "stack frame too big" | 逐函数单独建,理解栈帧改写顺序 |

---

## 三、反调试 / 反分析 / 反沙箱

### Linux 反调试
| 技术 | 指纹 | 绕过 |
|---|---|---|
| 自我 ptrace | `ptrace(PTRACE_TRACEME)` 返回 -1 即判定被调试 | `LD_PRELOAD` hook ptrace 返 0;pwntools 把 `ptrace` patch 成 `xor eax,eax; ret`;GDB `catch syscall ptrace` 后 `set $rax=0`;`echo 0 > /proc/sys/kernel/yama/ptrace_scope` |
| 双重 ptrace(看门狗子进程) | `fork()` 后子进程 `PTRACE_ATTACH` 父进程,阻止其它调试器 | 杀掉看门狗子进程再 attach |
| /proc 检查 | 读 `/proc/self/status` 的 `TracerPid`;扫 `/proc/self/maps` 找 frida 等 | hook `fopen`/`fread` 伪造内容;mount namespace 把 `/proc/self/status` bind 到 `/dev/null` |
| 计时检测 | `rdtsc` / `clock_gettime` / `gettimeofday` 前后差超阈值 | NOP 掉 `rdtsc`;Frida hook 时间函数;`faketime` / `libfaketime` |
| 信号反调试 | `signal(SIGTRAP,...)+int3`(调试器吃掉则被调试);`SIGALRM`+`alarm()` 超时自杀;`SIGSEGV` handler 藏真逻辑 | GDB `handle SIGTRAP nostop pass`、`handle SIGALRM ignore`、`handle SIGSEGV nostop pass` |
| 直接 syscall 绕过 hook | 内联 `syscall` 而非 libc(x86_64 ptrace=101) | 只能 patch 二进制或 GDB `catch syscall 101` |

### Windows 反调试
| 技术 | 指纹 | 绕过 |
|---|---|---|
| PEB.BeingDebugged | 读 PEB+0x2 | ScyllaHide 自动清;手动置 0 |
| NtGlobalFlag | PEB+0xBC(64 位)`& 0x70` | ScyllaHide / 清零 |
| NtQueryInformationProcess | class 0x7(DebugPort)/0x1E(DebugObjectHandle)/0x1F(DebugFlags,反向:0=被调试) | hook 该函数返假值 / ScyllaHide |
| Heap Flags | ProcessHeap 的 Flags(应=0x2)/ForceFlags(应=0) | ScyllaHide |
| TLS Callback | PE TLS 目录 AddressOfCallBacks,在 `main` 前执行反调试 | x64dbg 开 TLS Callback 断点;patch TLS 目录项 |
| 硬件断点检测 | `GetThreadContext` 读 Dr0-Dr3 | 用软件断点;hook GetThreadContext 清 DR |
| 软件断点/CRC 自校验 | 扫 `.text` 找 `0xCC`;或 CRC32/SHA 校验代码段 | 用硬件断点;patch 比较;hook 校验函数 |
| 异常类反调试 | `UnhandledExceptionFilter`(调试器下不调用)、`int 2dh` | 让异常正常传递 / patch |
| NtSetInformationThread | class 0x11 ThreadHideFromDebugger(隐藏线程,停掉调试事件) | hook 该函数忽略 0x11 / patch |

### 反 VM / 反沙箱
| 检测 | 指纹 | 绕过 |
|---|---|---|
| CPUID hypervisor 位 | `cpuid(1)` ECX bit31;`cpuid(0x40000000)` 厂商串 `VMwareVMware`/`KVMKVMKVM`/`Microsoft Hv`/`XenVMMXenVMM` | patch cpuid 结果;裸机跑 |
| MAC 前缀 | VMware `00:0C:29`/`00:50:56`,VirtualBox `08:00:27`,Hyper-V `00:15:5D`,Parallels `00:1C:42`,QEMU `52:54:00` | 改虚拟网卡 MAC |
| 文件/注册表/进程痕迹 | `vm*.sys`、`vbox*.dll`、`VBoxService.exe`、`HKLM\...\VMware Tools`、`vmtoolsd.exe`;Linux `/sys/class/dmi/id/product_name` 含 VirtualBox/VMware | 清痕迹 / hook 查询 |
| 资源检查 | CPU 核数<2、RAM<2-4GB、磁盘<60GB 判沙箱 | 给 VM 配足资源(4+核 / 8GB+ / 100GB+) |
| 计时型 VM 检测 | `rdtsc` 包住特权指令(强制 VM exit)看是否变慢 | NOP / hook 计时 |

### 反 DBI(Frida / Pin / DynamoRIO)
- **Frida 指纹**:`/proc/self/maps` 含 `frida`/`gadget`;默认端口 27042 可连;libc 函数 prologue 被改成 `0xE9`(JMP) hook;线程名 `gmain`/`gdbus`/`frida-*`;Windows 命名管道 `\\.\pipe\frida-*`。
- **绕过**:hook 检测函数本身(如 hook `strstr` 在命中 "frida"/"gadget" 时返 0);early-init 用 frida-gadget 抢在反 DBI 前加载。
- **Pin/DynamoRIO 指纹**:maps 里 `pin-`/`pinbin`、`dynamorio`/`drrun`;指令计数计时检测开销。

### 代码完整性 / 自哈希
**指纹**:CRC32/MD5/SHA256 over `.text` 或函数体,不匹配就 `exit` 或销毁 flag;独立看门狗线程循环校验。
**应对**:用硬件断点(不改代码);patch 比较恒真;hook 哈希函数返期望值;**改用模拟器(Unicorn/Qiling)** 完全不修改原码;杀看门狗线程。

### 通用绕过清单
1. 先 **枚举所有检查**:grep `ptrace`、`IsDebuggerPresent`、`rdtsc`、`cpuid`、`NtQuery`、`GetTickCount`、`/proc/self`、`SIGTRAP`、`alarm`、`signal`、`fork`。
2. 静态 patch(pwntools / Ghidra)优先于动态对抗。
3. Linux 用 `LD_PRELOAD` hook libc 返假值。
4. Windows 用 ScyllaHide 一键处理 PEB / NT 函数。
5. 检查太多就上 **模拟器**(Unicorn/Qiling),无调试器痕迹可检。
6. 注意**分层反调试**会叠加(TLS callback → main 里 ptrace → 看门狗线程 → 代码段自校验 → 信号 handler 藏真逻辑),逐层处理。

---

## 四、加密算法 / 编码特征指纹

### 通过常量识别算法(看到魔数 → 几乎可定性)
| 常量 | 算法 |
|---|---|
| `0x67452301 0xEFCDAB89 0x98BADCFE 0x10325476` | MD5(初始向量) |
| `0x6A09E667 0xBB67AE85 0x3C6EF372 0xA54FF53A ...` | SHA-256(初始哈希值) |
| `0x63 0x7C 0x77 0x7B`(S-box 开头) | AES(Rijndael S-box) |
| `0x243F6A88`(π 十六进制) | Blowfish(P-array 初值) |
| `0x9E3779B9` / `0x9E3779B97F4A7C15` | TEA/XTEA delta、黄金比例常量(也常见于各种哈希/PRNG) |
| `0xB7E15163` | RC5/RC6 magic |
| `0x61707865`("expa","expand 32-byte k") | ChaCha20 / Salsa20 |
| `0xC6EF3720` | XTEA(32 轮后的 sum) |
| `0x85EBCA6B` `0xA97288ED` | MurmurHash3 finalizer 常量 |
| `0x1b` / `0x11b` | GF(2^8) AES 约简多项式(看到即 Galois Field 运算) |
| `0xcbf29ce484222325` / `5381` | FNV / DJB2 哈希(常见于 hash-resolved import) |
| `0x2545F4914F6CDD1D` | xorshift64* 乘子 |

### 通过行为/结构识别
| 行为特征 | 可能算法 |
|---|---|
| 256 字节查找表 + i/j 双指针 swap | RC4(S-box init:0-255 循环,`S[i]`↔`S[j]`) |
| 16 字节块 + 多轮置换/查表 | AES |
| Feistel 结构(左右半交换) | DES / Blowfish / TEA |
| 固定 64 轮(或 32 轮 + delta) | TEA / XTEA |
| 大数乘法 / 模幂 | RSA |
| 椭圆曲线点加/倍点 | ECDSA / ECDH |

### XOR 家族识别与求解
- **重复密钥 XOR**:已知 flag 前缀(如 `flag{`、`0xL4ugh{`)即可恢复短密钥;试小密钥长度并验证可打印输出。CTF hint 短语常原文出现在 flag 体内。
- **带位置索引变体**:`cipher[i] = plain[i] ^ key[i%k] ^ i` —— 症状是重复密钥几乎对上前缀但后段崩,或 XOR 出的"密钥"每位 +1。**先剥 `^ i` 再恢复密钥。**
- **工具**:`xortool`(猜 key 长度 + 已知明文)、CyberChef XOR、`xortool-xor -f enc -s known`。

### 编码识别(字符集/格式特征)
| 编码 | 识别特征 | 解码 |
|---|---|---|
| Base64 | 末尾 `=`/`==`,字符集 `A-Za-z0-9+/` | `base64 -d` / CyberChef |
| Base32 | 大写+`2-7`,末尾 `=` | CyberChef |
| Base58 | 无 `0/O/I/l`,常见于 Bitcoin | CyberChef |
| Hex | 仅 `0-9a-f`,偶数长度 | `xxd -r -p` |
| URL / HTML 实体 | `%XX` / `&#XX;` | urldecode / CyberChef |
| Unicode 转义 | `\uXXXX` | Python `decode('unicode_escape')` |
| JWT | 三段点分 Base64URL | jwt.io / CyberChef |
| Brainfuck / Ook! | 仅 `><+-.,[]` / 仅 `Ook.Ook!Ook?` | 在线解释器 |
| 哈希 | 32/40/64 字符 hex | hashID 识别 → Hashcat/John 破解 |

### 工具路由
- **不知道是什么**:`ciphey -t "密文"` 自动识别;失败用 CyberChef **Magic** 模式;`dcode.fr` 古典密码全家桶。
- **哈希**:`hashid`/`haiti` 识别 → `hashcat -m <mode>` / John 破解;`hashes.com`/`crackstation` 在线反查。
- **RSA**:`RsaCtfTool --publickey pub.pem --private`(自带 Wiener/Boneh-Durfee/Fermat/共模/小 q/Hastad 等);`factordb.com` 查分解;SageMath 手算。
- **古典替换**:`quipqiup.com` 频率分析自动解。
- **ZIP 已知明文**:`bkcrack`(现代)/`pkcrack`。
- **约束求解**:`z3`(SMT)、`angr`(符号执行自动求输入)、SageMath(LLL/CVP 格密码)。
- **自定义加密**:IDA/Ghidra 逆出算法 → 手写解密脚本(常见就是提取 `.rodata` 里的常量表 + 写逆函数)。

### PRNG / 密钥流生成指纹
- **Xorshift32**:移位 13/17/5,无乘法常量。
- **Xorshift64\***:移位 12/25/27 后乘 `0x2545F4914F6CDD1D`。
- **Fisher-Yates 洗牌生成 S-box**:从 255 倒数循环,与 PRNG 选出的 `j` 交换 → 算法由 seed 完全决定。

---

## 五、CTF 逆向常见套路(看到现象 → 套路 → 解法)

### 数据藏在静态文件里,不必跑
- **命名符号泄露**:`readelf -s` / `nm` 看到 `EMBEDDED_ZIP`、`ENCRYPTED_MESSAGE`、`LICENSE` 等 → 直接从 `.rodata` 抠数据离线处理(找 `PK\x03\x04` 抠内嵌 ZIP,XOR 已知明文)。
- **静态比较目标**:程序把输入变换后和 `.rodata` 里的静态目标比 → 抠目标 + 写逆函数,反序 undo 每步操作恢复输入。
- **侧信道/特殊硬件实现但参数全在 data 段**(S-box、轮密钥、置换表):别去跑特殊硬件,静态抠表本地重算。
- **像素/位图即 flag**:程序渲染输入比较像素 → 期望像素就是 flag 渲染图,从 data 段抠出(常 XOR 一个常量如 `0xAA`)存图 + OCR(charset 白名单 `a-zA-Z0-9{}_` 提精度)。

### 逐字节可解(无扩散 / 链式独立)
- **字节级均匀变换 / 无扩散块密码**:改一个输入字节只变一个输出字节 → 对每位置试 256 个值匹配目标,逐字节恢复,不用知道密钥。
- **前缀哈希**:程序对输入每个前缀独立输出一个摘要 → 逐字符爆破(`N × |charset|` 次执行),改末字符只变末摘要即确认。
- **时序侧信道**:每对一个字符校验耗时变长 → 计时爆破,选最慢的字符;信号侧信道同理(`strace -e signal=SIGFPE` 数信号数)。

### 约束求解类(收集约束 → Z3/格)
- **SECCOMP/BPF 校验**:`seccomp-tools dump` 拿过滤器 → 把比较/内存操作翻成 Z3 约束求解,不必跑二进制。BPF 反汇编看不懂时开 `bpf_jit_enable` 让内核 JIT 成 x64 读 dmesg。
- **printf `%hhn` VM**:`%Nc%hhn` 把已打印字符数(mod 256)写进指针 → 等价字节写 VM;抠每对写的地址/值建方程组 Z3 解。
- **格密码(LLL/CVP)**:输入分组乘系数矩阵比 64 位常量,解必须是可打印 ASCII(普通代数失败) → SageMath LLL 约简 + CVP 求最近格点。
- **GF(2^8) 高斯消元**:`.rodata` 里 N×N 矩阵 + 增广向量,行操作是 XOR,出现 `0x1b`/`0x11b` → 在 GF(2^8) 上消元,解向量即 flag。
- **DNN 逆推**:sigmoid/tanh 激活 + 方阵权重(`.rodata` 浮点数组) → 逐层求逆 sigmoid、减 bias、乘权重逆;注意输入变换(如 `1/x`)也要逆。

### 自修改 / 多层解密
- **自修改代码 XOR 解密下一块**:每个输入字符作密钥解下一块,块首已知 opcode(函数 prologue `endbr64;push rbp;mov rbp,rsp`)即正确密钥字节,逐字节恢复 flag。
- **多层自解密(N 层洋葱)**:每层读密钥字节、派生密钥流、XOR 解下一层再跳入 → 用 oracle 判正确密钥(错密钥出垃圾码,对的出合法指令如恰好 2 个 `call read@plt`);爆破引擎走 JIT + fork-per-candidate(COW 隔离)远快于 ptrace。
- **内存自 dump**:程序读 `/proc/self/mem` 或 `/proc/self/maps` → 在 dump 自身(可能加密);用已知函数 prologue 作已知明文恢复 XOR 密钥。

### 信号 / 异常 / 多线程藏逻辑
- **信号即控制流**:多个 `sigaction(SA_SIGINFO)` + `sigaltstack` → 真逻辑在 handler 里(SIGSEGV/SIGILL/SIGFPE/SIGTRAP)。`LD_PRELOAD` hook `signal`/`sigaction` 把"安装下一个 handler"当作"当前字符正确"的侧信道。
- **SIGILL 模式切换**:`signal(SIGILL,...)` 早早安装 → 非法指令触发 handler,handler 改 RIP/段寄存器切 32/64 位或解释自定义 opcode。GDB `handle SIGILL nostop pass`。
- **Nanomites**:`fork()`+子进程 `PTRACE_TRACEME`,父进程才是真 CPU,用 `PTRACE_POKETEXT` 改子进程;魔数标记 `0x1337BABE`/`0xDEADC0DE`。日志记录父进程 POKE 操作重建算法。
- **多线程 + 解码诱饵**:线程 1 做假 crypto + `ud2` 故意崩(诱饵浪费分析时间),线程 2 在信号 handler 里用 MBA 算真 flag,线程 3 抹内存防 dump,主线程 `rdtsc` 计时。抠 MBA 逻辑用 Python 重实现,别在调试器下跑。
- **C++ 析构 / atexit 藏校验**:`main` 看着平淡 → 查 `__cxa_atexit`、`.init_array`/`.fini_array`,全局对象析构里藏校验。`__cxa_finalize` 下断。

### 指令级 / 体系结构陷阱
- **x86-64 符号扩展**:`movsx`/`cdqe` 把 `0xFFFFFFFF` 变 `-1`,反编译器常算错;XOR 只取低字节,加法走全 32 位带溢出。务必对照原始汇编验证。
- **循环边界状态更新**:汇编常把状态更新跨循环边界拆(`jmp loop_middle` 首次从中间进),decompiler 易把"用旧值还是新值"搞反。
- **指令计数器作密码状态**:手写汇编用某寄存器(如 `r12`)做指令计数器,几乎每条后 `inc`,值喂进每字节变换 → 路径相关,解析逆推不现实。Unicorn 逐字节爆破 + 保留正确前缀状态。
- **算术-only 混淆(无内存写)**:只有 sub/add/xor/rol/ror 寄存器运算 → 完全可逆:IDAPython 抓非跳转指令序列,逆序 + 互逆替换(`add↔sub`、`rol↔ror`,`xor` 自逆),Keystone 汇编 + Unicorn 模拟。注意 PEB 反调试可能切换比较目标。

### 格式/容器层把戏
- **ELF section header 损坏反分析**:`readelf -S`/`objdump`/IDA 崩但程序正常跑 → 段头损坏(`e_shoff` 等),但程序头(PT_LOAD)完好。`readelf -l` 仍可用;把 `e_shoff` 清 0 后 IDA/Ghidra 靠程序头加载;flag 常附在尾部带魔数(如 `DE AD BE EF` 后跟 XOR 数据)。
- **hash-resolved import(无导入表)**:`readelf -d` 几乎无动态符号(只 `dlopen`/`dlsym`),strings 无标准 API 名,反汇编见哈希循环 + 间接调用 → 别逆哈希函数,在沙箱里 `LD_PRELOAD` hook 它最终调的 crypto 函数(如 `EVP_CipherInit_ex`/`EVP_DecryptInit_ex`)抓 AES 密钥;ROR13/DJB2/FNV/SipHash 是常见哈希族。**疑似勒索/恶意样本只在 Docker/VM 跑、只挂副本。**
- **自定义 binfmt 内核模块**:`.ko` 调 `register_binfmt`,特定 magic 文件被内核解密执行;RC4 密钥常以 `movabs` 立即数存在(非 data 段);解密后是无 ELF 头的 flat binary,从 `.ko` 的 `vm_mmap` 取加载地址,`objdump -b binary` 或 Ghidra Raw Binary 导入。
- **后门 libc**:GDB 下能跑、正常跑失败 → `ldd` 查非标准库路径,`strings | diff` 对比系统 libc 找注入函数;suid 二进制在调试器下掉权,后门 libc 用 `getuid`/`geteuid` 检测并切换行为。
- **时间锁**:对比大整数常量落在可识别日期范围(Unix 时间戳 2012≈1.35B)→ `date -s` 或 `faketime` 设到指定日期跑;IDA 查 `time`/`localtime`,看 `tm_year`(自 1900)/`tm_mon`(0-based)。

### 其它取巧
- **INT3 + coredump oracle**:在变换输出点 patch `0xCC`,`ulimit -c unlimited`,跑后 `strings core` 抠中间状态,逐字符爆破,免全量逆向。
- **死分支**:`cmp [ebp-0xc],0x1` 恒假的 `je real_flag` 永不命中 → 把比较常量 `01` patch 成 `00` 进真路径;`strace` 揭示 fork/pipe/read 结构。
- **批量 crackme**:几百个同结构二进制 → 脚本 `objdump` 抽 `cmp`/`add`/`sub` 立即数,从目标反序 undo 算 key,不必执行。
- **mmap RWX shellcode**:`mmap(PROT_EXEC)` 后跳入 → data 段抠出常 XOR 旋转密钥解密再反汇编。
- **嵌入式固件(如 ESP32/Xtensa)**:主流工具不支持 → radare2 `-a xtensa`,加载 SDK 的 ROM linker script(`esp32.rom.ld`)把 ROM 地址映成符号,交叉参考公开 SDK 示例码定位应用逻辑。
- **图像里藏机器码**:base64 blob → 解出 PNG/BMP,像素 RGBA 即 ARM/x86 指令流;先看引入的模拟器库名(UnicornJS 等)确定 ISA,再 capstone 反汇编。
- **字体连字隐写**:OpenType GSUB 连字表把显示字符映射到隐藏字形 → `ttx font.otf` 转 XML,grep `LigatureSubst` 读映射;fontTools 解析。
