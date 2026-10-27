# -*- coding: utf-8 -*-
"""带重试的 /sd 推送驱动（SD 卡抽风时的兜底, 2026-10-23）。

用法: python tools/_push_sd.py COM12
逻辑: 每个目标先核对板上大小, 不对就 cmd_put, 失败/不符就硬复位重来, 最多 5 轮。
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repl as R  # noqa: E402

ROOT = os.path.dirname(HERE)
JOBS = (
    (os.path.join(ROOT, "body_detect.py"), "/flash/main.py"),
    (os.path.join(ROOT, "body_detect.py"), "/sd/main.py"),
    (os.path.join(ROOT, "follow_link.py"), "/flash/follow_link.py"),
    (os.path.join(ROOT, "follow_link.py"), "/sd/follow_link.py"),
)


def board_size(s, remote):
    out, err = R.exec_code(s, "import os\nprint(os.stat('%s')[6])\n" % remote,
                           echo=False, timeout=15)
    txt = out.decode("utf-8", "replace").strip()
    try:
        return int(txt.splitlines()[-1])
    except Exception:
        return None


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM12"
    s = R.open_port(port)
    R.drain(s, 0.3)
    print(">>> 复位打断 ...")
    R.hard_reset(s)

    for round_i in range(1, 6):
        print("\n===== 第 %d 轮 =====" % round_i)
        pending = []
        for local, remote in JOBS:
            want = os.path.getsize(local)
            got = board_size(s, remote)
            if got == want:
                print("  [OK-已一致] %s (%d)" % (remote, want))
            else:
                print("  [需推送]   %s 板上=%s 本地=%d" % (remote, got, want))
                pending.append((local, remote))
        if not pending:
            print("\n四份全部一致, 完成")
            return 0
        for local, remote in pending:
            try:
                R.cmd_put(s, local, remote)
            except Exception as e:
                print("  put 异常:", repr(e))
        # 核验
        bad = []
        for local, remote in pending:
            want = os.path.getsize(local)
            got = board_size(s, remote)
            if got != want:
                bad.append(remote)
                print("  [!!] %s 大小不符 板上=%s 本地=%d" % (remote, got, want))
            else:
                print("  [OK] %s = %d" % (remote, got))
        if not bad:
            print("\n全部推送成功")
            return 0
        print(">>> 复位重来 (SD 抽风兜底) ...")
        R.hard_reset(s)
    print("!! 5 轮仍有失败项")
    return 1


if __name__ == "__main__":
    sys.exit(main())
