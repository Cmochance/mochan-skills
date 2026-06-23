# 游戏客户端逆向与分析(研究 / 反作弊评估视角)

前提:仅针对自有、获授权或纯研究/教学对象(单机、本地复刻、CTF、自建私服、反作弊技术调研)。本文只到方法论与工具盘点层面,不提供针对线上游戏的作弊或绕过反作弊的可运行实现。

游戏逆向的典型动机:理解引擎运行时结构、还原资源/协议格式、评估反作弊检测面、教学演示运行时内存模型。不同引擎(Unity / Unreal / 原生 C++)入口差别很大,先识别引擎再选路径。

## 识别引擎与技术栈(第一步)

不要凭直觉,先看文件布局:

- `*_Data/Managed/Assembly-CSharp.dll` 存在 → Unity Mono 后端。
- `*_Data/il2cpp_data/Metadata/global-metadata.dat` + `GameAssembly.dll`(Win)/ `libil2cpp.so`(Android)→ Unity IL2CPP 后端。
- `Engine/` `*/Binaries/` `*.pak` `*.uasset` + `GNames`/`GUObjectArray` 字样 → Unreal Engine。
- 一坨原生 `.exe`/`.dll`,无托管运行时 → 原生 C++(回到 binary-reverse 方法论)。
- 看导入表 / 字符串(`rg`、`strings`、PE 解析)快速确认:`mono-2.0`、`UnityPlayer`、`il2cpp`、`UE4`/`UE5`、`Unreal`。

引擎版本会影响所有结构偏移与 dumper 兼容性。先确定大版本(Unity 年份版本、UE4 vs UE5),工具链按版本选。

## Unity — Mono 后端

Mono 把 C# 编译成标准 CIL,保留几乎完整的元数据(类名、方法名、字段名),逆向体验接近读源码。

- **工具**:dnSpy / dnSpyEx(活跃 fork)、ILSpy、dotPeek。直接打开 `Assembly-CSharp.dll`。
- **流程**:
  1. 加载 `Assembly-CSharp.dll`(及 `Assembly-CSharp-firstpass.dll`、第三方托管 DLL)。
  2. 按类名/方法名搜索逻辑(伤害结算、存档读写、协议序列化)。
  3. dnSpy 支持运行时附加 + 断点 + 即时编辑回写 IL,适合在自有/研究环境观察运行时行为。
- **常见坑**:
  - 商用混淆器(如 Beebyte、ConfuserEx 等)会重命名符号、加控制流混淆、字符串加密,符号优势大打折扣;需要反混淆或动态求值字符串解密例程。
  - 部分游戏用 AOT 把 Mono 也编译进原生层,或加运行时完整性校验,改 DLL 后启动失败。
  - 别只读静态,运行时 attach 看真实字段值往往比硬读 IL 快。

## Unity — IL2CPP 后端

IL2CPP 先把 C# 转 C++ 再编译成原生机器码,符号信息被剥离进 `global-metadata.dat`,反编译产物是无符号原生代码。核心工作是把元数据还原成符号再喂给反汇编器。

