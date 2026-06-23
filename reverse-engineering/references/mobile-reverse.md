# 移动端逆向统一方法论(Android + iOS)

Android(jadx / apktool / smali / adb / Frida / .so 联动)+ iOS(class-dump / Hopper / Objection / Frida)的统一工作流。覆盖四阶段、SSL Pinning / Root / 越狱 / 反调试绕过、加密算法与密钥提取、OWASP MASTG 要点。

> 仅对自有 app 或已获授权的目标操作。绕过证书校验、改包、Hook 等动作只在合法授权范围内进行。

## 工具链速查

| 工具 | 平台 | 用途 |
|------|:--:|------|
| jadx / JADX-GUI | A | DEX → Java 反编译阅读 |
| apktool | A | 解包/重打包、改 smali 与资源、读改 Manifest |
| dex2jar + JD-GUI | A | DEX → JAR 另一条反编译路径 |
| baksmali / smali | A | Dalvik 字节码反汇编/回编 |
| adb | A | 设备连接、安装、logcat、pull/push |
| Frida / frida-trace | A+I | 运行时动态插桩 |
| Objection | A+I | Frida 增强 REPL,常见绕过无需写脚本 |
| MobSF | A+I | 自动化 SAST + DAST |
| Ghidra | A+I | 多架构 .so / Mach-O 反编译 |
| radare2 / Cutter / r2frida | A+I | CLI 快速侦察 + Frida 集成 |
| IDA | A+I | .so / Mach-O 深度分析、类型恢复 |
| class-dump | I | 导出 ObjC 类与方法声明 |
| Hopper | I | iOS 反汇编(自动还原 Swift) |
| frida-ios-dump / Clutch | I | App Store 加密二进制解密 |
| jtool2 / otool / nm / lipo | I | Mach-O 头部、依赖、符号、瘦身 |
| Burp Suite / mitmproxy | A+I | HTTP(S) 拦截与改包 |

参考机器实测可用版本示例:jadx 1.5.5、apktool 3.0.2、frida 17.9.6(版本以本机实际为准,勿照抄)。

## 四阶段工作流

### Phase 1 — 信息收集

Android:
- APK 获取(Google Play / APKMirror / `adb pull`)
- Manifest 分析:权限、导出组件、intent-filter、`allowBackup` / `debuggable` 标志
- androguard 解析组件 / 权限 / 签名;APKLeaks 扫硬编码 API Key / Token / Secret
- 加固检测:是否加壳(360 / 腾讯乐固 / 梆梆 / 爱加密 / 易盾 / 娜迦)
- `lib/` 下是否有关键 `.so`

iOS:
- IPA 获取(App Store / ipatool / Apple Configurator)
- App Store 二进制为加密 FAT,需先解密(frida-ios-dump / Clutch / dumpdecrypted)
- Info.plist 分析:ATS 配置、URL Scheme、LSApplicationQueriesSchemes
- class-dump 导出 ObjC 类结构;判断 Swift/ObjC 混淆程度

### Phase 2 — 静态分析

Android:
```bash
jadx -d jadx_out app.apk                 # DEX → Java
jadx --single-class com.x.LoginActivity -d out app.apk
jadx --deobf -d jadx_out app.apk         # 混淆名去模糊
apktool d app.apk -o apktool_out         # smali + 资源 + Manifest
apktool b apktool_out -o rebuilt.apk     # 重建
```
关键搜索词:`login` `sign` `encrypt` `cipher` `token` `root` `certificate` `trust` `okhttp` `retrofit` `webview` `http://`。先在 jadx 读懂高层逻辑,Java 不完整或要 patch 时再切 smali。

iOS:
```bash
class-dump -H TargetBinary -o headers/   # 导出 ObjC 头
otool -l Bin | grep crypt                # 加密状态(cryptid)
otool -L Bin                             # 动态库依赖
nm -g Bin                                # 导出符号
swift-demangle <mangled>                 # Swift 符号还原
lipo -info Bin; lipo Bin -thin arm64 -output Bin_arm64   # FAT 瘦身
```
Swift name mangling 形如 `$s10ModuleName5ClassC6method...`,用 swift-demangle / Hopper 自动还原。

### Phase 3 — 动态分析(Frida / Objection)

