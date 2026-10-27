# K210 人体检测 / 跟踪 / 区域告警（Yahboom CanMV 板）

基于嘉楠官方 `canmv_examples`（98-KPU_NEW/head_body_detect）重写，在 **Yahboom K210（CanMV_Yahboom V2.1.1 固件）** 上实测跑通。

## 已验证的结果

| 测试 | 结果 |
|---|---|
| 滑雪单人图（板载 KPU 推理） | 检出 1 人，89%，框位置精准 |
| 棒球多人图 | 检出 2 人（投手 + 击球手，各 70%） |
| 实时摄像头 30 帧冒烟测试 | **5.2 FPS**，零崩溃，干净退出 |
| **真机实拍（真人）** | 检出置信度 **0.70~0.93**，跟踪 ID 稳定，`ALARM` 触发 |
| **开机自启** | 上电自动跑检测，Ctrl-C 可中断回 REPL |
| **7 分钟无人值守** | 全程无重启、无崩溃，结束时仍在跑 |
| **模型缺失自愈** | 删掉模型后上电，自动退回"预览模式"：LCD 照样出画面，板子不崩不进重启循环 |

结果图：`testimgs/out785_big.png`、`testimgs/out2153_big.png`（板上画框后回传的）。

## 主程序 `body_detect.py`

在官方例程基础上多了这些（都是为实战加的）：

- **多人跟踪 + 稳定 ID**：官方例程每帧重新编号（框会跳号），这里给每个目标分配固定 `#ID`
- **区域入侵告警**：人进入黄框区域并持续 N 帧 → 串口输出 `ALARM person_in_zone`，框变橙色，带冷却防刷屏
- **累计人次统计**：屏幕右上角 `N=当前 T=累计`
- **自动适配新旧 KPU API**：本板是旧版（`load_kmodel/init_yolo2`），换新版固件也能跑
- **内存顺序修正**：先加载模型、后开 lcd（见下方"坑"）

### 调参（文件顶部配置区）

| 参数 | 说明 |
|---|---|
| `MODE` | `BODY`=人体，`HEAD`=人头 |
| `THRESHOLD` | 置信度阈值，默认 0.7，更灵敏调 0.5 |
| `NMS` | 重叠框抑制 |
| `TRACK_MAX_DIST` | 前后帧同一目标的最大位移，人走得快就调大 |
| `ALERT_X/Y/W/H` | 告警区（默认画面中间 1/3 竖条） |
| `ALERT_FRAMES` / `ALERT_COOLDOWN` | 告警灵敏度 / 冷却 |
| `HMIRROR` | 画面左右镜像。**本板默认 False**，设 True 画面会左右反 |
| `VFLIP` | 画面上下翻转。哪天发现画面是倒的，把它设 True |
| `DIST_ENABLE` | 距离估算开关 |
| `PERSON_H_M` | 被检测者的真实身高（米），默认 1.70 |
| `FOCAL_PX` | 焦距（像素），**需要标定一次**，见下 |
| `DIST_SMOOTH` | 距离平滑系数，0.35 默认；调小更稳、调大更跟手 |
| `MODEL_MISSING_FATAL` | 模型加载失败时是否直接抛错。**默认 False**（回退预览模式，别改） |
| `WDT_ENABLE` | 硬件看门狗开关，**默认开**，强烈建议别关 |
| `WDT_TIMEOUT_MS` | 多久没喂狗就硬复位，默认 30000 |
| `HEARTBEAT_SEC` | 心跳文件间隔秒数，0=关。排查卡死时设 20 |

### 距离估算（单目，粗略）

原理是针孔模型：**距离 = 人真实身高 × 焦距(像素) ÷ 画面里框高(像素)**。

**必须先标定一次**，否则误差可达 ±30%。标定只要一步：

1. 拿卷尺量好，站在离镜头 **D 米**的正面位置，站直不动，等屏幕出现你自己的框
2. 记下屏幕/串口显示的距离 `D_show`
3. 改配置区：`FOCAL_PX = FOCAL_PX × D ÷ D_show`

