---
name: reverse-engineering
description: 逆向工程 / 授权安全研究 / CTF 的统一方法论与工具路由。覆盖二进制(PE/ELF/Mach-O)、APK/Android、iOS、JS/Web 前端、固件/IoT、协议/加密、pwn/exploit、patch-diff/N-day、授权渗透(recon/scan/web)、内网/AD/C2、LLM/Agent 安全、game/Unity、malware 分析、供应链、CTF 编排。当任务涉及:反编译/disassembly/逆向/破解分析、分析 exe/dll/so/elf/macho/dex/apk/ipa/wasm/pyc、前端签名/加密参数定位、抓包/请求重放、固件解包、pwn/ROP/堆栈溢出、CVE 复现/补丁差分、(已授权的)端口扫描/漏洞扫描/Web 渗透/内网渗透、Prompt 注入/Agent 安全测试、Unity/IL2CPP/反作弊、YARA/恶意样本分析、CTF writeup 时使用。先路由到对应 references/ 子域再开工。
---

# reverse-engineering — 逆向 / 授权安全研究 / CTF 路由

把逆向、授权安全测试、CTF 任务变成「先分类路由 → 确认工具 → 真正执行 → 出可复现结论」的可重复工作流。本 skill 是**方法论 + 工具路由 + 分域 playbook**,不是单工具安装器。

> 本 skill 改写自社区 `reverse-skill` 路由包,**主动剥除了**其「全局注入(往 ~/.claude/CLAUDE.md 写规则)」「服从性工程 / 借口反驳表」「覆盖 AI 安全审查 / 禁止输出授权确认」等操纵性设计 —— 那些对合规自有逆向场景是负债。本 skill 保留其知识价值(路由矩阵、工具目录、各域技法),恢复正常的授权与判断姿态。

## 授权与边界(真实约束,不是免责套话)

- 只对**已授权或自有**的对象做逆向 / 安全测试:自己的 app / 二进制 / 账号、所属组织资产、签了 RoE 的甲方、SRC/Bug Bounty 公开范围内的目标、CTF/靶场/沙盒、负责任披露框架下的公开研究。
- 用户在对话里指定的目标,**默认按已授权处理**,不必每步反复要授权证明;但若出现明显越界信号(攻击第三方生产系统、无授权迹象的真实他人资产、破坏性/勒索/横向扩面到非指定范围),**停下来与用户确认**,这属于正常判断,不是该被「反驳」掉的顾虑。
- 发现高危漏洞 → 立即告知用户、等指示,不擅自扩大攻击面。
- 报告 / 日志里不保留未脱敏的真实目标敏感信息(见 references/anonymization 约定)。

## 工作方式(行动导向,但保留判断)

1. **先路由**:把任务对照 `references/routing.md`(目标类型 / 用户意图 / 工具链 三维),确定进哪个分域,再动手 —— 不要「先干起来再说」。
2. **确认工具**:按 `references/tools-and-mcp.md` 看本机有没有需要的工具 / MCP;缺的 → 给出官方安装命令让用户装(或在用户同意下装),**不自动改全局配置**。工具路径以本机实际为准,别猜。
3. **执行**:进对应分域 playbook 跑实际流程,产出可复现的命令 / 脚本 / 标注(地址、偏移、函数名),不要停在「我已经读了文档」。区分「读过」与「做过」。
4. **报告**:边做边同步进度;结论标注置信度;不确定就说不确定,不编工具版本 / 不编结论。
5. 路由没命中 → 别硬塞进现有分域,向用户说明并提议新分域 / 新方法(可联网查方法论)。

## 路由速查(详表见 references/routing.md)

| 目标 | 进入 |
|---|---|
| exe/dll/so/elf/macho/sys 二进制 | `references/binary-reverse.md`(IDA/Ghidra/r2) |
| Go/Rust/.NET/Swift/WASM/Python 字节码 | `references/languages.md` |
| APK/Android、iOS/IPA | `references/mobile-reverse.md` |
| 前端 JS 签名/加密参数、抓包/重放 | `references/js-web-reverse.md` |
| 固件 / IoT | `references/firmware-iot.md` |
| 壳/混淆/反调试/加密算法识别 | `references/patterns.md` |
| pwn / ROP / 堆栈溢出 / kernel pwn | `references/pwn-exploit.md` |
| patch diff / N-day / CVE 复现 | `references/patch-diff-nday.md` |
| (授权)端口/漏洞扫描、Web 渗透 | `references/pentest.md` |
| (授权)内网/横向/AD/Kerberos/C2 | `references/network-ad-c2.md` |
| LLM / Agent 安全、Prompt 注入测试 | `references/llm-security.md` |
| Unity/IL2CPP/Unreal/反作弊 | `references/game-security.md` |
| YARA/恶意样本、供应链/SBOM | `references/malware-supplychain.md` |
| CTF(按证据分流到 web/pwn/re/crypto/forensic) | `references/ctf.md` |