```bash
frida-ps -U                                          # 列设备进程
frida -U -f com.app -l hook.js                       # spawn 并注入
frida-trace -U -f com.app -j '*Cipher*!*'            # 追踪加密
frida-trace -U -f com.app -j '*OkHttp*!*'            # 追踪 HTTP
frida-trace -U -f com.app -i 'Java_*'                # 追踪 native JNI
```

Objection(常见绕过无需写脚本):
```bash
objection -g com.app explore
android root disable / ios jailbreak disable
android sslpinning disable / ios sslpinning disable
android keystore list / ios keychain dump
android hooking list activities / android hooking watch class com.app.Main
android clipboard monitor / ios pasteboard monitor
env / ls / sqlite connect <db> / file download <path>
```

免 Root/越狱部署(Frida Gadget):把 `frida-gadget.*` 注入进 APK/IPA 再重签安装。
```bash
objection patchapk --source app.apk            # 自动注入 Gadget + 重签
objection patchapk --source app.apk --skip-resources
# 手动:apktool d → 拷 libfrida-gadget.so 进 lib/arm64-v8a/ →
#       smali 注入 System.loadLibrary("frida-gadget") → apktool b → uber-apk-signer
```

frida-server 部署(Root 设备):
```bash
adb push frida-server /data/local/tmp/ && adb shell chmod 755 /data/local/tmp/frida-server
adb shell su -c /data/local/tmp/frida-server &
```

### Phase 4 — 网络分析

- Burp Suite / mitmproxy 拦截改包;Wireshark 看 PCAP
- 证书安装:Android 7+ 用户证书不被默认信任,需改 network_security_config 或 Frida 绕过;Magisk + MoveCert 可把用户证书提升为系统证书
- SSL Pinning 绕过见下;VPN 抓包(HttpCanary 等)免 root 免代理但绕不过 pinning
- 关注 WebSocket / gRPC、URL 参数中的敏感数据、请求签名 / nonce / timestamp 防重放

## SSL Pinning 绕过

最简:Objection `android sslpinning disable` / `ios sslpinning disable`(自动 Hook 下列多层)。

Android 多层(逐层覆盖):
```javascript
Java.perform(function() {
    // 1. OkHttp3 CertificatePinner
    try {
        var CP = Java.use("okhttp3.CertificatePinner");
        CP.check.overload('java.lang.String', 'java.util.List').implementation = function() {};
    } catch(e) {}

    // 2. Conscrypt TrustManagerImpl(返回未校验链)
    try {
        var TMI = Java.use("com.android.org.conscrypt.TrustManagerImpl");
        TMI.verifyChain.implementation = function(chain) { return chain; };
    } catch(e) {}

    // 3. WebView SSL Error → proceed
    try {
        var H = Java.use("android.webkit.SslErrorHandler");
        H.proceed.implementation = function() { return this.proceed(); };
    } catch(e) {}

    // 4. Network Security Config(Android 7+,放行明文)
    try {
        var NSC = Java.use("android.security.net.config.NetworkSecurityConfig");
        NSC.isCleartextTrafficPermitted.implementation = function() { return true; };
    } catch(e) {}
});
// 5. Native SSL(OpenSSL/BoringSSL):Hook SSL_get_verify_result → 返回 X509_V_OK(0)
```

框架对应表:Retrofit 走 OkHttp 底层(同上);Volley → `HurlStack` SSL 工厂;React Native → `OkHttpClientProvider`;Flutter 见下。

iOS 多层:
```javascript
// NSURLSession:SecTrustEvaluate → kSecTrustResultProceed
var SecTrustEvaluate = Module.findExportByName("Security", "SecTrustEvaluate");
Interceptor.replace(SecTrustEvaluate, new NativeCallback(function(trust, result) {
    Memory.writeU32(result, 1); // kSecTrustResultProceed
    return 0;                   // errSecSuccess
}, 'int', ['pointer', 'pointer']));
// Alamofire → Hook ServerTrustManager.evaluate;AFNetworking → AFSecurityPolicy;libcurl → 替换验证回调
```

Flutter 专项(走自己的 BoringSSL,不读系统证书):需在 `libflutter.so` 中定位 `ssl_verify_peer_cert` 的特征码,`Interceptor.replace` 使其返回成功;reFlutter 工具可 patch libflutter.so。

## Root / 越狱 / 模拟器 / 反调试绕过

