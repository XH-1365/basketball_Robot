# -*- coding: utf-8 -*-
"""
解析串口日志, 把里面的 base64 图片落盘。

★★ 核心: 按【字符流】读, 不按【行】读 ★★
   实测板子会在一条很长的 base64 行【中间】莫名插一个换行
   (原始字节: ...txrvl3s\\r\\n[RUN 15s/150s]\\r\\nWLSP...), 按行解析必丢块。
   所以本脚本的做法是:
     读到 "B <名字> <块号> <字节数> <校验和> " 之后, 忽略所有空白,
     继续攒 base64 字符, 直到攒够 ceil(字节数/3)*4 个, 或遇到终止符 '#',
     然后用 (字节数 + 校验和) 验一遍。换行插在哪儿都无害。

支持两种格式:
  新格式 capture_ram.py:
      ITEM cap_012.jpg 17545 35
      B cap_012.jpg 0 512 65024 <684个base64字符>#
      ...
      E cap_012.jpg 35
  旧格式 capture_stream.py (无校验, 仅供回看老日志):
      IMGBEGIN cap_009.jpg 17707
      B64 <base64>
      IMGEND cap_009.jpg

同一张图可以在日志里出现多遍(短按后自动回传 + 长按重吐), 按 (名字, 块号)
合并: 校验通过的块留下, 校验失败的计入"坏块", 后面收到好块就覆盖并计"修复"。

用法:
  python tools/parse_stream.py tools/_ram.log [输出目录]
输出目录默认 <项目>/testimgs/caps。
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)

ITEM_RE = re.compile(r"\bITEM\s+(\S+)\s+(\d+)\s+(\d+)")
B_HDR_RE = re.compile(r"B (\S+) (\d+) (\d+) (\d+) ")
SERVE_RE = re.compile(r"\bSERVE\s+count=(\d+)\s+tag=(\S+)")
BEGIN_RE = re.compile(r"IMGBEGIN\s+(\S+)\s+(\d+)")


def bump(files, name):
    info = files.get(name)
    if info is None:
        info = files[name] = {"size": 0, "nch": 0, "got": {}, "bad": set()}
    return info


def b64_len(nbytes):
    """按 base64 定义算: 每 3 字节 -> 4 字符, 向上取整。"""
    return 4 * ((nbytes + 2) // 3)


def scan_new(text, files, stat):
    pos = 0
    while True:
        m = B_HDR_RE.search(text, pos)
        if not m:
            break
        name = m.group(1)
        idx = int(m.group(2))
        dlen = int(m.group(3))
        dsum = int(m.group(4))
        need = b64_len(dlen)
        p = m.end()
        buf = []
        while len(buf) < need and p < len(text):
            ch = text[p]
            p += 1
            if ch.isspace():
                continue                       # 换行/空格一律跳过
            if ch == "#":
                break                          # 终止符: 本块到此为止
            buf.append(ch)
        pos = p
        payload = "".join(buf)
        info = bump(files, name)
        ok = False
        if len(payload) == need:
            try:
                raw = base64.b64decode(payload + "=" * (-len(payload) % 4))
                if len(raw) == dlen and (sum(raw) & 0xFFFF) == dsum:
                    ok = True
            except Exception:
                ok = False
        if ok:
            if idx in info["bad"]:
                info["bad"].discard(idx)
                stat["fixed"] += 1
                stat["bad_unfixed"].discard((name, idx))
            info["got"][idx] = raw
        else:
            info["bad"].add(idx)
            stat["bad"] += 1
            stat["bad_unfixed"].add((name, idx))

    for m in ITEM_RE.finditer(text):
        info = bump(files, m.group(1))
        info["size"] = int(m.group(2))
        info["nch"] = int(m.group(3))
    for m in SERVE_RE.finditer(text):
        stat["passes"].append((m.group(2), int(m.group(1))))

    # ---- 旧格式(同样按字符流拼) ----
    for m in BEGIN_RE.finditer(text):
        name = m.group(1)
        size = int(m.group(2))
        end = text.find("IMGEND", m.end())
        seg = text[m.end():end if end > 0 else len(text)]
        seg = seg.replace("B64 ", "")          # 去掉每行前缀
        payload = "".join(ch for ch in seg if not ch.isspace())
        need = b64_len(size) if size > 0 else len(payload)
        payload = payload[:need]
        info = bump(files, name + "#legacy")
        info["size"] = size
        info["nch"] = 1
        try:
            raw = base64.b64decode(payload + "=" * (-len(payload) % 4))
            info["got"][0] = raw
        except Exception as e:
            stat["bad"] += 1
            stat["bad_unfixed"].add((name, 0))
            print("  (旧格式 %s 解码失败 %r)" % (name, e))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    log = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(PROJ, "testimgs", "caps")
    if not os.path.isdir(outdir):
        os.makedirs(outdir)

    with open(log, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()

    files = {}
    stat = {"passes": [], "bad": 0, "fixed": 0, "bad_unfixed": set()}
    scan_new(text, files, stat)

    print("解析 %s (%d 字符)" % (log, len(text)))
    print("输出 %s" % outdir)
    if stat["passes"]:
        print("日志里的回传批次: %d  %s" % (len(stat["passes"]), stat["passes"]))
    print("-" * 64)

    ok, partial = [], []
    for name in sorted(files.keys()):
        info = files[name]
        nch = info["nch"] or 0
        got = info["got"]
        if nch == 0:
            continue
        miss = [i for i in range(nch) if i not in got]
        if miss:
            partial.append((name, len(got), nch, miss))
            continue
        data = b"".join(got[i] for i in range(nch))
        head = data[:2] == b"\xff\xd8"
        tail = data[-2:] == b"\xff\xd9"
        szok = (info["size"] <= 0) or (len(data) == info["size"])
        p = os.path.join(outdir, name.replace("#legacy", ""))
        with open(p, "wb") as g:
            g.write(data)
        if head and tail and szok:
            ok.append((name, len(data), nch, info["size"]))
        else:
            partial.append((name, len(got), nch,
                            ["JPEG头=%s 尾=%s 长=%d/期望%d"
                             % (head, tail, len(data), info["size"])]))

    print("完整取回 %d 张:" % len(ok))
    for n, sz, nch, exp in ok:
        flag = "" if sz == exp else "  <-- 长度与板上报的 %d 不一致!" % exp
        print("    %-18s %7d bytes  %d 块%s" % (n, sz, nch, flag))
    if partial:
        print("没收全 %d 张(再长按一次 BOOT 键重吐, 然后重跑本脚本):" % len(partial))
        for n, g, t, miss in partial:
            print("    %-18s %d/%d 块  缺: %s" % (n, g, t, miss))
    print("-" * 64)
    print("坏块(校验失败): %d 次, 其中被后续重传覆盖修好: %d 次"
          % (stat["bad"], stat["fixed"]))
    # 只按【最终状态】算残留: 某块只要拿到过一次校验通过的数据就算到手,
    # 后面再来一遍坏的也不该把它算成没收全。
    unresolved = []
    for name in sorted(files.keys()):
        info = files[name]
        for i in range(info["nch"] or 0):
            if i not in info["got"]:
                unresolved.append((name, i,
                                   "校验失败" if i in info["bad"] else "没收到"))
    if unresolved:
        print("仍未拿到的块 (%d):" % len(unresolved))
        for name, i, why in unresolved:
            print("    %-18s 第%3d 块  %s" % (name, i, why))
    else:
        print("所有块都校验通过, 无残留。")
    if not ok and not partial:
        print("日志里没找到任何图片 —— 是不是没按按钮?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
