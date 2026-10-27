# -*- coding: utf-8 -*-
"""
K210 CanMV 串口 REPL 客户端（不占用 IDE 时可用）

用法:
  python tools/repl.py COM16 info                  # 打印板子信息
  python tools/repl.py COM16 run <本地py文件>       # 把脚本发到板子上执行
  python tools/repl.py COM16 eval "<一行代码>"      # 执行一行代码
  python tools/repl.py COM16 put <本地文件> <板上路径>  # 上传文件
  python tools/repl.py COM16 ls [路径]              # 列目录

关键坑: 打开串口必须 dtr=False / rts=False，否则 CH340 会拉复位脚，板子直接重启。
"""
import io
import os
import sys
import time

import serial

PORT = "COM16"
BAUD = 115200
CHUNK = 192          # raw REPL 分块发送大小，太快会丢
CTRL_A = b"\x01"
CTRL_B = b"\x02"
CTRL_C = b"\x03"
CTRL_D = b"\x04"


def open_port(port=PORT, baud=BAUD):
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 0.2
    s.dtr = False
    s.rts = False
    s.open()
    s.dtr = False
    s.rts = False
    return s


def drain(s, wait=0.15):
    time.sleep(wait)
    return s.read(65536)


def sync_to_prompt(s, timeout=10.0):
    """
    反复 Ctrl-C，直到板子回到 friendly REPL (>>>)。
    板子开机跑 main.py 时会 init sensor+lcd，是 C 层阻塞，秒级才响应 Ctrl-C。
    所以必须循环发 + 耐心等，不能用固定次数。
    """
    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        s.write(CTRL_C)
        time.sleep(0.25)
        buf += s.read(65536)
        if buf.rstrip().endswith(b">>>"):
            return True
    print("!! sync_to_prompt 超时，最后收到: %r" % buf[-200:])
    return False


def enter_raw(s):
    if not sync_to_prompt(s):
        print("!! 板子没回到 >>> 提示符")
        return False
    s.reset_input_buffer()
    s.write(CTRL_A)
    t = time.time()
    buf = b""
    while time.time() - t < 4:
        c = s.read(1)
        if c:
            buf += c
            if buf.endswith(b">"):
                return True
    print("!! 进 raw REPL 失败, 收到: %r" % buf[:200])
    return False


def exit_raw(s):
    s.write(CTRL_B)
    time.sleep(0.1)
    drain(s)


def send_source(s, src, timeout=180):
    """把源码分块喂进 raw REPL 并执行，返回 (stdout, stderr)。"""
    data = src.encode("utf-8")
    for i in range(0, len(data), CHUNK):
        s.write(data[i:i + CHUNK])
        time.sleep(0.004)
    s.write(CTRL_D)

    s.timeout = timeout
    # 响应格式: OK <stdout> \x04 <stderr> \x04
    head = s.read_until(b"OK")
    if not head.endswith(b"OK"):
        s.timeout = 2
        return b"", b"<no OK, got: " + head[:300] + b">"
    out = s.read_until(b"\x04")
    err = s.read_until(b"\x04")
    s.timeout = 0.2
    if out.endswith(b"\x04"):
        out = out[:-1]
    if err.endswith(b"\x04"):
        err = err[:-1]
    return out, err


def exec_code(s, src, timeout=180, echo=True):
    if not enter_raw(s):
        raise RuntimeError("进不去 raw REPL（板子没响应？换个 DTR 组合试试）")
    out, err = send_source(s, src, timeout)
    exit_raw(s)
    if echo:
        if out:
            sys.stdout.write(out.decode("utf-8", "replace"))
            sys.stdout.flush()
        if err:
            sys.stdout.write("\n--- STDERR ---\n")
            sys.stdout.write(err.decode("utf-8", "replace"))
            sys.stdout.flush()
    return out, err


# ------------------------------------------------------------
def cmd_info(s):
    exec_code(s, "import sys, gc, os\n"
                 "print('platform  :', sys.platform)\n"
                 "print('impl      :', sys.implementation)\n"
                 "print('version   :', sys.version)\n"
                 "print('mem_free  :', gc.mem_free())\n"
                 "print('root      :', os.listdir('/'))\n")


def cmd_ls(s, path="/"):
    exec_code(s, "import os\nprint(os.listdir('%s'))\n" % path)


def cmd_run(s, path):
    with io.open(path, "r", encoding="utf-8") as f:
        src = f.read()
    print(">>> 上传并执行 %s (%d bytes)" % (path, len(src)))
    exec_code(s, src)
    print(">>> 执行结束")


def cmd_eval(s, code):
    exec_code(s, code)


