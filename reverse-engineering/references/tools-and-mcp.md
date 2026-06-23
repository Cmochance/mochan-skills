# 工具目录 + 安装指引 + MCP 服务(opt-in)

工具按需安装,**给出官方命令让用户装,或在用户同意下装**。不自动改全局配置、不自动往 `~/.claude/mcp.json` 注册 MCP。工具路径以本机实际为准 —— 本机已装哪些、装在哪,记到本 skill 目录的 `config.local.json`(从 `config.example.json` 复制填写,不进版本库),用之前先看它,别猜路径。

## 安装姿态(与上游 reverse-skill 的区别)

上游 `bootstrap-reverse.ps1/.sh` 会自动安装工具 + 自动写 MCP 配置 + 刷新「tool-index」。本 skill **不照搬自动化**:
- 缺工具 → 输出对应平台官方安装命令,让用户确认 / 自己执行。
- MCP 服务 → 给出注册片段(写到客户端 MCP 配置),由用户决定是否启用,而非默默注册。
- 装完后把实际路径/版本记进 `config.local.json` 当本机事实源。

## 静态逆向

| 工具 | 用途 | macOS | Linux/Kali |
|---|---|---|---|
| jadx | APK/DEX → Java | `brew install jadx` | apt 或 GitHub release ZIP |
| apktool | APK 解包/重打包/smali | `brew install apktool` | `apt install apktool` 或官方 jar |
| radare2 | CLI 反汇编/分析/patch | `brew install radare2` | 优先源码/GitHub,apt 兜底 |
| Ghidra | 免费反编译器(需 Java) | `brew install --cask ghidra` | GitHub release ZIP / Flatpak |
| IDA Pro | 商业反编译(配 ida-pro-mcp) | 官方安装 | 官方安装 |
| adb | Android 平台工具 | `brew install android-platform-tools` | `apt install adb` |

## 动态分析 / 插桩

| 工具 | 用途 | 安装 |
|---|---|---|
| frida / frida-tools | 运行时 Hook(Android/iOS/桌面) | `pipx install frida-tools` |
| Objection | Frida 之上的移动端运行时工具箱 | `pipx install objection` |
| GDB + GEF/pwndbg | 调试 + pwn | 系统 gdb + GEF/pwndbg 脚本 |
| angr / Qiling / Unicorn | 符号执行 / 模拟执行 | `pipx install angr` 等 |

## pwn / exploit

`pip install pwntools`、ROPgadget(`pipx install ropgadget`)、Ropper、one_gadget(gem)、libc-database(clone)、qemu-system(内核调试)。

## patch-diff / N-day

ghidriff(`pipx install ghidriff`)、Diaphora(clone + IDA)、BinDiff(官方)。

## (授权)渗透工具

| 工具 | 用途 | 安装 |
|---|---|---|
| nmap | 端口/服务扫描 | `brew install nmap` / `apt install nmap` |
| nuclei | 模板化漏洞扫描 | `brew install nuclei` / GitHub release |
| sqlmap | SQL 注入 | pipx / clone |
| ffuf / gobuster | 目录/参数爆破 | `brew install ffuf` / go install |
| hashcat / john / hydra | 口令破解 | brew / apt |
| metasploit / impacket | 利用框架 / 协议库 | 官方 / `pipx install impacket` |
| SecLists | 字典库 | `git clone https://github.com/danielmiessler/SecLists` |
| BurpSuite | Web 代理/拦截/扫描 | 官方安装 |
| ProxyCat | 代理池/IP 轮换 | `pipx install git+https://github.com/honmashironeko/ProxyCat.git` |

## 内网 / AD / C2(授权)

BloodHound、Impacket、NetExec(nxc)、Certipy、Coercer、Mimikatz(目标侧);C2 框架 Sliver / Havoc / Cobalt Strike 按授权使用。

## LLM / Agent 安全

`pipx install garak`、PyRIT(`pip install pyrit`)、promptfoo(`npm i -g promptfoo`)。

## game / 移动 / 固件

Cheat Engine、x64dbg、ReClass.NET、IL2CPP Dumper、dnSpy(game);class-dump、Hopper(iOS);binwalk(`pipx install binwalk`)、unblob、EMBA、squashfs-tools(固件)。

## 恶意样本 / 供应链

YARA(`brew install yara`)、Sigma、Trivy、Syft、Gitleaks、OSV-Scanner(brew / GitHub release)。

## MCP 服务清单(opt-in —— 用户同意后再注册到客户端 MCP 配置)

| 服务 | 端口 | 用途 | 启动 / 注册 |
|---|---|---|---|
| ida-pro-mcp | 13337+ | IDA Pro 逆向工具 over MCP | `pipx install 'git+https://github.com/mrexodia/ida-pro-mcp.git'` → `ida-pro-mcp --install`(选 Streamable HTTP + Global)→ 重启 IDA |
| ghidra-mcp | 8765 | Ghidra 反编译 over MCP | 装 Ghidra MCP 插件/server,GUI 启动后监听 |
| jshookmcp | stdio | JS Hook/CDP/Network/AST | MCP 配 `{"command":"npx","args":["-y","@jshookmcp/jshook@latest"]}` |
| anything-analyzer | 23816 | 浏览器自动化 + HTTP 抓包 | clone + `pnpm install` + `pnpm dev`;MCP 配 `{"url":"http://localhost:23816/mcp"}` |
| burpsuite mcp | 9876 | Burp 全工具 over MCP | 构建 burp-mcp 扩展 jar 并在 Burp Extensions 加载 |

> 注册示例只给片段,实际写入哪个 MCP 配置文件、是否启用,由用户决定。端口冲突时问用户实际端口再改。