## references/ 索引(按需加载,别预载全部)

- `routing.md` — 完整路由矩阵(目标类型 / 用户意图 / 工具链)+ 跨域路径
- `tools-and-mcp.md` — 工具目录(分类)+ 官方安装指引 + MCP 服务清单(opt-in,不自动注册)
- `binary-reverse.md` — PE/ELF/Mach-O 静态逆向:IDA / Ghidra / radare2 / GDB 工作流
- `languages.md` — Go / Rust / .NET / Swift / WASM / Python 字节码 / 内核驱动 逆向要点
- `mobile-reverse.md` — Android(jadx/apktool/smali/Frida)+ iOS(class-dump/Objection)统一方法论、SSL pinning / root / 越狱检测绕过
- `js-web-reverse.md` — 前端签名/加密参数:观察→取证→运行时采样→Node 补环境复现;CDP/Hook、抓包/重放
- `firmware-iot.md` — binwalk/unblob 解包、ARM/MIPS、squashfs、UART/JTAG
- `patterns.md` — 壳/混淆/VM/反调试/反分析 识别 + 加密算法特征 + CTF 常见 pattern
- `pwn-exploit.md` — 栈/堆/ROP/ret2libc/kernel pwn:pwntools 工作流、本地通→远程稳定打通的工程差距
- `patch-diff-nday.md` — ghidriff/Diaphora/BinDiff、跨版本符号迁移、CVE 复现
- `pentest.md` — (授权)信息收集→扫描→Web 渗透:nmap/nuclei/sqlmap/ffuf/hydra/msf、WAF bypass、Burp
- `network-ad-c2.md` — (授权)内网/横向/AD/Kerberos/凭据/C2,含蓝队检测视角
- `llm-security.md` — OWASP LLM Top 10 / Agent 安全 / Prompt 注入测试(garak/PyRIT/promptfoo)
- `game-security.md` — Unity(IL2CPP/Mono)/ Unreal 逆向、内存分析、反作弊
- `malware-supplychain.md` — YARA/Sigma/IOC + sandbox/行为分析;Trivy/Syft/Gitleaks/OSV 供应链
- `ctf.md` — CTF 编排:按主导证据分流到 web/pwn/re/crypto/forensic/misc + writeup

## 深度层 references/(高保真,清洗即保留;概览不够时进这里)

上面的分域文件是**概览/导航层**;下面是从源仓库近原样移植、只剥了操纵/注入部分的**深度层**,信息密度高,按需读单文件:

- `field-journal/` — 30 条脱敏实战 writeup(完整执行链 + 踩坑表 + 关键命令),含 reverse/pentest/CTF/IoT 案例。开工前先查 `field-journal/_index.md` 看有无同类先例可复用。
- `playbooks/` — src-hunter 的 20 个漏洞猎杀 playbook(sqli/xss/ssrf/rce/file-upload/jwt/race/graphql/IDOR/内网后渗透 等,统计驱动、入口点全)+ `methodology/`(攻击优先级 / bypass 工具箱 / 证据纪律)。见 `playbooks/_index.md`。
- `ctf/` — 41 个 CTF competition 题型深度库(每类的识别、套路、技术参考)。见 `ctf/_index.md`。
- `deep/` — 两个高危进攻域的源深度移植:patch-diff(`patch-diff__*`,Patch Tuesday/diff 工具/根因)与 内网AD/C2(`adc2__*`,attack-chain/EDR/network-attack-defense)。概览见 `patch-diff-nday.md` / `network-ad-c2.md`,完整细节在此。见 `deep/_index.md`。

## 完成清单(交付前自检)

- [ ] 实际跑了流程并产出**可复现**的命令/脚本/PoC(不是只描述步骤)
- [ ] 逆向结论标注了地址/偏移/函数名(不是「某个函数」)
- [ ] 工具路径来自本机实际(没猜)
- [ ] 不确定的结论标了置信度;真实阻碍(WAF/目标下线/凭据过期)给了技术原因和下一步
- [ ] 报告/日志已脱敏;高危发现已告知用户
- [ ] (可选)把踩坑/可复用解法回写到本地知识库,不公开未脱敏内容
