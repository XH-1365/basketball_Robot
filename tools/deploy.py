# -*- coding: utf-8 -*-
"""
一键部署 body_detect.py 到板子的【两个】启动位置。

为什么是两个（实测血泪）:
  - 固件挂上 SD 卡后, 会去执行 /sd/main.py, 而且【不会回落】到 /flash/main.py
    -> 卡插着时不推 /sd/main.py, 板子就等于什么都没跑, 直接掉进 REPL
  - 卡不在时, 固件执行 /flash/main.py
  -> 所以两份都要有, 内容必须一致

用法:
  python tools/deploy.py            # 部署到两处
  python tools/deploy.py COM16      # 指定串口
  python tools/deploy.py COM16 -c   # 部署完顺便复位看自启是否正常
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPL = os.path.join(HERE, "repl.py")
WATCH = os.path.join(HERE, "reboot_watch.py")

# (本地源文件, 板上目标路径)。跟随链路模块 follow_link.py 必须和 main.py
# 同目录各推一份, import 才找得到（固件挂 SD 后执行 /sd/main.py）。
FILES = (
    (os.path.join(ROOT, "body_detect.py"), "/flash/main.py"),
    (os.path.join(ROOT, "body_detect.py"), "/sd/main.py"),
    (os.path.join(ROOT, "follow_link.py"), "/flash/follow_link.py"),
    (os.path.join(ROOT, "follow_link.py"), "/sd/follow_link.py"),
)


def run(argv):
    p = subprocess.run(argv, capture_output=True)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    return p.returncode, out


def main():
    port = "COM16"
    check = False
    for a in sys.argv[1:]:
        if a == "-c":
            check = True
        else:
            port = a

    # ---- 本地先过一遍语法, 别把坏文件推上板 ----
    import py_compile
    for src, _tgt in FILES:
        try:
            py_compile.compile(src, doraise=True,
                               cfile=os.path.join(HERE, "__pycache__",
                                                  "_syntax.pyc"))
        except Exception as e:
            print("!! 本地语法检查失败, 不部署: %s\n %s" % (src, e))
            return 2
        print(">>> 本地语法 OK, %s = %d 字节" % (src, os.path.getsize(src)))

    py = sys.executable
    ok = {}
    for src, tgt in FILES:
        size = os.path.getsize(src)
        print("\n>>> %s -> %s ..." % (os.path.basename(src), tgt))
        rc, out = run([py, REPL, port, "put", src, tgt])
        # repl.py 会打印 "size <n>"
        n = None
        for ln in out.splitlines():
            ln = ln.strip()
            if ln.startswith("size "):
                try:
                    n = int(ln.split()[1])
                except Exception:
                    pass
            if "打开文件失败" in ln:
                print("    跳过: 该位置不可写 (%s)" % ln)
        if n == size:
            print("    OK  板上 %d 字节, 与本地一致" % n)
            ok[tgt] = True
        elif n is None:
            print("    未确认写入 (可能该目录不存在)\n%s" % out[-400:])
            ok[tgt] = False
        else:
            print("    !! 大小不符: 板上 %s / 本地 %d" % (n, size))
            ok[tgt] = False

    print("\n===== 部署小结 =====")
    for _src, t in FILES:
        print("  %-24s %s" % (t, "OK" if ok.get(t) else "未写入"))

    if not all(ok.get(t) for _s, t in FILES):
        print("!! 有目标没写进去, 检查板子和串口")
        return 1

    if check:
        print("\n>>> 复位验证开机自启 ...")
        rc, out = run([py, WATCH, port, "25"])
        sys.stdout.write(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