- **工具**:Il2CppDumper、Il2CppInspector(支持生成 IDA/Ghidra 脚本与 C# 头)。配套 IDA Pro 或 Ghidra。
- **关键输入**:`GameAssembly.dll` / `libil2cpp.so` + `global-metadata.dat`。
- **流程**:
  1. dumper 解析 metadata,产出类/方法清单(`dump.cs`)+ 地址映射 + 反汇编器脚本(`.py`/`.json`/IDA script)。
  2. 把脚本导入 IDA/Ghidra,自动给函数命名、还原类型,无符号原生代码瞬间变可读。
  3. 在反汇编器里定位目标方法,结合交叉引用理解调用链。
- **常见坑**:
  - `global-metadata.dat` 常被加密或抹掉头部魔数(`AF 1B B1 FA`),dumper 报错时优先怀疑被改;需先还原 metadata。
  - 字符串字面量在 metadata 里集中存放,被加密时静态分析会断链。
  - IL2CPP 输出随 Unity 版本变化,dumper 版本要匹配引擎版本,否则地址映射错位。
  - 还原后的函数仍是原生代码,没有 Mono 那种"读源码"体验,需要正经做原生逆向。

## Unreal Engine(UE4 / UE5)

UE 的反射系统在运行时维护全量对象与类型信息,逆向核心是定位几个全局结构再遍历。

- **关键全局结构**:
  - `GNames`(`FNameEntry` 池)— 所有名字(类名、属性名、函数名)的字符串池。
  - `GObjects` / `GUObjectArray` — 所有 `UObject` 实例的全局数组。
  - `UClass` / `UProperty`(UE5 为 `FProperty`)/ `UFunction` — 描述类布局、字段偏移、蓝图可调函数。
- **思路(SDK / dumper)**:
  1. 在二进制里定位 `GNames`、`GObjects` 的地址(常用特征串/AOB 或已知签名)。
  2. 遍历对象数组,顺着反射元数据还原每个类的字段名与偏移,生成 C++ SDK 头。
  3. 用 SDK 头在反汇编器/ReClass 里把裸内存解释成有名字的结构体。
- **工具思路**:UE Dumper 类工具(社区有多个实现,按 UE 版本选)负责自动遍历反射树生成 SDK;原生分析仍回到 IDA/Ghidra。
- **常见坑**:
  - 偏移随 UE 大版本(4.x ↔ 5.x)及小版本变化,UE5 把多数 `UProperty` 改成 `FProperty`,旧 dumper 直接挂。
  - 自定义引擎分支(大厂魔改)会改结构布局,通用 dumper 不一定适用,要手工定位全局指针。
  - `.pak` 资源可能加密(见资源章节),需要 AES key 才能解。

## 内存分析与运行时结构还原

静态读不动或想观察真实运行时值时,转内存分析。这是研究运行时数据模型最直接的手段。

- **Cheat Engine(CE)**:
  - 适合教学/研究自有进程的内存。典型流程:精确值扫描 → 改变游戏内数值 → 再次扫描收敛 → 定位地址。
  - **指针链(pointer scan)**:动态地址每次重启变化,通过指针扫描找出从静态基址到目标的稳定偏移链,得到可复现的访问路径。
  - **AOB(Array of Bytes)扫描**:用一段唯一字节特征定位代码/数据,抵抗地址漂移;配合通配符容忍小改动。
  - 内置反汇编器 + "find out what accesses this address" 可反查哪段代码读写目标,快速定位结构与逻辑。
- **x64dbg**:Windows 用户态原生调试器,断点、内存断点、调用栈、模块/导入分析。适合跟踪函数级行为、配合反汇编器静态结论做动态验证。
- **ReClass.NET**:把一段内存按猜测的结构体布局可视化,逐字段标注类型(指针/浮点/字符串),迭代还原出 C++ 结构体定义,再回填到反汇编器。和 CE 指针链、UE SDK 配合使用。
- **常见坑**:
  - 反调试 / 完整性校验会在调试器附加或代码被改时崩溃或上报,研究时常需在隔离环境、关闭联网。
  - ASLR 让基址每次变化,务必用模块基址 + 偏移或指针链表达地址,别硬编码绝对地址。
  - 多线程/GC(托管运行时)会移动或释放对象,扫描到的地址可能失效。

## 反作弊(EAC / BattlEye / Vanguard 等)— 概念层

只讲它们大致如何工作以及逆向研究时的难点,不提供任何绕过实现。研究反作弊本身要在合法、隔离、获授权的前提下进行。

- **常见检测维度(概念)**:
  - **内核态驱动**:部分反作弊(如 Vanguard、EAC/BattlEye 的内核组件)运行在 Ring 0,可早于游戏启动加载,监控驱动加载、句柄打开、内存读写来源,检测面远超用户态。
  - **完整性校验**:对游戏代码段/关键数据做哈希或签名校验,检测内存补丁、inline hook、模块注入。
  - **进程/句柄监控**:检测可疑进程、调试器附加、对游戏进程的跨进程内存访问。
  - **环境/行为信号**:已知作弊工具特征、虚拟机/调试环境特征、统计层面的异常行为(由服务端判定)。
  - **加壳 / 虚拟化保护**:反作弊自身常被 VMProtect/Themida 等加壳或代码虚拟化,自我保护、抗静态分析。
- **逆向研究时会遇到的难点**:
  - 内核组件需要内核调试(双机调试、VM + 内核 debugger),门槛与风险都高,且驱动签名/PatchGuard 等机制限制实验。
  - 加壳与代码虚拟化让静态反汇编几乎无效,需要脱壳、还原虚拟机指令集,工作量极大。
  - 反调试/反 VM 让常规动态分析手段失效,需要专门的隐蔽调试环境。
  - 服务端检测不可见,客户端逆向只能看到一半。
- **边界**:本文止于"它检测什么、为什么难逆向"。任何针对线上游戏绕过这些机制的具体手段不在范围内,且通常违反服务条款乃至法律。

## 资源解包与协议观察(一般思路)

- **资源解包**:
  - Unity:AssetStudio / UABE / AssetRipper 解 `.assets`、AssetBundle,导出贴图/模型/音频/文本;部分 bundle 经 LZ4/LZMA 压缩或自定义加密。
  - Unreal:`.pak` 用 UnrealPak 或社区 pak 工具解;加密 pak 需先拿到 AES key(常藏在二进制里,通过逆向定位)。
  - 通用:未知容器先用 binwalk / 十六进制看魔数与结构,识别压缩/加密后再写解析器。custom 格式靠对照多个样本归纳字段。
- **网络协议观察**:
  - 抓包:Wireshark 看原始流量,mitmproxy / Figgerprint 类工具看 HTTP(S);TLS 加密需在自有/授权环境配信任证书。
  - 多数游戏用自定义二进制协议或 Protobuf/FlatBuffers,先判断序列化框架(看握手、字段 tag 规律、是否有 schema 字符串)。
  - 结合客户端逆向定位序列化/反序列化函数,比纯抓包猜字段快得多——找到打包函数就拿到了字段定义。
  - **坑**:加密/压缩在应用层之上时抓包只见密文,必须回到客户端找加解密点;心跳/校验字段(序号、时间戳、CRC、HMAC)会让重放失败,理解它们是协议分析的核心。

## 小结:按引擎选路径

- Mono → dnSpy 直读托管 DLL,最轻松,防混淆。
- IL2CPP → Il2CppDumper/Inspector 还原符号 → IDA/Ghidra 做原生逆向。
- Unreal → 定位 GNames/GObjects → dumper 生成 SDK → ReClass/反汇编器解释内存。
- 运行时 → CE(指针链/AOB)+ x64dbg + ReClass.NET 三件套还原结构与逻辑。
- 反作弊 → 概念理解 + 隔离环境调研,止于检测原理,不碰线上绕过。
