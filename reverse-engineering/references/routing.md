# 路由矩阵 — 按目标类型 / 用户意图 / 工具链 分流

把任务路由到最合适的分域 reference 再开工。三维任一命中即可定位;跨域任务组合多个分域(见末尾「跨域路径」)。

> 用法:先完成路由再执行,别「先干后路由」。路由没命中 → 不硬塞进现有分域,向用户说明并提议新方法(可联网查方法论)。

## 按目标类型

| 目标类型 | 推荐入口 | 备选 |
|---|---|---|
| exe/dll/so/elf/macho/sys 二进制 | `binary-reverse.md`(IDA 反编译) | `binary-reverse.md` 的 r2/Ghidra 段;GDB/Unicorn |
| Go / Rust / .NET / Swift / WASM / Python 字节码 | `languages.md` | `binary-reverse.md` 深挖 |
| APK / Android | `mobile-reverse.md`(jadx 反编译 + apktool 解包) | 核心在 .so → `binary-reverse.md` |
| iOS / IPA / Mach-O app | `mobile-reverse.md`(class-dump/Objection/Frida iOS) | `languages.md`(Swift/ObjC) |
| JavaScript / Web 前端 | `js-web-reverse.md`(观察→取证→采样→补环境复现) | CDP/Hook、抓包重放 |
| HTTP 抓包 / 浏览器采样 / 请求重放 | `js-web-reverse.md` 抓包段 | 浏览器自动化 MCP |
| 固件 / IoT | `firmware-iot.md`(binwalk/ARM/MIPS) | Ghidra headless |
| 内存 dump / PCAP | `patterns.md` + `firmware-iot.md` | `malware-supplychain.md` |
| 恶意样本 / 病毒 | `malware-supplychain.md`(YARA/sandbox/行为) | `binary-reverse.md` 深挖 |
| 加密算法 / 加解密 | `patterns.md`(crypto 特征识别) | `js-web-reverse.md`(前端加密) |
| 协议逆向 / 自定义协议 | `firmware-iot.md` 协议段 / `js-web-reverse.md`(WS/HTTP) | `patterns.md` |
| Game(Unity/Unreal) | `game-security.md`(引擎逆向、反作弊、IL2CPP/Mono) | `binary-reverse.md` |
| pwn / 漏洞利用 | `pwn-exploit.md` | `patterns.md`(CTF pwn) |
| patch diff / N-day / CVE 复现 | `patch-diff-nday.md` | `binary-reverse.md` |
| (授权)Web/主机 渗透 | `pentest.md` | `network-ad-c2.md` |
| (授权)内网 / AD / 域 | `network-ad-c2.md` | `pentest.md` |
| LLM / AI 应用 | `llm-security.md`(OWASP LLM + Agent 安全) | — |
| API / REST / GraphQL | `pentest.md`(BOLA/BFLA/JWT/OAuth) | — |
| 供应链 / SBOM / CI-CD | `malware-supplychain.md`(Trivy/Syft/Gitleaks) | — |
| CTF(整题) | `ctf.md`(按证据分流) | 按主导证据进对应分域 |

## 按用户意图(用户说什么 → 进哪)

| 用户说 | 路由到 |
|---|---|
| 「反编译 / IDA 分析」「看看这个 exe / dll」「帮我破解 / 找密码」 | `binary-reverse.md` |
| 「还原源码 / 反汇编」 | `binary-reverse.md` |
| 「radare2 / r2 分析」「rabin2/rasm2/radiff2 怎么用」 | `binary-reverse.md`(r2 段) |
| 「Frida hook / 动态注入」 | `mobile-reverse.md` 或 `binary-reverse.md` 的动态段 |
| 「找前端签名 / 加密参数 / 风控字段」「jshook / CDP 调试」 | `js-web-reverse.md` |
| 「APK 解包 / 重打包 / 改 smali」 | `mobile-reverse.md` |
| 「绕过反调试 / 反检测」「这是什么壳 / VM」 | `patterns.md` |
| 「Go/Rust/Swift 逆向」「Python pyc 反编译」 | `languages.md` |
| 「内核驱动 / Rootkit / LKM」 | `languages.md`(内核驱动段) |
| 「符号执行 / angr」 | `binary-reverse.md`(动态/符号执行段) |
| 「pwn / 栈溢出 / 堆 / ROP / ret2libc / kernel pwn」 | `pwn-exploit.md` |
| 「N-day / 补丁差分 / CVE 复现 / bindiff / 符号迁移」 | `patch-diff-nday.md` |
| 「端口扫描 / Nmap」「漏洞扫描 / Nuclei」「SQL 注入 / SQLMap」「目录爆破 / FFUF」「密码破解 / Hashcat / Hydra」 | `pentest.md` |
| 「SRC / Bug Bounty / 众测」「WAF bypass」「SSTI / XSS / IDOR / 越权」 | `pentest.md` |
| 「BurpSuite / Burp MCP / Intruder / Repeater / Collaborator」 | `pentest.md`(Burp 段) |
| 「内网渗透 / 横向移动 / 域渗透 / AD」「Mimikatz / Kerberoasting / DCSync / PtH」「C2 / 持久化 / Cobalt Strike / Sliver」 | `network-ad-c2.md` |
| 「蓝队 / 检测 / 防御 / 应急响应」 | `network-ad-c2.md`(检测视角) |
| 「Prompt 注入 / AI 安全 / Agent 安全 / 越狱测试」「garak / PyRIT / promptfoo」 | `llm-security.md` |
| 「Game 逆向 / 反作弊」「Unity / IL2CPP / Mono」「Unreal / UE」「Cheat Engine / 内存扫描」 | `game-security.md` |
| 「YARA / 恶意样本 / 病毒分析」「IOC / Sigma」 | `malware-supplychain.md` |
| 「供应链安全 / SBOM / SCA / Trivy / Syft / Gitleaks」 | `malware-supplychain.md` |
| 「iOS 逆向 / IPA / class-dump / Objection / SSL Pinning 绕过」 | `mobile-reverse.md` |
| 「固件 / IoT / binwalk / ARM / squashfs / UART」 | `firmware-iot.md` |
| 「Wireshark / PCAP / 抓包分析」「协议逆向 / Protobuf」 | `firmware-iot.md` / `js-web-reverse.md` |
| 「CTF 题 / 比赛逆向」 | `ctf.md` |
| 「写报告 / writeup / 文档」 | 任务结束按完成清单产出;脱敏见 anonymization 约定 |
| 「画图 / 流程图 / 攻击路径图 / 架构图」 | 用 Mermaid/Graphviz/PlantUML,放报告里 |

