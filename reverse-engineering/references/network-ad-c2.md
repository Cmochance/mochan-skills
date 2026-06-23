# 内网 / AD 域 / C2(授权红队 + 蓝队检测视角)

本域是**授权范围内**的内网与 Active Directory 安全评估的概念地图、工具盘点与检测视角。定位是"路由 + 科普 + 给检测建议",**不提供可直接运行的攻击命令、武器化 payload、或绕过特定 EDR 产品的实现**。每种技术尽量配一条蓝队检测/缓解,方便从攻防双向使用。

> 前提:仅在签约的红队/演练、自有域、靶场内做这类工作;出现越界信号(非授权真实域、扩面到指定范围外)立即停下与用户确认。攻击技术的操作细节按授权工程的 RoE 在受控环境内进行。

## 攻击链概念地图(用于定位"现在在哪一环")

```
初始立足点 → 信息收集/枚举 → 凭据获取 → 横向移动 → 权限提升 → 域控/持久化
        ↑___________________ 失败则换向、回到枚举 ____________________↓
```

定位任务在哪一环,再决定看哪段工具与检测。多数评估是"拿到一个低权立足点,看能否走到域管"。

## 各阶段:相关工具 + 蓝队检测视角

### 信息收集 / 枚举
- **工具**:BloodHound / SharpHound(攻击路径图)、NetExec(nxc,原 CrackMapExec,批量枚举)、ldapsearch、adidnsdump。
- **看什么**:域信任、ACL 错配、可 Kerberoast 账户、未约束/约束委派、ADCS 模板、本地管理员重用。
- **蓝队检测**:异常 LDAP 大批量查询、SharpHound 采集特征(短时间大量 LDAP/SAMR)、蜜罐对象/账户被访问。

### 凭据获取(概念 + 检测)
- **Kerberoasting**:请求服务账户的 service ticket、离线爆破弱口令 SPN 账户。**检测**:大量 TGS 请求(Event 4769)、RC4 加密票据请求异常、为多个 SPN 短时请求。**缓解**:服务账户用强随机口令 / gMSA、监控 4769。
- **AS-REP Roasting**:针对"不要求预认证"的账户。**检测**:Event 4768 中 preauth 未启用账户的 AS-REQ。**缓解**:全员开 Kerberos 预认证。
- **凭据转储(本地)**:从内存/SAM/LSASS 提取(Mimikatz 类)。**检测**:LSASS 异常进程访问(Sysmon Event 10)、可疑句柄、Credential Guard 命中。**缓解**:开 Credential Guard、限制本地管理员、LSA 保护。
- **NTLM relay / 强制认证(Coercer 类)**:诱导机器账户认证后中继。**检测**:异常 SMB/HTTP 认证流、PetitPotam 等触发特征。**缓解**:开 SMB 签名 / LDAP 签名+channel binding、关不必要的 WebDAV/MS-RPRN。

### 横向移动(概念 + 检测)
- **方式**:Pass-the-Hash / Pass-the-Ticket、WMI / WinRM / SMB(PsExec 类)、SCM 远程服务。工具盘点:Impacket 套件、NetExec、Evil-WinRM。
- **蓝队检测**:异常远程服务创建(Event 7045)、横向登录(4624 type 3)异常源、同账户在多主机短时认证、命名管道异常。
- **缓解**:LAPS(本地管理员密码随机化)、分层管理(Tier 0/1/2)、限制管理协议来源。

### 权限提升 / 域控
- **概念面**:DCSync(模拟 DC 同步拿哈希)、ADCS 证书模板滥用(ESC1-ESC8 类配置缺陷)、未约束委派滥用、GPO 滥用。工具盘点:Impacket、Certipy、PowerView/SharpView。
- **检测**:非 DC 发起的目录复制请求(DCSync → Event 4662 复制权限调用)、异常证书签发(ADCS CA 日志)、敏感组变更(4728/4732)。
- **缓解**:审计 ADCS 模板与 CA 权限、限制复制权限、监控 DPAPI/委派配置变更。

