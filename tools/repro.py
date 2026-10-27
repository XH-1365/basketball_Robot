# -*- coding: utf-8 -*-
"""
无人值守复现实验：
  1. DTR 复位，让板子自己跑 /flash/main.py，读 15 秒确认启动
  2. 关串口，静置 WAIT 秒（全程没人管）
  3. 探测板子是否还活着（静读 / 回车 / Ctrl-C）
  4. 硬复位，把 /flash/hb.txt 读回来看卡死在那一刻

用法: python tools/repro.py COM16 300
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 300


def stream(s, secs, tag):
    s.timeout = 0.2
    t0 = time.time()
    buf = b""
    last = 0.0
    while time.time() - t0 < secs:
        n = s.in_waiting
        if n:
            d = s.read(n)
            if d:
                buf += d
                sys.stdout.write(d.decode("utf-8", "replace"))
                sys.stdout.flush()
        else:
            time.sleep(0.05)
        el = time.time() - t0
        if el - last > 20:
            sys.stdout.write("\n[%s %ds/%ds]\n" % (tag, int(el), secs))
            sys.stdout.flush()
            last = el
    return buf


# ---------- 1. 复位启动，确认起来了 ----------
s = repl.open_port(PORT)
try:
    repl.drain(s, 0.3)
    print(">>> DTR 复位，让 main.py 自己跑 ...")
    s.reset_input_buffer()
    s.dtr = True
    time.sleep(0.3)
    s.dtr = False
    print(">>> 读 15 秒确认启动")
    print("-" * 50)
    b1 = stream(s, 15, "启动")
    print("\n" + "-" * 50)
    if "开始实时检测" in b1.decode("utf-8", "replace"):
        print(">>> 确认已进入检测循环")
    else:
        print("!! 没看到'开始实时检测'，看上面输出")
finally:
    try:
        s.dtr = False
        s.rts = False
        time.sleep(0.2)
    except Exception:
        pass
    s.close()

# ---------- 2. 无人值守静置 ----------
print("\n>>> 关闭串口，静置 %d 秒（没人管板子）..." % WAIT)
time.sleep(WAIT)

# ---------- 3. 探测 ----------
print(">>> 探测板子状态 ...")
s = repl.open_port(PORT)
alive = False
try:
    b = stream(s, 5, "探测")
    print("    静读 5s: %d 字节 %r" % (len(b), b[:160]))
    if b"DET" in b:
        alive = True
    s.write(b"\r\n")
    b2 = stream(s, 3, "回车")
    print("    回车后: %d 字节 %r" % (len(b2), b2[:160]))
    s.write(repl.CTRL_C)
    b3 = stream(s, 4, "Ctrl-C")
    print("    Ctrl-C 后: %d 字节 %r" % (len(b3), b3[:200]))
    if (len(b) + len(b2) + len(b3)) == 0:
        print("\n===== 复现成功：板子无响应（冻结）=====")
    elif b"DET" in b or b"DET" in b3:
        print("\n===== 没复现：程序还在跑 =====")
        alive = True
    else:
        print("\n===== 有响应但不含 DET，看上面内容 =====")
finally:
    try:
        s.dtr = False
        s.rts = False
        time.sleep(0.2)
    except Exception:
        pass
    s.close()

# ---------- 4. 复位并读心跳 ----------
if not alive:
    print("\n>>> 硬复位抢救 ...")
    s = repl.open_port(PORT)
    try:
        repl.drain(s, 0.3)
        ok = repl.hard_reset(s)
        print(">>> 复位 %s" % ("成功" if ok else "失败"))
        out, err = repl.exec_code(
            s,
            "import os\n"
            "try:\n"
            "    d = open('/flash/hb.txt','rb').read().decode()\n"
            "    lines = [l for l in d.splitlines() if l.strip()]\n"
            "    print('HB lines', len(lines))\n"
            "    for l in lines[-6:]:\n"
            "        print('  ', l)\n"
            "except Exception as e:\n"
            "    print('hb read fail', repr(e))\n",
            echo=False)
        sys.stdout.write(out.decode("utf-8", "replace"))
        if err.strip():
            print("ERR:", err.decode("utf-8", "replace")[:300])
    finally:
        try:
            s.dtr = False
            s.rts = False
        except Exception:
            pass
        s.close()
print("\n>>> 实验结束")
