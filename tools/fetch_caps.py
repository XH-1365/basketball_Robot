# -*- coding: utf-8 -*-
"""一次串口会话把 /flash 里所有 cap_*.jpg 取回本地。"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repl  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM16"
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testimgs", "caps")

CODE = """
import os, ubinascii
names = []
for n in os.listdir('/flash'):
    if n.startswith('cap_') and n.endswith('.jpg'):
        names.append(n)
names.sort()
print('COUNT', len(names))
for n in names:
    f = open('/flash/' + n, 'rb')
    print('FILE ' + n)
    while True:
        d = f.read(1500)
        if not d:
            break
        print(ubinascii.b2a_base64(d).decode().strip())
    f.close()
print('ALLDONE')
"""


def main():
    if not os.path.isdir(OUTDIR):
        os.makedirs(OUTDIR)
    s = repl.open_port(PORT)
    try:
        repl.drain(s, 0.3)
        print(">>> 同步板子 ...")
        if not repl.hard_reset(s):
            print("!! 复位失败，仍继续尝试")
        print(">>> 读取 cap_*.jpg ...")
        out, err = repl.exec_code(s, CODE, timeout=240, echo=False)
        txt = out.decode("utf-8", "replace")
        if err.strip():
            print("STDERR:", err.decode("utf-8", "replace")[:400])

        cur = None
        chunks = []
        saved = []
        for line in txt.splitlines():
            line = line.strip()
            if line.startswith("COUNT"):
                print("板上有", line.split()[1], "张截图")
                continue
            if line.startswith("FILE "):
                if cur and chunks:
                    data = base64.b64decode("".join(chunks))
                    p = os.path.join(OUTDIR, cur)
                    with open(p, "wb") as f:
                        f.write(data)
                    saved.append((cur, len(data)))
                cur = line[5:].strip()
                chunks = []
                continue
            if line in ("ALLDONE", "") or line.startswith(">>>"):
                continue
            if cur is not None:
                chunks.append(line)
        if cur and chunks:
            data = base64.b64decode("".join(chunks))
            p = os.path.join(OUTDIR, cur)
            with open(p, "wb") as f:
                f.write(data)
            saved.append((cur, len(data)))

        print(">>> 保存到 %s" % OUTDIR)
        for n, sz in saved:
            print("    %-14s %d bytes" % (n, sz))
        print("共 %d 张" % len(saved))
    finally:
        s.close()


if __name__ == "__main__":
    main()