> 例：站在真实 **2.0 米**处，屏幕显示 **4.9m**
> → 新 FOCAL_PX = 277 × 2.0 / 4.9 = **113**

**什么时候不能信：**
- 人**头顶被画面切掉**（框贴着上边缘）→ 框高偏小 → 距离被**高估**。程序对这种情况显示 `>3.3m`
- 只拍到半身 / 蹲着 / 弯腰 → 同理
- 多人时每个人的身高不同，`PERSON_H_M` 只按一个人设，换人会有偏差
- 摄像头有俯仰角（比如架高往下拍）时误差会明显变大

### 串口输出格式

```
DET n=2 total=5 | #1 x138,y107,w92,h107,0.70,C ; #3 x89,y0,w32,h42,0.71,L,HOT
ALARM person_in_zone n=1 frame=213
```
`C/L/R` = 画面中/左/右，`HOT` = 处在告警区内，`h107` = 框高像素（标定用），`d1.8` = 估算距离（米）。

## 模型坏了会怎样：预览兜底（别让板子死）

**这是踩过的最坑的一个坑。** 模型文件传了一半 / flash 写坏时，老版本会在 `main()` 里直接抛异常：

```
异常 -> 看门狗复位 -> main.py 重跑 -> 又抛异常 -> 又复位 -> ...
```

表现就是**无限重启循环，LCD 一直黑着或者很暗，摄像头永远不更新**，
你会以为"板子挂了/摄像头坏了"，其实只是模型坏了。

现在不会了。加载模型失败时自动降级：

```
[模型] 加载失败: OSError('[BODY] 找不到模型文件...')
[模型] 已回退到预览模式(画面照上, 只是不检测)。把模型传好再上电即自动恢复。
[CANMV]: sensor id = 45
[CANMV]: find gc2145
开始实时检测，Ctrl-C / 停止键退出
```

- 画面正中显示 **`NO MODEL`** 横幅，串口报 `PREVIEW no_model frame=N`
- 帧号在涨 = 摄像头和 LCD 都好着，问题 100% 在模型文件
- 模型传好、重上电，**自动恢复检测**，不用改任何东西

想看纯画面不想检测：把配置区 `MODE` 改成 `"PREVIEW"`。

## 稳定性：看门狗兜底（重要）

这块板子的固件**本身不稳**。实测抓到过一次固件级崩溃：

```
开始实时检测，Ctrl-C / 停止键退出
[CanMV]:SPIFFS Error Code -10002
core dump: illegal instruction
Cause 0x0000000000000002, EPC 0x0000000080006f8a
W (2997940763) SYSCALL: sys_exit called by core 1 with 0x539
```

还有一次是**彻底冻结**：串口静读、回车、Ctrl-C 全部无响应，LCD 停在最后一帧不动。
这是卡在 C 层，MicroPython 的 `try/except` 完全救不回来。

**解法是硬件看门狗**（`machine.WDT`，本板固件支持）：

- 程序一进 `main()` 就武装看门狗（默认 30 秒）
- 主循环每帧 `wdt.feed()` 喂狗
- 一旦卡死超过 30 秒没喂 → **硬件直接复位板子** → `/flash/main.py` 自动重跑 → 画面自己回来
- 循环里任何 Python 层异常也会主动 `machine.reset()`，不许静默死掉
- 按 Ctrl-C 停止时会顺手关掉看门狗，板子老实停在 REPL 方便调试

代价：真卡死时会有约 30~35 秒黑屏，然后自动恢复。比一直黑着强。

想确认是不是卡死自愈了，看 `machine.reset_cause()`——返回 `4`（WDT_RESET）就是看门狗干的。

## 怎么跑

**开机自启（推荐）**：`body_detect.py` 已部署为 `/flash/main.py`，**板子上电即自动开始检测并显示在 LCD 上**。要重来就按板上的复位键，或拔插一次 USB。

**CanMV IDE**：连接板子 → 打开 `body_detect.py` → 点运行。双击 `open_in_ide.bat` 可直接打开。
（注意：板子正在跑自启 main.py 时 IDE 可能连不上，先在 IDE 里点停止/断开。）