def cmd_put(s, local, remote):
    """把本地文件 base64 分块写进板子。"""
    import base64
    import time as _t
    with open(local, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode()
    print(">>> 上传 %s -> %s (%d bytes, b64 %d)" % (local, remote, len(raw), len(b64)))

    setup = ("import ubinascii\n"
             "f = open('%s','wb')\n" % remote)
    if not enter_raw(s):
        raise RuntimeError("进不去 raw REPL")

    out, err = send_source(s, setup)
    if err:
        print("打开文件失败:", err.decode("utf-8", "replace"))
        exit_raw(s)
        return

    step = 1024
    t0 = _t.time()
    total = len(b64)
    for i in range(0, total, step):
        code = "f.write(ubinascii.a2b_base64('%s'))\n" % b64[i:i + step]
        s.write(code.encode() + CTRL_D)
        s.timeout = 30
        s.read_until(b"OK")
        s.read_until(b"\x04")
        s.read_until(b"\x04")
        s.timeout = 0.2
        done = i + step
        if done > total:
            done = total
        el = _t.time() - t0
        speed = done / el if el > 0 else 0
        eta = (total - done) / speed if speed > 0 else 0
        sys.stdout.write("\r    写入 %3d%%  %.1f KB/s  剩余 %3.0fs   " %
                         (done * 100 // total, speed / 1024.0, eta))
        sys.stdout.flush()
    print("")

    o, e = send_source(s, "f.close()\nimport os\nprint('size', os.stat('%s')[6])\n" % remote)
    sys.stdout.write(o.decode("utf-8", "replace"))
    if e:
        print("ERR:", e.decode("utf-8", "replace"))
    exit_raw(s)


def soft_reset(s):
    """软复位板子，清掉上次脚本泄漏的 KPU/内存，等 main.py 跑完回到 REPL。"""
    if not sync_to_prompt(s):
        return False
    s.reset_input_buffer()
    s.write(CTRL_D)
    time.sleep(1.0)
    drain(s, 0.5)
    return sync_to_prompt(s)


def hard_reset(s, tries=4):
    """
    硬复位 + 抢在 main.py 跑起来之前打断。实测最可靠的序列：
      DTR 拉高 0.3s 再放开 -> 等启动，期间狂发 Ctrl-C -> 直到看到 >>> 
    一次不成会自动重试（LittleFS 挂载偶尔会拖）。
    """
    buf = b""
    for i in range(tries):
        s.reset_input_buffer()
        s.dtr = True
        time.sleep(0.3)
        s.dtr = False
        t0 = time.time()
        buf = b""
        while time.time() - t0 < 7:
            s.write(CTRL_C)
            time.sleep(0.15)
            d = s.read(8192)
            if d:
                buf += d
            if buf.rstrip().endswith(b">>>"):
                return True
    print("!! 复位失败（试了 %d 次），最后收到: %r" % (tries, buf[-200:]))
    return False


GET_SCRIPT = """
import ubinascii, sys
f = open('%s','rb')
while True:
    d = f.read(1500)
    if not d:
        break
    sys.stdout.write(ubinascii.b2a_base64(d).decode().strip() + chr(10))
f.close()
print('GETEOF')
"""


def cmd_get(s, remote, local):
    """把板子上的文件 base64 读回来。"""
    print(">>> 读取 %s -> %s" % (remote, local))
    lines = []
    out, err = exec_code(s, GET_SCRIPT % remote, echo=False)
    for ln in out.decode("utf-8", "replace").splitlines():
        ln = ln.strip()
        if not ln or ln == "GETEOF":
            continue
        try:
            lines.append(ln)
        except Exception:
            pass
    import base64
    data = base64.b64decode("".join(lines))
    with open(local, "wb") as f:
        f.write(data)
    print(">>> 保存 %s (%d bytes, %d 段)" % (local, len(data), len(lines)))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    port = sys.argv[1]
    cmd = sys.argv[2]
    s = open_port(port)
    try:
        # 上电日志先清掉
        drain(s, 0.3)
        if cmd not in ("info", "get"):
            # 跑脚本前硬复位并早打断 main.py，保住系统堆给 KPU 用
            # （get 只是读文件，不需要复位，省时间）
            print(">>> 硬复位 + 打断 main.py ...")
            if not hard_reset(s):
                print("!! 硬复位失败，继续尝试")
        if cmd == "info":
            cmd_info(s)
        elif cmd == "ls":
            cmd_ls(s, sys.argv[3] if len(sys.argv) > 3 else "/")
        elif cmd == "run":
            cmd_run(s, sys.argv[3])
        elif cmd == "eval":
            cmd_eval(s, sys.argv[3])
        elif cmd == "put":
            cmd_put(s, sys.argv[3], sys.argv[4])
        elif cmd == "get":
            cmd_get(s, sys.argv[3], sys.argv[4])
        else:
            print("未知命令:", cmd)
            return 1
    finally:
        s.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
