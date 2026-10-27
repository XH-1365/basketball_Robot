# -*- coding: utf-8 -*-
"""parse_stream.py 的回归自测(离线, 不用板子)。

覆盖实测踩到的 3 种破坏方式:
  A) 长 base64 行【中间被插了一个换行】  -> 字符流读法应当免疫, 一遍就该对
  B) 行中间被插进杂行 "[RUN 15s/150s]"   -> 这一块应当被判为坏块
  C) 整块没发过来(丢了)                  -> 第二遍重吐后应当补齐
另外验证旧格式(IMGBEGIN/B64/IMGEND) 兼容。
"""
import base64
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CHUNK = 512
LEGACY_CHUNK = 1500       # 旧流程就是这么发的(1500 % 3 == 0, 不带补位)


def mk_jpeg(nbytes, seed):
    d = bytearray(b"\xff\xd8\xff\xe0")
    x = seed
    while len(d) < nbytes - 2:
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        d.append(x & 0xFF)
    d += b"\xff\xd9"
    return bytes(d)


def chunks_of(data, n=CHUNK):
    return [data[i:i + n] for i in range(0, len(data), n)]


def bline(name, i, c):
    return "B %s %d %d %d %s#\n" % (name, i, len(c), sum(c) & 0xFFFF,
                                    base64.b64encode(c).decode())


def emit(f, name, chs, cut=None, junk=None, skip=(), tag="auto"):
    f.write("ITEM %s %d %d\n" % (name, sum(len(c) for c in chs), len(chs)))
    for i, c in enumerate(chs):
        if i in skip:
            continue
        s = bline(name, i, c)
        if i == cut:
            # A) 在行中间插一个换行(模拟实测到的串口行为)
            k = len(s) // 2
            s = s[:k] + "\r\n" + s[k:]
        if i == junk:
            # B) 行中间插进一条杂行
            k = len(s) // 2
            s = s[:k] + "\r\n[RUN 15s/150s]\r\n" + s[k:]
        f.write(s)
    f.write("E %s %d\n" % (name, len(chs)))


def main():
    log = os.path.join(HERE, "_selftest.log")
    outdir = os.path.join(HERE, "_selftest_out")
    if os.path.isdir(outdir):
        for n in os.listdir(outdir):
            os.remove(os.path.join(outdir, n))
    else:
        os.makedirs(outdir)

    a = mk_jpeg(17545, 7)
    b = mk_jpeg(12000, 99)
    c = mk_jpeg(9000, 2024)
    ca, cb, cc = chunks_of(a), chunks_of(b), chunks_of(c)

    with open(log, "w", encoding="utf-8") as f:
        f.write("[CanMV]: find gc2145\n")
        f.write("sdcard no found\n")
        f.write("SHOT n=12 name=cap_012.jpg size=17545\n")
        f.write("SERVE count=3 tag=auto\n")
        emit(f, "cap_012.jpg", ca, cut=17)                 # A
        emit(f, "cap_013.jpg", cb, junk=5)                 # B
        emit(f, "cap_014.jpg", cc, skip=(7,))              # C
        f.write("SERVEDONE count=3 tag=auto gc_free=420000\n")
        # 第二遍(长按重吐): 只重吐 013 / 014, 012 不再出现
        f.write("LONGPRESS_DUMP t=33s\n")
        f.write("SERVE count=2 tag=longpress\n")
        emit(f, "cap_013.jpg", cb)
        emit(f, "cap_014.jpg", cc)
        f.write("SERVEDONE count=2 tag=longpress gc_free=418000\n")
        # 旧格式
        f.write("IMGBEGIN cap_099.jpg %d\n" % len(a))
        for ch in chunks_of(a, LEGACY_CHUNK):
            f.write("B64 %s\n" % base64.b64encode(ch).decode())
        f.write("IMGEND cap_099.jpg\n")
        f.write("RAMDONE shots=14 kept=3\n")

    print(">>> 假日志 %s (%d bytes)" % (log, os.path.getsize(log)))
    subprocess.call([PY, os.path.join(HERE, "parse_stream.py"), log, outdir])

    print("\n===== 断言 =====")
    fails = 0

    def chk(cond, msg):
        nonlocal fails
        print(("  PASS  " if cond else "  FAIL  ") + msg)
        if not cond:
            fails += 1

    def same(fn, want):
        p = os.path.join(outdir, fn)
        return os.path.exists(p) and open(p, "rb").read() == want

    chk(same("cap_012.jpg", a), "A 中途插换行 -> 一遍即无损 (字节完全一致)")
    chk(same("cap_013.jpg", b), "B 中途插杂行 -> 判坏块 + 第二遍修好")
    chk(same("cap_014.jpg", c), "C 整块丢失 -> 第二遍补齐")
    chk(same("cap_099.jpg", a), "旧格式 IMGBEGIN/B64/IMGEND 兼容")

    print("断言失败: %d" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
