# -*- coding: utf-8 -*-
"""
棋盘格标定一键收尾（PC 端）

作用: 停掉板上正在跑的采集脚本 -> 把 /sd/chess_*.jpg 拉回本地
      -> 直接调 calib_chess.py 标定 -> 打印能贴进 body_detect.py 的两行
      -> 最后把板子复位回 main.py 的正常检测状态

用法:
  python tools/chess_collect.py COM16
  python tools/chess_collect.py COM16 --from 4          # 跳过前 4 张(旧姿态)
  python tools/chess_collect.py COM16 --pull-only       # 只拉图不标定
  python tools/chess_collect.py COM16 --apply           # 标完自动改 body_detect.py
                                                        # (改完仍需自己跑 deploy.py)

注意: 会占用 COM16, 跑之前先断开 CanMV IDE。
"""
import argparse
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import repl as R  # noqa: E402

_PY_CACHE = []


def pick_python():
    """挑一个装了 cv2 的 Python 跑标定。

    cv2 装在项目 venv (…/python/envs/default) 里, 而本脚本自己可能是用
    另一个 python 启动的, 直接用 sys.executable 会 ModuleNotFoundError。
    """
    if _PY_CACHE:
        return _PY_CACHE[0]
    base = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(sys.executable))))
    cands = [
        os.path.join(base, "envs", "default", "Scripts", "python.exe"),
        os.path.join(base, "envs", "default", "bin", "python"),
        sys.executable,
    ]
    for c in cands:
        if not os.path.isfile(c):
            continue
        try:
            r = subprocess.run([c, "-c", "import cv2"], capture_output=True)
            if r.returncode == 0:
                if c != sys.executable:
                    print(">>> 标定用解释器: %s" % c)
                _PY_CACHE.append(c)
                return c
        except Exception:
            pass
    print("!! 找不到装了 cv2 的 Python, 试过: %s" % cands)
    _PY_CACHE.append(sys.executable)
    return sys.executable


def pick_port(want=None):
    """找板子串口。want 给了就用它, 否则自动挑 CH340/USB-SERIAL。"""
    import serial.tools.list_ports as lp
    ports = list(lp.comports())
    if want:
        for p in ports:
            if p.device.upper() == want.upper():
                return p.device
        raise SystemExit("!! 找不到串口 %s。当前可用: %s"
                         % (want, [p.device for p in ports] or "无"))
    hits = [p for p in ports
            if "CH340" in (p.description or "").upper()
            or "USB-SERIAL" in (p.description or "").upper()]
    if len(hits) == 1:
        print(">>> 自动识别到板子: %s (%s)" % (hits[0].device, hits[0].description))
        return hits[0].device
    if not hits:
        raise SystemExit("!! 没找到板子串口(CH340). 板子插上了吗? 当前: %s"
                         % ([p.device for p in ports] or "一个串口都没有"))
    raise SystemExit("!! 找到多个疑似串口, 请手动指定: %s"
                     % [(p.device, p.description) for p in hits])


def list_board_chess(s):
    """返回板上 /sd/chess_NNN.jpg 的编号列表。"""
    out, err = R.exec_code(
        s,
        "import os\n"
        "ns = []\n"
        "for n in os.listdir('/sd'):\n"
        "    if n.startswith('chess_') and n.endswith('.jpg'):\n"
        "        ns.append(n)\n"
        "print('|'.join(sorted(ns)))\n",
        echo=False)
    txt = out.decode("utf-8", "replace").strip()
    ids = []
    for name in txt.split("|"):
        name = name.strip()
        m = re.match(r"chess_(\d+)\.jpg$", name)
        if m:
            ids.append(int(m.group(1)))
    return sorted(ids)


def stop_board_script(s):
    """Ctrl-C 打断板上正在跑的脚本(采集脚本或 main.py), 回到 >>>。

    有一个实测坑: 如果板子正在高速往串口刷数据(比如 shot_chess.py 的预览
    帧), 而读端刚好断开过 —— K210 的 USB 发送缓冲会塞满, 板子就**卡死在
    print() 里**, 此时 Ctrl-C 根本进不去(实测 12s 一个字节都不回)。
    open_port 是故意不拉 DTR 的(避免复位), 所以这种卡死不会自己好。
    兜底: 改用 hard_reset() 打 DTR 脉冲硬复位 + 抢在 main.py 之前打断,
    这条路径是 repl.py 里久经使用的序列。
    """
    print(">>> 打断板上正在跑的脚本 ...")
    R.drain(s, 0.8)                       # 先把积压的数据读走, 让板子有机会解阻塞
    if R.sync_to_prompt(s, timeout=12.0):
        return
    print(">>> Ctrl-C 没反应(板子可能卡在 print 里), 改用硬复位打断 ...")
    if not R.hard_reset(s):
        print("!! 硬复位也没成, 后面的读取可能失败")


def reset_board(port):
    """DTR 复位脉冲, 让 main.py 重新自启(板子回到正常检测状态)。"""
    import time as _t
    s = R.open_port(port)
    try:
        s.reset_input_buffer()
        print(">>> 收尾: 复位板子回 main.py 正常检测 ...")
        s.dtr = True
        _t.sleep(0.3)
        s.dtr = False
        _t.sleep(0.5)
    finally:
        s.close()
    print(">>> 已复位")