### 检测层次模型
- Layer 1 静态(安装/启动时):包管理器(Cydia/apt/Magisk)、文件(su/busybox/frida-server)、属性(ro.debuggable/ro.secure)
- Layer 2 运行时(持续):进程(frida-server/magiskd)、端口(27042 frida 默认)、内存(/proc/self/maps 注入痕迹)、调用帧
- Layer 3 环境(按需):ptrace TracerPid、/proc/self/status、build.prop test-keys、直接 syscall 绕过 libc

### Android Root 检测

| 检测库/方式 | 绕过 |
|------|------|
| RootBeer(多种组合) | Hook 每个检测方法返回 false |
| `File.exists()` 查 su/Superuser/magisk/busybox/xposed | Hook 命中黑名单返 false |
| `Runtime.exec("su"/"which")` | Hook 拦截抛 IOException |
| `/proc/self/mounts`、`/data/adb/` | Hook 文件读取过滤,或 Hook opendir/access |
| SafetyNet / Play Integrity | Magisk Hide / Zygisk + Shamiko / Trickystore + PIF(运行环境层,非脚本) |
| native syscall 读 /proc | Hook syscall 或修改 /proc 挂载 |

```javascript
Java.perform(function() {
    // RootBeer 全检测方法
    var RB = Java.use("com.scottyab.rootbeer.RootBeer");
    ["isRooted","isRootedWithBusyBox","checkSuExists","detectRootManagementApps",
     "detectPotentiallyDangerousApps","detectTestKeys","checkForDangerousProps",
     "checkForRWPaths"].forEach(function(m){ RB[m].implementation = function(){ return false; }; });

    // File.exists 黑名单
    var File = Java.use("java.io.File");
    var bl = ["su","superuser","magisk","busybox","xposed"];
    File.exists.implementation = function() {
        var p = this.getAbsolutePath().toLowerCase();
        for (var i=0;i<bl.length;i++) if (p.indexOf(bl[i])!==-1) return false;
        return this.exists();
    };

    // Build.TAGS / PackageManager 隐藏 root 包
    Java.use("android.os.Build").TAGS.value = "release-keys";
    var PM = Java.use("android.content.pm.PackageManager");
    PM.getPackageInfo.overload('java.lang.String','int').implementation = function(pkg, f) {
        if (pkg.includes("magisk")||pkg.includes("frida")||pkg.indexOf("xposed")!==-1)
            throw Java.use("android.content.pm.PackageManager$NameNotFoundException").$new();
        return this.getPackageInfo(pkg, f);
    };
});
```

### iOS 越狱检测

检测分类与对应 Hook:
1. 文件系统(`/Applications/Cydia.app`、`/var/lib/apt`、`/bin/bash`、`/usr/sbin/sshd`、`/Library/MobileSubstrate`)→ Hook `NSFileManager.fileExistsAtPath:` 命中返 NO
2. 沙箱逃逸(`fork()` 成功 / `system()`)→ Replace `fork` 返回 -1
3. dyld 注入(`_dyld_get_image_count` 超阈值)→ 限制返回值到合理范围
4. Scheme(`cydia://` via `canOpenURL:` / LSApplicationWorkspace)→ Hook 对越狱 scheme 返 NO
5. 签名校验(`MISValidateSignature`)→ onLeave `retval.replace(0)`

```javascript
// fork → -1
Interceptor.replace(Module.findExportByName("libSystem.B.dylib","fork"),
    new NativeCallback(function(){ return -1; }, 'int', []));

// fileExistsAtPath: 命中越狱路径返 NO
var fm = ObjC.classes.NSFileManager.defaultManager();
Interceptor.attach(fm["- fileExistsAtPath:"].implementation, {
    onEnter: function(args){ this.path = new ObjC.Object(args[2]).toString(); },
    onLeave: function(retval){
        if (/Cydia|apt|sshd|bash|MobileSubstrate/.test(this.path)) retval.replace(0);
    }
});
```

### 反调试绕过

Android:`Debug.isDebuggerConnected` Hook 返 false;native `ptrace(PTRACE_TRACEME)` Hook 返 0;`/proc/self/status` 的 TracerPid 经 fopen/fgets Hook 伪造为 0。

iOS:`ptrace(PT_DENY_ATTACH=31)` Hook 直接 return 0 忽略;`sysctl` onLeave 清 kinfo_proc 的 `P_TRACED` 位;`getppid` 检测(调试时父进程 != launchd/1)需配合 Hook。Frida 在 PT_DENY_ATTACH 生效前注入,或用 debugserver。

