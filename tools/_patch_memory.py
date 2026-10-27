# -*- coding: utf-8 -*-
"""一次性原子更新 .workbuddy/memory/MEMORY.md, 每处改动都断言命中数。"""
import io
import re
import sys

P = r"E:\K210\.workbuddy\memory\MEMORY.md"
raw = io.open(P, "r", encoding="utf-8").read()
orig = raw

edits = []

# ---- 1. 在 AprilTag 段落之后插入新的棋盘格标定段落 ----
NEW_SEC = u"""
## ★★ 棋盘格标定完成（2026-10-10 实测，推翻旧的 FOCAL_PX=277）
- **实测结果**：`FOCAL_PX = fy = 408.95`（Q跑 320x240），`CAM_CY = cy = 102.06`，
  `cx = 176.03`，RMS 重投影 **0.1695 px**，有效图 20/24，`fx/fy = 1.0041`
- **旧值 277 从来没被物理测过** —— 它是最早的估计值，之后合成自测里出现的
  「真值 f=277」只是拿它验证拟合代码能不能跑通（循环论证）。
  **277 → 409 差 47.6%，等价于过去 HEIGHT 法读数偏小约 32%**
- ★ 焦距该取 **fy 不是 fx**：HEIGHT 法量的是框【高】= 纵向像素，
  纵向投影 `h_px = fy·H/D` ⇒ `D = fy·H/h_px`
- 已写回 body_detect.py 并 `tools/deploy.py COM16` 推到 /flash/main.py + /sd/main.py

### 怎么验证一个标定结果（三件套工具，都留在 tools/ 下）
1. `tools/_verify_chess_calib.py` — 自助抽样 + 畸变量化
   · 随机抽 16 张重标 40 次：fx 相对极差 4.90%，RMS 稳在 0.170 → 焦距不是随机噪声
   · **畸变极小：全画面最大径向位移只有 3.57 px（画面宽的 1.12%）** → 不用去畸变
2. `tools/_verify_loo_cv.py` — 留一交叉验证。全模型 / 只有k1 / k1k2 / 纯针孔
   四个模型 LOO 误差 0.1569~0.1600 px **完全打平** → 数据区分不了模型，
   6% 的焦距差是「参数简并」，不是噪声
3. `tools/_effective_focal.py` — **最终定案**。按 body_detect 的真实几何
   （竖直杆 [x_off, ±H/2, D] 投影）反解纯针孔公式的有效焦距：
   D≥3 m 时 f_eff = **409.06**（x_off 0/40/80/110 四处都试），与全模型 fy 重合
   → 结论：**用全模型的 fy**。因为畸变在 r=0 处是恒等变换，
     「中心焦距」就是人站画面中央时该用的焦距；纯针孔那个 385.86 是被画面四角拖低的

### ★ 判断畸变大小绝不能看系数
- 本例 `k1=-0.032 k2=1.295 k3=-4.617 p1=-0.004 p2=0.009`，
  数值看着吓人，但**合成径向曲线在整流形范围内偏离 1 不超过 0.9%**
  —— k2/k3 是在和 k1、fx、cx、cy 互相抵消（过拟合）
- 根因：**棋盘格从没进过画面四角**（角点最远只到画面半对角的 73%，y 最多 0.823）。
  平面标定要约束径向畸变，必须让靶标铺到画面边角
- 判断方法：把 `1 + k1·r² + k2·r⁴ + k3·r⁶` 在 r∈[0, 半对角] 上画出来，看倍率曲线，
  **不看单个系数**

### 棋盘格标定链（比 AprilTag 更适合标内参）
- `tools/shot_chess.py`（板端）BOOT 键拍干净 QVGA 图 → `/sd/chess_NNN.jpg`，`MAX_SHOTS` 拍满自停
- `tools/chess_collect.py COM16 [--from N] [--apply]`（PC 端一键）
  打断板上脚本 → 拉图 → 调 calib_chess.py → 可选写回 → 复位板子
- `tools/calib_chess.py`（PC 端）自动猜内角点规格（实测 **9×6**），
  输出 `FOCAL_PX`(=fy) / `CAM_CY`，并解释为什么用 fy
- **不用给任何参数**：格子物理边长不用给（内参与物点尺度无关）、
  内角点数不用数、距离不用量。用户只需保证拍摄质量（姿态多、不出画、光线够）

### 棋盘格 / AprilTag 怎么选
- 棋盘格：能给畸变 + 主点，无检出死区，**不需要格子物理尺寸**。
  代价：PC 端解算，要 15~25 张不同姿态
- AprilTag：能板上实时算，但**检出能力非单调（有死区）**，且给不了畸变
- 标内参 → 棋盘格；要现场快速核对 → AprilTag
"""

anchor = u"## 地面法(GROUND)测距 —— 装相机前必看"
assert raw.count(anchor) == 1, "GROUND 段锚点命中 %d" % raw.count(anchor)
raw = raw.replace(anchor, NEW_SEC.strip() + u"\n\n" + anchor, 1)
edits.append("插入棋盘格标定段")