**命令行**（需先在 IDE 里断开串口）：

```bash
# 实时运行主程序（Ctrl-C 停）
MSYS_NO_PATHCONV=1 python tools/repl.py COM16 run body_detect.py

# 跑一个死循环脚本 N 秒后自动 Ctrl-C 停止（看 LCD 用这个）
MSYS_NO_PATHCONV=1 python tools/live_run.py COM16 body_detect.py 120

# 只复位不发 Ctrl-C，验证开机自启 main.py 真的跑起来了
MSYS_NO_PATHCONV=1 python tools/watch_boot.py COM16 80

# 30 帧冒烟测试（自动退出）
MSYS_NO_PATHCONV=1 python tools/repl.py COM16 run tools/smoke_test.py

# 板上自检（固件/文件系统/KPU API/模型可用性）
MSYS_NO_PATHCONV=1 python tools/repl.py COM16 run selfcheck.py
```

> Git Bash 下必须带 `MSYS_NO_PATHCONV=1`，否则 `/flash/xxx` 会被转成 Windows 路径。

## 已部署到板子

| 路径 | 说明 |
|---|---|
| `/flash/person_v1.kmodel` | 人体模型 1.4MB（已验证） |
| `/flash/head_v1.kmodel` | 人头模型 1.4MB（已验证） |
| `/flash/main.py` | **本检测程序**（开机自启 + 看门狗 + 预览兜底，19497 B，已校验） |
| `/flash/main_moon.py.bak` `/flash/main_welcome.py.bak` | 原厂商开机脚本备份 |

## 四个必须知道的坑

**1. `lcd.init()` 会吃掉 KPU 需要的系统堆 —— 顺序必须「先模型、后 lcd」**

原厂商 `/flash/main.py` 是月亮检测脚本，读不存在的 `/sd/det.kmodel` 报 `ValueError: open file error`，而且它的 `lcd.init()` 占住系统堆，导致 KPU 的 1.4MB 模型缓冲分配失败（`MemoryError: model buffer memory allocation failed`）。

**已处理**：把厂商脚本移到 `/flash/main_moon.py.bak` / `main_welcome.py.bak`，`/flash/main.py` 换成 `body_detect.py`。它内部顺序是 `lcd.deinit()` → 加载模型 → `lcd.init()`，所以开机自启也不会踩这个坑。

恢复厂商开机脚本：`os.rename('/flash/main_welcome.py.bak','/flash/main.py')`。
想让开机什么都不跑（回到空白）：把 `/flash/main.py` 内容清成 `pass`（**不要删文件**，Yahboom 固件发现 main.py 不存在会自动重新生成欢迎屏脚本）。

**2. 固件会偶发崩溃/冻结 —— 靠看门狗兜底**

见上面「稳定性：看门狗兜底」。**不要为了省事把 `WDT_ENABLE` 关掉**。

**3. 上传"变慢"就是"卡死"，别硬等 —— 有明确的健康指标**

115200 波特率下 base64 分块上传，本板**实测**：

| 文件 | 块数 | 实测耗时 | 速率变化 |
|---|---|---|---|
| 19 KB（main.py） | 26 | **8.8 秒** | 9.6 → 7.3 KB/s |
| 1.4 MB（person_v1.kmodel） | 1906 | **约 10~11 分钟** | 7.0 → 2.9 KB/s |

**两个必须记住的点：**

1. **大文件越写越慢**：1.4MB 开头 7 KB/s、结尾只剩 2.9 KB/s。
   （别拿小文件的速率去外推大文件——我外推过一次，算出"4.5 分钟"，实测 11 分钟，错了 2.4 倍。）
2. **"卡死"的判据是"每块 20 秒以上"，不是"不到 7 KB/s"**。
   正常速率区间是 **2.9 ~ 9.6 KB/s**，末尾 3 KB/s 完全正常。
   真正的卡死长这样：**46 分钟只传了 6.3%**（板上文件 92160 / 1463728 字节，即每块 ~23 秒 =
   每块都在等 30 秒超时）。

确认卡死后：