def apply_focal(px, cy, path=None):
    """把 FOCAL_PX / CAM_CY 写进 body_detect.py。逐条 assert 命中数, 不静默改。

    path 只给自测用(传个副本), 正常调用走默认的 body_detect.py。
    改完会做一次语法检查, 语法坏了自己回滚 —— 标定结果再重要也不能把
    一个跑不起来的主程序留在板上。
    """
    import py_compile
    import shutil
    import tempfile
    p = path or os.path.join(ROOT, "body_detect.py")
    orig = io.open(p, "rb").read()
    raw = orig.decode("utf-8")
    edits = [
        (r"(?m)^FOCAL_PX\s*=\s*[\d.]+\s*#.*$",
         "FOCAL_PX    = %.1f    # 焦距(像素), 棋盘格标定实测" % px),
        (r"(?m)^CAM_CY\s*=\s*\d+\s*#.*$",
         "CAM_CY        = %d    # 主点所在行, 棋盘格标定实测" % cy),
    ]
    for pat, rep in edits:
        hits = re.findall(pat, raw)
        assert len(hits) == 1, "锚点命中 %d 次: %s" % (len(hits), pat)
        raw = re.sub(pat, lambda m, r=rep: r, raw, count=1)

    io.open(p, "wb").write(raw.encode("utf-8"))
    try:
        with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False) as tf:
            tmp = tf.name
        py_compile.compile(p, cfile=tmp, doraise=True)
        os.remove(tmp)
    except Exception as e:
        io.open(p, "wb").write(orig)          # 回滚
        print("!! 改完语法坏了, 已回滚: %r" % e)
        return False
    print(">>> 已改 body_detect.py: FOCAL_PX=%.1f  CAM_CY=%d (语法检查通过)"
          % (px, cy))
    print(">>> 别忘了跑: MSYS_NO_PATHCONV=1 python tools/deploy.py COM16")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default=None,
                    help="串口, 如 COM16。省略则自动找 CH340")
    ap.add_argument("--out", default=os.path.join(ROOT, "testimgs", "chess_imgs"),
                    help="本地保存目录")
    ap.add_argument("--from", dest="from_n", type=int, default=0,
                    help="只拉编号 >= N 的图(跳过旧的同姿态照片)")
    ap.add_argument("--pull-only", action="store_true", help="只拉图, 不标定")
    ap.add_argument("--apply", action="store_true",
                    help="标定成功后自动把 FOCAL_PX/CAM_CY 写进 body_detect.py")
    ap.add_argument("--local-only", action="store_true",
                    help="不碰板子, 直接拿 --out 目录里已有的图重新标定")
    args = ap.parse_args()

    if not os.path.isdir(args.out):
        os.makedirs(args.out)

    if args.local_only:
        return do_calib(args.out, args.apply)

    args.port = pick_port(args.port)

    s = R.open_port(args.port)
    try:
        R.drain(s, 0.3)
        stop_board_script(s)

        ids = list_board_chess(s)
        print(">>> 板上 chess_*.jpg 共 %d 张: %s"
              % (len(ids), ids if len(ids) <= 12 else "%s ..." % ids[:12]))
        want = [i for i in ids if i >= args.from_n]
        if not want:
            print("!! 没有可拉的图(编号 >= %d). 采集脚本跑起来了吗?" % args.from_n)
            return 1
        print(">>> 要拉 %d 张 (编号 >= %d)" % (len(want), args.from_n))

        ok = 0
        for i in want:
            remote = "/sd/chess_%03d.jpg" % i
            local = os.path.join(args.out, "chess_%03d.jpg" % i)
            try:
                R.cmd_get(s, remote, local)
                ok += 1
            except Exception as e:
                print("!! 拉 %s 失败: %r" % (remote, e))
        print(">>> 成功拉回 %d / %d 张 -> %s" % (ok, len(want), args.out))
    finally:
        s.close()

    if args.pull_only:
        print(">>> --pull-only, 不标定. 手动标定:")
        print("    %s tools/calib_chess.py %s" % (pick_python(), args.out))
        return 0

    rc = do_calib(args.out, args.apply)
    reset_board(args.port)
    return rc


def do_calib(out_dir, do_apply):
    """拿一个目录里的图跑标定, 打印结果, 可选自动写进 body_detect.py。"""
    print("")
    print("=" * 62)
    print(" 开始标定: %s" % out_dir)
    print("=" * 62)
    r = subprocess.run([pick_python(), os.path.join(HERE, "calib_chess.py"), out_dir],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    # 丢掉 OpenCV 那行 JPEG 尾部字节的无害告警, 别吓到人
    out = "\n".join(ln for ln in out.splitlines()
                    if not ln.startswith("Corrupt JPEG data"))
    print(out)

    if r.returncode != 0:
        print("!! 标定没成功, 看上面的原因(多半是有效图不够或姿态太单一)")
        return r.returncode

    if do_apply:
        m = re.search(r"FOCAL_PX\s*=\s*([\d.]+)", out)
        m2 = re.search(r"CAM_CY\s*=\s*(\d+)", out)
        if m and m2:
            apply_focal(float(m.group(1)), int(m2.group(1)))
        else:
            print("!! 解析不到 FOCAL_PX/CAM_CY, 没自动改")
    return 0


if __name__ == "__main__":
    sys.exit(main())
