# -*- coding: utf-8 -*-
"""height_check.parse_dets 的离线自测 —— 不能拿板子当测试台。

真实行样例来自 body_detect.py 的串口上报:
  parts.append("#%d x%d,y%d,w%d,h%d,%.2f%s%s"
               % (tid, b[0], b[1], b[2], b[3], b[4], side,
                  ",HOT" if ... else "",
                  (",d%.1f%s" % (dist, dmode)) if dist else ",d?"))
  print("DET n=%d total=%d | %s" % (len(items), total, " ; ".join(parts)))
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from height_check import parse_dets  # noqa: E402

CASES = [
    ("DET n=1 total=5 | #1 x125,y12,w58,h191,0.88,d2.4H",
     [(1, 125, 12, 58, 191, 0.88, 2.4, "H")]),

    ("DET n=1 total=5 | #1 x10,y20,w30,h40,0.75,HOT,d3.1G",
     [(1, 10, 20, 30, 40, 0.75, 3.1, "G")]),

    ("DET n=1 total=5 | #1 x10,y20,w30,h40,0.75,d?",
     [(1, 10, 20, 30, 40, 0.75, None, "")]),

    ("DET n=1 total=5 | #1 x10,y20,w30,h40,0.75,HOT,d?",
     [(1, 10, 20, 30, 40, 0.75, None, "")]),

    ("DET n=2 total=5 | #1 x10,y20,w30,h40,0.90,d2.0H ; #2 x100,y30,w40,h50,0.80,d5.0H",
     [(1, 10, 20, 30, 40, 0.90, 2.0, "H"),
      (2, 100, 30, 40, 50, 0.80, 5.0, "H")]),

    ("DET n=1 total=0 | #1 x1,y2,w3,h4,0.50,d12.3A",
     [(1, 1, 2, 3, 4, 0.50, 12.3, "A")]),

    # 这些应该解析出 0 个
    ("DET none | total=0", []),
    ("PREVIEW no_model frame=15", []),
    ("[BODY] 就绪 (旧版 API)", []),
    ("ALARM person_in_zone n=1 frame=30", []),
]

fails = 0
for ln, want in CASES:
    got = parse_dets(ln)
    ok = got == want
    if not ok:
        fails += 1
    print("%s  %-64s" % ("PASS" if ok else "FAIL", ln[:64]))
    if not ok:
        print("        want %r" % (want,))
        print("        got  %r" % (got,))

print("")
if fails:
    print("!! %d / %d 个用例失败" % (fails, len(CASES)))
    sys.exit(1)
print("全部 %d 个用例通过" % len(CASES))
