# -*- coding: utf-8 -*-
"""给 body_detect.py 加"模型加载失败自愈": 重试 -> 有限次自动重启 -> 才回退预览。

背景: 卡偶尔挂不上 -> 模型加载失败 -> 静默退化成"只出画面不检测"。
无人值守时这是最危险的失败模式(板子看着正常, 其实一个人都不检测)。

改动三处:
  1. 配置区: 加 MODEL_RETRY / MODEL_AUTO_REBOOT / MODEL_MAX_REBOOTS / BOOTFAIL_PATH
  2. 加三个辅助函数: read_bootfail / write_bootfail / reboot_board
  3. 重写 build_detector: 重试 -> 有限次重启 -> 预览

硬约束: 绝不能变成无限重启。计数器放 /flash(卡缺失时也可读写),
连续 MODEL_MAX_REBOOTS 次失败就放弃重启。
"""
import io
import re

P = r"E:\K210\body_detect.py"
raw = io.open(P, "r", encoding="utf-8").read()
orig = raw
done = []

# ---------------- 1. 配置区 ----------------
a1 = u"MODEL_MISSING_FATAL = False"
assert raw.count(a1) == 1, "配置锚点命中 %d 次" % raw.count(a1)
cfg = a1 + u"""

# --- 模型加载失败时的自愈（2026-10-10 加）---
# 动机: 卡偶尔挂不上 -> 模型加载失败 -> 会静默退化成"只出画面不检测"。
#       无人值守时这是最危险的失败模式: 板子看着一切正常, 其实一个人都不检测。
# 做法(有限次, 绝不无限重启):
#   1. 原地重试 MODEL_RETRY 次(卡挂载慢 / 模型刚传到一半)
#   2. 还失败 -> 自动重启板子重来(重启会重跑固件的 SD 初始化, 实测常能自愈)
#   3. 连续 MODEL_MAX_REBOOTS 次开机都没拿到模型 -> 放弃重启, 老实停在预览模式
# 计数器放 /flash 而不是 /sd —— 卡没挂上时 /flash 照样可读写。
MODEL_RETRY         = 3      # 加载失败先原地重试几次
MODEL_RETRY_DELAY_S = 2.0    # 每次重试之间等多久
MODEL_AUTO_REBOOT   = True   # 重试还失败就自动重启重来
MODEL_MAX_REBOOTS   = 3      # 连续几次开机都失败就放弃重启(防无限重启)
BOOTFAIL_PATH       = "/flash/bootfail.txt\""""
raw = raw.replace(a1, cfg, 1)
done.append("配置区")

# ---------------- 2. 辅助函数 + 3. 重写 build_detector ----------------
old_bd = u'''def build_detector():
    """按 MODE 建检测器; 失败时按 MODEL_MISSING_FATAL 决定抛错还是回退预览。"""
    if MODE == "PREVIEW":
        print("[PREVIEW] 预览模式: 不加载模型, 只出画面")
        return NullDetector("PRE", COLOR_BODY)
    try:
        if MODE == "BODY":
            return Detector("BODY", ANCHOR_BODY, BODY_MODEL_PATHS, COLOR_BODY)
        return Detector("HEAD", ANCHOR_HEAD, HEAD_MODEL_PATHS, COLOR_HEAD)
    except Exception as e:
        print("[模型] 加载失败:", repr(e))
        if MODEL_MISSING_FATAL:
            raise
        print("[模型] 已回退到预览模式(画面照上, 只是不检测)。"
              "把模型传好再上电即自动恢复。")
        return NullDetector("PRE", COLOR_BODY)'''
assert raw.count(old_bd) == 1, "build_detector 锚点命中 %d 次" % raw.count(old_bd)