1. **立刻杀掉上传**，别等
2. 板上 `os.stat('/flash/person_v1.kmodel')` 看实际大小，跟本地对不上就是废文件
3. `os.remove()` 删掉半截文件 —— **必须先删**，否则 main.py 会拿它去加载，进重启循环
4. 重新传

另外：**别把 `repl.py put` 的输出用管道 `| tail` 接**，`tail` 会把进度缓冲到结束才显示，
你就完全看不到速率，只能干等。要留日志就重定向到文件：

```bash
MSYS_NO_PATHCONV=1 python -u tools/repl.py COM16 put models/person_detect.kmodel /flash/person_v1.kmodel > tools/_put_model.log 2>&1
# 另开一个终端看进度:
tail -c 200 tools/_put_model.log
```

**4. IDE 连接时独占 COM16**

命令行工具连不上（拒绝访问），用前先在 IDE 里断开连接。

## 文件清单

```
body_detect.py        主程序（检测+跟踪+告警）
selfcheck.py          板上自检
open_in_ide.bat       双击用 IDE 打开主程序
models/               官方 kmodel（person / head）
testimgs/             COCO 测试图 + 板上推理结果图
tools/
  repl.py             串口客户端：info / run / put / get / ls / eval
  live_run.py         跑死循环脚本 N 秒后自动 Ctrl-C 停（LCD 实时预览用）
  watch_boot.py       仅复位、验证开机自启 main.py
  live_scan.py        60 秒扫描窗口，检出才存图（零检出存诊断帧）
  fetch_caps.py       一次串口会话把 /flash/cap_*.jpg 全取回
  peek.py             三级探针看板子状态（静读/回车/Ctrl-C），不复位
  sample.py           被动采样 N 秒：只读、不复位、不发 Ctrl-C，标定/看稳定性用
  calib.py            人体框标定采样（解析 DET 行，剔掉被裁的框）
  fit_focal.py        标定求解器：多点最小二乘反算 FOCAL_PX
  tag_calib.py        AprilTag 采样（QQVGA，逐帧打 w/h/z）
  fov_probe.py        决定性实验：同一 tag 在 QQVGA / QVGA 的像素宽之比（缩放 or 裁剪）
  make_tag.py         生成可打印的 AprilTag36h11（A4 SVG + 大图 PNG）
  repro.py            无人值守复现：复位→读15s→关串口静置N秒→探针
  smoke_test.py       30 帧实时冒烟测试
  verify_model.py     人体模型加载验证
  verify_head.py      人头模型加载验证
  detect_test.py      静态图片检测（读 /flash 里的图）
  handshake.py        串口握手诊断（波特率 + DTR/RTS 扫描）
  test_flash_space.py / test_flash_model.py   容量与 flash 地址探测
  probe_env.py / probe2.py                    环境与文件系统探测
  debug_io.py / reset_probe.py                底层串口调试
  official_head_detect.py.orig                官方原版（对照用）
```

## 换模型 / 上传新文件

```bash
MSYS_NO_PATHCONV=1 python tools/repl.py COM16 put 本地.kmodel /flash/名字.kmodel
```
115200 波特率下 **2.9~9.6 KB/s**（越写越慢），1.4MB 模型实测约 **10~11 分钟**。
判断是否卡死看"每块耗时"而不是速率，见"坑 3"。

**传完必须校验**，AI 和人都一样，别凭"命令没报错"就当成功了：

```bash
MSYS_NO_PATHCONV=1 python tools/repl.py COM16 eval "
f = open('/flash/person_v1.kmodel', 'rb')
r = 0; acc = 0
while True:
    d = f.read(8192)
    if not d: break
    r += len(d); acc = (acc + sum(d)) & 0xFFFFFFFF
f.close()
print('size', r, 'sum', acc)
print('VERDICT', 'GOOD' if (r == 1463728 and acc == 161167812) else 'BAD')
"
```

期望输出 `size 1463728 sum 161167812` + `VERDICT GOOD`。
（本地算出这两个数的命令见 `tools/fit_focal.py` 同目录的说明；简单说就是按 8192 字节分块累加所有字节。）