### 持久化
- **概念面**:黄金/白银票据、Skeleton Key、ADCS 持久证书、计划任务/服务/启动项、AdminSDHolder/ACL 后门。
- **检测**:异常 TGT 生命周期/加密类型、krbtgt 使用异常、SDProp 还原异常 ACL、计划任务创建(4698)。
- **缓解**:定期双重重置 krbtgt、ACL 基线比对、特权账户行为基线。

## C2 框架(盘点 + 检测面)
- **盘点**:Sliver、Havoc、Cobalt Strike、Mythic 等 —— 用于授权红队的指挥控制与后渗透编排。功能上覆盖 beacon 通信、任务下发、横向、文件操作。
- **蓝队检测面**(防御评估重点):
  - 网络:beacon 周期性回连(jitter/sleep 特征)、可疑 TLS JA3/SNI、DNS 隧道异常、域前置。
  - 主机:进程注入/反射加载、异常父子进程链、命名管道、未签名模块注入。
  - 用 Suricata/Zeek + Sysmon + EDR 遥测做交叉关联;C2 流量画像匹配公开 IOC/规则集。

## EDR / AV 规避(概念 + 检测,不含可运行实现)
- **存在哪些手法(概念)**:用户态 hook 摘除(unhook)、直接/间接系统调用、AMSI/ETW 遥测致盲、未签名/反射加载。这些在授权评估中用于检验 EDR 覆盖盲区。
- **防御/检测视角(本域重点)**:
  - 监控 ntdll 内存完整性(hook 被改写)、ETW 提供者被禁用、AMSI 被 patch 的内存特征。
  - 内核遥测(ETW-Ti)、用户态+内核态双源交叉,降低单点被致盲的影响。
  - 评估输出应是"EDR 在哪些遥测点有盲区 + 怎么补",而不是"怎么绕过它"。

## 工具盘点速查

| 类别 | 工具 |
|---|---|
| 路径分析 | BloodHound / SharpHound |
| 枚举/横向 | NetExec(nxc)、Impacket、Evil-WinRM、PowerView |
| 凭据 | Mimikatz(目标侧)、Rubeus(Kerberos)、Certipy(ADCS) |
| 强制认证/中继 | Coercer、Impacket-ntlmrelayx |
| C2 | Sliver、Havoc、Cobalt Strike、Mythic |
| 蓝队/检测 | Sysmon、Zeek/Suricata、Sigma 规则、ELK/EDR 遥测 |

## 纪律与边界
- 所有动作在授权 RoE 与受控环境内;高危发现立即告知用户、等指示,不擅自扩面。
- 报告脱敏(主机名/IP/凭据占位化)。
- 本 skill 提供编排判断与检测建议;具体武器化实现不在此文件,按授权工程在受控环境处理。

## 深度(源移植,完整细节)

本文是概念地图 + 检测视角的概览。完整深度在 `deep/`(源仓库 attack-chain / edr-bypass-re / network-attack-defense 近原样移植,授权工程内使用):
- `deep/adc2__attack-chain.md` + `deep/adc2__attack-playbooks.md` — 完整攻击链编排与各阶段 playbook
- `deep/adc2__evasion-cheatsheet.md` + `deep/adc2__edr-bypass.md`(+ `adc2__hook-survey.md` / `adc2__unhook-techniques.md` / `adc2__telemetry-blinding.md`)— EDR/AV 规避技术清单(防御评估用)
- `deep/adc2__network-attack-defense.md` — 内网/AD/横向/提权/凭据/C2 综合参考

## 关联
- Web/主机渗透前置 → `pentest.md`
- EDR 规避的二进制层机制(研究)→ `binary-reverse.md` / `patterns.md`
- 恶意流量/样本检测规则 → `malware-supplychain.md`
- 完整案例 → `field-journal/_index.md`