new_bd = u'''def read_bootfail():
    """读"连续几次开机都没拿到模型"的计数器。文件不存在/内容坏都当 0。"""
    try:
        f = open(BOOTFAIL_PATH, "r")
        try:
            s = f.read().strip()
        finally:
            f.close()
        return int(s) if s else 0
    except Exception:
        return 0


def write_bootfail(n):
    """写计数器。值没变就不写 —— 少擦一次 flash。"""
    if read_bootfail() == n:
        return
    try:
        f = open(BOOTFAIL_PATH, "w")
        try:
            f.write("%d" % n)
        finally:
            f.close()
    except Exception as e:
        print("[自愈] 计数器写入失败(忽略):", repr(e))


def reboot_board():
    """自动重启。machine.reset() 不行就让看门狗超时兜底。

    正常情况【不返回】(复位了); 只有复位发不出去、看门狗也关着时才返回 False。
    """
    try:
        print("[自愈] 调 machine.reset() 重启")
        time.sleep(0.2)
        machine.reset()
        print("[自愈] !! machine.reset() 返回了, 没生效")
    except Exception as e:
        print("[自愈] reset 异常(可能已复位): %r" % (e,))
    if WDT_ENABLE:
        print("[自愈] 交给看门狗超时复位(不再喂狗, 最多 %d ms) ..."
              % WDT_TIMEOUT_MS)
        while True:
            time.sleep(1)
    print("[自愈] 看门狗也关着, 没法自动重启")
    return False


def build_detector():
    """按 MODE 建检测器。

    失败时: 先原地重试 -> 再有限次自动重启 -> 最后才回退预览
    (或按 MODEL_MISSING_FATAL 直接抛错)。
    """
    if MODE == "PREVIEW":
        print("[PREVIEW] 预览模式: 不加载模型, 只出画面")
        return NullDetector("PRE", COLOR_BODY)

    last = None
    for k in range(MODEL_RETRY):
        try:
            if MODE == "BODY":
                det = Detector("BODY", ANCHOR_BODY, BODY_MODEL_PATHS, COLOR_BODY)
            else:
                det = Detector("HEAD", ANCHOR_HEAD, HEAD_MODEL_PATHS, COLOR_HEAD)
            write_bootfail(0)          # 成功 -> 计数器清零, 下次开机从零开始
            return det
        except Exception as e:
            last = e
            print("[模型] 第 %d/%d 次加载失败: %r" % (k + 1, MODEL_RETRY, e))
            gc.collect()               # 失败留下的 KPU 对象要回收, 否则重试几次就没内存
            if k + 1 < MODEL_RETRY:
                time.sleep(MODEL_RETRY_DELAY_S)

    print("[模型] 加载失败(试了 %d 次): %r" % (MODEL_RETRY, last))
    if MODEL_MISSING_FATAL:
        raise last

    if MODEL_AUTO_REBOOT:
        n = read_bootfail() + 1
        if n <= MODEL_MAX_REBOOTS:
            write_bootfail(n)
            print("[自愈] 连续第 %d/%d 次开机没拿到模型, 重启重来 ..."
                  % (n, MODEL_MAX_REBOOTS))
            reboot_board()             # 正常不返回
        else:
            print("[自愈] 已连续 %d 次失败, 放弃重启(防止无限重启), 停在预览模式"
                  % MODEL_MAX_REBOOTS)

    print("[模型] 已回退到预览模式(画面照上, 只是不检测)。"
          "把模型传好再上电即自动恢复。")
    return NullDetector("PRE", COLOR_BODY)'''

raw = raw.replace(old_bd, new_bd, 1)
done.append("辅助函数 + build_detector")

# ---------------- 4. 顺手把上面那段注释指向新行为 ----------------
old_note = u"""# True         = 直接抛异常(老行为, 会配合看门狗变成无限重启)。"""
assert raw.count(old_note) == 1, "注释锚点命中 %d 次" % raw.count(old_note)
new_note = u"""# True         = 直接抛异常, 不重试也不回退(老行为, 会配合看门狗变成无限重启)。
# 注: False 时现在的流程是 "重试 -> 有限次自动重启 -> 才回退预览", 见下面的 MODEL_* 配置。"""
raw = raw.replace(old_note, new_note, 1)
done.append("旧注释指向新行为")

assert raw != orig
io.open(P, "wb").write(raw.encode("utf-8"))
print("OK, 改了 %d 处: %s" % (len(done), " / ".join(done)))
print("文件 %d -> %d 字节" % (len(orig.encode("utf-8")), len(raw.encode("utf-8"))))

# ---------------- 自检 ----------------
import py_compile
import tempfile
import os as _os
with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False) as tf:
    tmp = tf.name
try:
    py_compile.compile(P, cfile=tmp, doraise=True)
    print("语法检查: OK")
finally:
    _os.remove(tmp)

for name in ("read_bootfail", "write_bootfail", "reboot_board", "build_detector",
             "MODEL_RETRY", "MODEL_MAX_REBOOTS", "BOOTFAIL_PATH"):
    assert name in raw, "少了 %s" % name
print("关键符号齐全")