# ---- 2. 修 AprilTag 的 277 距离建议(改用 QQVGA 口径 204.5) ----
pat = (u"^- \\*\\*100mm 的 tag 最远只能摆 0\\.69m\\*\\*.*?检不到）$")
m = re.search(pat, raw, re.M | re.S)
assert m, "AprilTag 距离建议段没匹配到"
new_ap = (u"- **焦距口径要小心**: AprilTag 链跑在 **QQVGA(160x120)**, 焦距是 QVGA 的一半\n"
          u"  → 现测得 QVGA fy=409 ⇒ **QQVGA f = 204.5**(旧文档里的 277 是按 QVGA 猜的, 口径混了)\n"
          u"- **100mm 的 tag 最远只能摆 0.51m**（`204.5×0.100/40`，按外沿 ≥40px 才稳）。\n"
          u"  推荐摆 **0.22 / 0.33 / 0.45 / 0.55 m**（外沿约 92/62/46/37 px，和死区对齐）。\n"
          u"  想标更远就把 tag 印大。（旧值 0.3~0.75m 是按 277 推的，焦距实测后要整体缩 0.74 倍）")
raw = re.sub(pat, lambda mm: new_ap, raw, count=1, flags=re.M | re.S)
edits.append("修 AprilTag 距离建议")

# ---- 3. 修 GROUND 段的 f/cy 与覆盖表 ----
pat2 = (u"^- \\*\\*俯角 0 时测不了近处\\*\\*：.*?全在画面外\n"
        u"- hc=1\\.20 的覆盖表：.*?30°→0\\.90m~10\\.4m$")
m2 = re.search(pat2, raw, re.M | re.S)
assert m2, "GROUND 覆盖段没匹配到"
new_gr = (u"- **俯角 0 时近处根本测不到**（实测焦距定案后更严）：hc=1.2m、**f=409、cy=102**、画面高 240 时，\n"
          u"  底边那行 y=239 对应 `atan((239-102)/409)=18.52°` → 最近只能测 `1.20/tan(18.52°)=3.58m`，\n"
          u"  **3.58m 以内的脚全在画面外**（比旧文档按 f=277 算的 2.79m 更糟）\n"
          u"- hc=1.20、f=409、cy=102 的覆盖表（近 ~ 远）：\n"
          u"  · 0°  → 3.58m ~ ∞\n"
          u"  · 10° → 2.21m ~ ∞\n"
          u"  · 20° → 1.51m ~ 11.4m\n"
          u"  · 25° → 1.26m ~ 6.18m\n"
          u"  · 30° → 1.06m ~ 4.19m\n"
          u"  （远界 = 俯角 − 顶端 off-axis 角 14.0°，俯角越大远界收得越狠）")
raw = re.sub(pat2, lambda mm: new_gr, raw, count=1, flags=re.M | re.S)
edits.append("修 GROUND 覆盖表")

# ---- 4. 工具清单补新工具 ----
pat3 = u"- `tools/_test_fit_tag.py` / `_test_calib_collect.py` = AprilTag 标定链的离线自测"
m3 = re.search(re.escape(pat3), raw)
assert m3, "工具清单锚点没匹配到"
add3 = pat3 + u"""
- `tools/shot_chess.py` + `chess_collect.py` + `calib_chess.py` = **棋盘格标定链**（标内参首选）
- `tools/live_view.py COM16 --http-port 8823` = 串口实时取景（板端吐小 JPEG → 本地 MJPEG 网页）
- `tools/_verify_chess_calib.py` / `_verify_loo_cv.py` / `_effective_focal.py` = 标定可信度三件套"""
raw = raw.replace(pat3, add3, 1)
edits.append("补工具清单")

# ---- 5. 铁律补两条 ----
pat4 = (u"18\\. \\*\\*PowerShell 的 `\\*>` 重定向写出的是 UTF-16LE\\*\\*，读日志要先看 BOM：\n"
        u"    `if raw\\[:2\\] in \\(b'\\\\xff\\\\xfe', b'\\\\xfe\\\\xff'\\): raw\\.decode\\('utf-16'\\)`")
m4 = re.search(pat4, raw)
assert m4, "铁律 18 锚点没匹配到"
add4 = m4.group(0) + u"""
19. **板子会卡死在 `print()` 里**：读端断开过 + 板子正高速刷串口 → K210 USB 发送缓冲塞满
    → 板子阻塞在 print() 里，**Ctrl-C 12 秒一个字节都不回**。
    open_port 故意不拉 DTR（避免复位），所以这种卡死不会自己好。
    兜底：先 `drain()` 解阻塞，还不行就 `repl.hard_reset()`（DTR 脉冲硬复位 + 抢打断）
20. **管道里 Python 的 stdout 是块缓冲**：`python xxx.py ... 2>&1`（前台）被 SIGTERM 掐掉后
    **输出会全丢**，看起来像「什么都没干」。必须 `-u`，或放后台跑（后台能拿到部分输出）
21. **串口拉文件的实测速度约 15 秒/张（约 25KB 的 JPEG）**，21 张要 8 分钟。
    量级先算好再决定前台还是后台"""
raw = re.sub(pat4, lambda mm: add4, raw, count=1)
edits.append("铁律补 19/20/21")

assert raw != orig, "什么都没改到"
io.open(P, "wb").write(raw.encode("utf-8"))
print("OK, 改了 %d 处: %s" % (len(edits), ", ".join(edits)))
print("文件 %d -> %d 字节" % (len(orig.encode("utf-8")), len(raw.encode("utf-8"))))