### 模拟器检测(Android)
伪造 `Build.FINGERPRINT/MODEL/MANUFACTURER/BRAND/DEVICE/PRODUCT/HARDWARE` 为真机值;`TelephonyManager.getDeviceId/getSubscriberId/getSimSerialNumber` 返回假但合法值。

## 移动端加密提取(密钥 / IV / 算法)

核心思路:不去逆算法本身,直接 Hook 标准库 API 拿明文密钥、IV、输入输出。

Android — Hook `Cipher` / `SecretKeySpec` / `IvParameterSpec` / `MessageDigest` / `Mac`:
```javascript
Java.perform(function() {
    var Cipher = Java.use("javax.crypto.Cipher");
    Cipher.getInstance.overload('java.lang.String').implementation = function(a) {
        console.log("[Cipher] algo=" + a); return this.getInstance(a);
    };
    Cipher.doFinal.overload('[B').implementation = function(input) {
        console.log("[doFinal] in=" + bytesToHex(input));
        var out = this.doFinal(input);
        console.log("[doFinal] out=" + bytesToHex(out)); return out;
    };
    Java.use("javax.crypto.spec.SecretKeySpec").$init.overload('[B','java.lang.String')
        .implementation = function(k, a){ console.log("[Key] "+a+" "+bytesToHex(k)); this.$init(k,a); };
    Java.use("javax.crypto.spec.IvParameterSpec").$init.overload('[B')
        .implementation = function(iv){ console.log("[IV] "+bytesToHex(iv)); this.$init(iv); };
    var Mac = Java.use("javax.crypto.Mac");
    Mac.init.overload('java.security.Key').implementation = function(key){
        console.log("[HMAC key] "+bytesToHex(key.getEncoded())); this.init(key);
    };
});
function bytesToHex(b){ if(!b) return "null"; var h=[]; for(var i=0;i<b.length;i++) h.push(('0'+(b[i]&0xFF).toString(16)).slice(-2)); return h.join(''); }
```

iOS — Hook CommonCrypto `CCCrypt`:
```javascript
Interceptor.attach(Module.findExportByName("libcommonCrypto.dylib","CCCrypt"), {
    onEnter: function(args) {
        console.log("CCCrypt op=" + args[0] + " alg=" + args[1]);   // op: 0=encrypt 1=decrypt
        console.log("Key:\n" + hexdump(args[3], { length: args[4].toInt32() }));
    }
});
```

## Native .so / JNI 分析联动

何时从 Java 切到 .so:Java 层只是 JNI 包装、`System.loadLibrary()` 后关键逻辑消失、核心签名/证书校验/风控落在 native。

```bash
unzip app.apk lib/arm64-v8a/*.so -d extracted/
file libxxx.so; rabin2 -I libxxx.so
nm -D libxxx.so | grep -i java          # 找 JNI 导出
```
JNI 注册两种:静态 = 函数名 `Java_包名_类名_方法名`;动态 = `JNI_OnLoad` 里调 `RegisterNatives`(从该函数表提取真实 native 地址)。IDA 技巧:导入 `jni.h` 类型库、把第一参数标注为 `JNIEnv*`(`env->FindClass` 等自动识别)、在 JNIEnv vtable 对应 offset 找 RegisterNatives 调用提取函数数组。

Frida 联动:`Module.findBaseAddress("lib.so").add(0x偏移)` 配合 `Interceptor.attach` Hook 任意地址;`Thread.backtrace(...).map(DebugSymbol.fromAddress)` 打调用栈;`Memory.scan` 搜内存、`Memory.patchCode` + `Arm64Writer` 改指令(如 putNop)。

## 加固脱壳(Android)

识别特征与脱壳:360 加固 `libjiagu.so`/`com.stub.StubApp`、腾讯乐固 `libshell*.so`、梆梆 `libDexHelper.so`/`com.secneo.apkwrapper`、爱加密 `libexec.so`、易盾 `libnesec.so`、娜迦 `libnaga.so`。

脱壳方法:
- FART(ART 主动调用脱壳,刷 ROM 或 Frida 版)
- Frida DEX Dump:在 `DexFile::OpenMemory` 或枚举 ClassLoader 处 dump 内存 dex
- BlackDex:免 root,安装 APK 选目标脱壳
- 手动:`Java.enumerateClassLoaders` 找应用 ClassLoader → 取 DexFile → 读内存区域保存

