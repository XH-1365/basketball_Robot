# -*- coding: utf-8 -*-
"""抢救后的状态确认: 复位->等 REPL->查 /flash 内容与空间。"""
import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
CTRL_A = b"\x01"
CTRL_B = b"\x02"
CTRL_C = b"\x03"
CTRL_D = b"\x04"

s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.2
s.dtr = False
s.rts = False
s.open()


def reset_and_wait(tries=4):
    last = b""
    for i in range(tries):
        s.reset_input_buffer()
        s.dtr = True
        time.sleep(0.3)
        s.dtr = False
        t0 = time.time()
        buf = b""
        while time.time() - t0 < 6:
            d = s.read(4096)
            if d:
                buf += d
        last = buf
        if b">>>" in buf:
            print("复位第 %d 次成功，启动 %d bytes" % (i + 1, len(buf)))
            return True
        print("复位第 %d 次未成功 (%d bytes)" % (i + 1, len(buf)))
    print("最后输出尾部: %r" % last[-200:])
    return False


if not reset_and_wait():
    print("!! 板子没能回到 REPL")
    s.close()
    sys.exit(1)

s.reset_input_buffer()
s.write(CTRL_A)
time.sleep(0.4)
r = s.read(1024)
if b">" not in r:
    print("进 raw REPL 失败: %r" % r[:200])
    s.close()
    sys.exit(1)
print("已进 raw REPL")

code = ("import os, gc\n"
        "print('ROOT  :', os.listdir('/'))\n"
        "print('FLASH :', os.listdir('/flash'))\n"
        "for n in os.listdir('/flash'):\n"
        "    try:\n"
        "        print('   %-24s %d' % (n, os.stat('/flash/'+n)[6]))\n"
        "    except Exception as e:\n"
        "        print('   %-24s ERR %s' % (n, e))\n"
        "st = os.statvfs('/flash')\n"
        "print('TOTAL : %.2f MB' % (st[2]*st[0]/1048576.0))\n"
        "print('FREE  : %.2f MB' % (st[3]*st[0]/1048576.0))\n"
        "print('MEM   :', gc.mem_free())\n")
s.write(code.encode() + CTRL_D)
s.timeout = 12
head = s.read_until(b"OK")
out = s.read_until(b"\x04")
err = s.read_until(b"\x04")
s.timeout = 0.3
sys.stdout.write(out.decode("utf-8", "replace"))
if err.strip(b"\x04\r\n"):
    print("--- STDERR ---")
    sys.stdout.write(err.decode("utf-8", "replace"))

s.write(CTRL_B)
time.sleep(0.2)
s.read(4096)
s.close()
print("完成")
