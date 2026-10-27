# -*- coding: utf-8 -*-
"""
按键/复位 归因实验。分三段, 每段都打标记, 一旦板子中途复位就能从
启动横幅(Pll0:freq 那段)的位置判断死在哪个阶段。

  阶段 1: 读 machine.reset_cause() —— 报告"上一次复位是谁干的"
  阶段 2: 验 WDT.stop() 是否真的管用 —— 武装 5 秒看门狗后立刻停掉,
          再睡 10 秒。板子活着 = stop() 有效; 被复位 = stop() 是假的。
  阶段 3: 试注册 IO17 —— 先不用 force, 再用 force, 各读电平。
          能一眼看出 IO17 是不是已被别的外设占用。
"""
import time

print("DIAG START")

# ---------- 阶段 1: 上次复位原因 ----------
try:
    import machine
    rc = machine.reset_cause()
    names = {}
    for n in ("PWRON_RESET", "HARD_RESET", "WDT_RESET", "WDT1_RESET", "SOFT_RESET"):
        try:
            names[getattr(machine, n)] = n
        except Exception:
            pass
    print("STAGE1 reset_cause=%d (%s)" % (rc, names.get(rc, "?")))
    print("STAGE1 all_resets", names)
except Exception as e:
    print("STAGE1 ERR", repr(e))

# ---------- 阶段 2: WDT.stop() 是否真的有效 ----------
print("STAGE2 arm 5000ms then stop ...")
try:
    import machine
    w = machine.WDT(0, 5000)
    print("STAGE2 armed")
    time.sleep_ms(300)
    w.stop()
    print("STAGE2 stopped -> 现在睡 10 秒, 若 stop() 无效则 5 秒后会被复位")
except Exception as e:
    print("STAGE2 ERR", repr(e))
t = time.ticks_ms()
for i in range(10):
    time.sleep_ms(1000)
    print("STAGE2 alive %ds" % (i + 1))
print("STAGE2 PASS stop() 有效")

# ---------- 阶段 3: IO17 注册 ----------
print("STAGE3 try register IO17 ...")
try:
    from fpioa_manager import fm
    print("STAGE3 used_pins_before", fm.get_gpio_used() if hasattr(fm, "get_gpio_used") else "n/a")
except Exception as e:
    print("STAGE3 fm import ERR", repr(e))
    fm = None

if fm is not None:
    # 3a: 不用 force —— 若 IO17 已被占用, 这里会报错, 那才是真相
    try:
        fm.register(17, fm.fpioa.GPIOHS1)
        print("STAGE3a register(no force) OK")
    except Exception as e:
        print("STAGE3a register(no force) FAIL", repr(e))
        try:
            fm.register(17, fm.fpioa.GPIOHS1, force=True)
            print("STAGE3a force register OK (说明原来被占用了!)")
        except Exception as e2:
            print("STAGE3a force FAIL", repr(e2))

    try:
        from maix import GPIO
        k = GPIO(GPIO.GPIOHS1, GPIO.IN, GPIO.PULL_UP)
        print("STAGE3b GPIO ok val=%d" % k.value())
    except Exception as e:
        print("STAGE3b GPIO ERR", repr(e))

# 阶段 3 读电平 25 秒(不碰摄像头/LCD)
t0 = time.ticks_ms()
i = 0
while time.ticks_diff(time.ticks_ms(), t0) < 25000:
    i += 1
    try:
        v = k.value()
    except Exception:
        v = -1
    if i % 10 == 0:
        print("STAGE3 loop n=%d t=%dms val=%d"
              % (i, time.ticks_diff(time.ticks_ms(), t0), v))
    time.sleep_ms(100)

print("DIAG DONE 全程未复位")