## 按工具链

| 工具 | 相关分域 |
|---|---|
| IDA Pro(idapro_* MCP) | `binary-reverse.md` |
| radare2(r2/rabin2/rasm2/radiff2/r2pipe) | `binary-reverse.md` |
| Ghidra(headless / MCP) | `binary-reverse.md` |
| jadx / apktool | `mobile-reverse.md` |
| Frida / Objection | `mobile-reverse.md`、`binary-reverse.md` 动态段 |
| GDB / GEF / pwndbg / pwntools / ROPgadget / one_gadget | `pwn-exploit.md` |
| angr / Qiling / Unicorn | `binary-reverse.md`(符号执行/模拟) |
| BinDiff / Diaphora / ghidriff | `patch-diff-nday.md` |
| jshookmcp / anything-analyzer / CDP | `js-web-reverse.md` |
| Cheat Engine / x64dbg / ReClass / IL2CPP Dumper / dnSpy | `game-security.md` |
| Nmap / Masscan / Nuclei / ZAP / Nikto | `pentest.md` |
| SQLMap / FFUF / Gobuster / SSTImap / XSStrike | `pentest.md` |
| Hashcat / John / Hydra | `pentest.md` |
| Metasploit / Impacket / NetExec(nxc) | `pentest.md`、`network-ad-c2.md` |
| BurpSuite / Burp MCP | `pentest.md` |
| BloodHound / Mimikatz / Coercer / Certipy | `network-ad-c2.md` |
| Cobalt Strike / Sliver / Havoc | `network-ad-c2.md` |
| garak / PyRIT / promptfoo | `llm-security.md` |
| YARA / Sigma / Trivy / Syft / Gitleaks / OSV-Scanner | `malware-supplychain.md` |
| binwalk / unblob / EMBA | `firmware-iot.md` |

> 工具实际可用性、路径、版本以本机为准(见 `tools-and-mcp.md` / 本机 `config.local.json`),不要猜路径。

## 跨域路径(常见组合)

```
APK 逆向:
  mobile-reverse(jadx 解包 → Java 层) → 核心在 .so? → binary-reverse(IDA/r2 分析 .so)
  → 需动态验证? → mobile-reverse(Frida Hook)

前端 JS 逆向:
  js-web-reverse(观察 → 定位目标请求) → 需更强 CDP/Hook? → jshookmcp 运行时采样
  → 确认入口函数 → js-web-reverse(Node 本地复现) → 需补环境 → 补环境段

二进制逆向:
  binary-reverse(r2 快速侦察) → 深挖 → IDA 反编译 → 动态验证 → Frida/GDB

pwn 链:
  binary-reverse / patterns(定位漏洞点) → pwn-exploit(本地通) → 远程稳定打通(libc/堆时序/缓冲)

授权 Web 渗透 + Burp:
  浏览器自动化(带 Burp 代理browse 目标) → Burp proxy history(分析请求)
  → 可疑端点 → Intruder 枚举 → 漏洞确认 → 出报告

CTF:
  ctf(建沙盒模型,按主导证据分流) → web/pwn/re/crypto/forensic 对应分域 → 卡住回 ctf 重路由
```