```javascript
Java.perform(function() {
    Java.enumerateClassLoaders({
        onMatch: function(loader) {
            try {
                var pl = Java.cast(loader, Java.use("dalvik.system.BaseDexClassLoader")).pathList.value;
                pl.dexElements.value.forEach(function(e){
                    var df = e.dexFile.value; if (df) console.log("[DEX] " + df.getName());
                });
            } catch(e) {}
        }, onComplete: function(){}
    });
});
```

## 跨框架逆向要点

- React Native:`assets/index.android.bundle` 是 JS 源(格式化后搜 API/密钥/签名);Hermes 字节码 `.hbc` 用 hermes-dec 反编译;Frida Hook Java 层 ReactBridge。
- Flutter:Dart AOT 编译进 `libapp.so` 无法直接反编译;reFlutter patch + Doldrums 解析 snapshot 恢复类/函数;Flutter 不走系统代理,抓包需特殊 SSL 处理。

## OWASP MASTG 检查清单(精选)

Manifest:`debuggable`/`allowBackup`/`exported` 组件/自定义权限 protectionLevel(应 signature)/deeplink scheme 可劫持/`usesCleartextTraffic`/minSdk 过低。

代码:硬编码密钥(搜 key/secret/password/api_key)、`Random` 而非 `SecureRandom`、ECB/DES/MD5 用于密码、WebView `setJavaScriptEnabled`+`addJavascriptInterface`(RCE)、rawQuery 拼接(SQLi)、ContentProvider openFile 路径遍历、Log 泄露、剪贴板与隐式 Intent 泄露。

数据存储:SharedPreferences 明文(`adb shell cat /data/data/pkg/shared_prefs/*.xml`)、未加密 SQLite(`adb pull .../databases/`)、外部存储、`allowBackup`(`adb backup`)、密码框 `inputType=textPassword`、敏感页 `FLAG_SECURE`。优先用 EncryptedSharedPreferences / SQLCipher / Android Keystore。

网络:全程 HTTPS、SSL Pinning、不接受自签名、token 过期、请求签名防篡改、nonce/timestamp 防重放、敏感数据不进 URL。

认证授权:弱密码、无登录锁定、token 不过期(登出后重放)、越权(改 user_id)、验证码可爆破、OAuth redirect_uri 可篡改、BiometricPrompt / device_id 绑定可 Hook 绕过。

## 推荐工作流(快速 triage)

1. 解包 + Manifest 审计(`apktool d`,看四标志)
2. Java 快速审计(`jadx -d`,搜密钥/明文 URL)
3. 网络:配代理操作 APP 看明文/弱加密
4. 存储:`adb shell` 看 shared_prefs 与 databases
5. 动态:Frida 先 Hook 打印参数/返回值再决定是否改返回值;先 Java 层再 native

纪律:别一上来盲改 smali;没看 Manifest 和主入口前不写 Hook;Java 反编译不完整 ≠ 不可分析;.so 明显承载核心逻辑时别死磕 Java。最终交付说明:入口组件与关键类、核心逻辑落在 Java/smali/.so 哪层、已确认敏感点(登录/签名/root/SSL/WebView/JNI)、做了哪些 patch 或 Hook。

## 标注纪律

- 任何对返回值/参数的修改、绕过、改包,在产物里标注清楚改了什么、Hook 了哪个类/方法/导出函数,便于复盘与回退。
- 区分"观察"(打印)与"干预"(replace/改返回):先观察确认再干预。

## 参考资源

- OWASP MASTG: https://mas.owasp.org/
- Frida 官方文档: https://frida.re/docs/ ; CodeShare: https://codeshare.frida.re/
- awesome-frida: https://github.com/dweinstein/awesome-frida
- FridaBypassKit(集成 root/SSL/模拟器/反调试绕过): https://github.com/okankurtuluss/FridaBypassKit
- httptoolkit/frida-interception-and-unpinning(直接 MitM 全部 HTTPS): https://github.com/httptoolkit/frida-interception-and-unpinning
- Objection: https://github.com/sensepost/objection ; r2frida: https://github.com/nowsecure/r2frida
- Android Security Awesome: https://github.com/ashishb/android-security-awesome
