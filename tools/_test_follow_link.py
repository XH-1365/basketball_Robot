# -*- coding: utf-8 -*-
"""follow_link.py 纯逻辑层离线单测（PC 上跑, 不需要板子）。

覆盖: 校验和、帧构造/解析往返、锁定状态机(选人/保锁/丢失/换人/视觉失效)。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import follow_link as F  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    if cond:
        print("  [OK] %s" % name)
    else:
        FAILS.append(name)
        print("  [!!] %s  %s" % (name, extra))


# ---------- 1) 异或校验已知向量 ----------
print("== 1) xor_cs ==")
check("xor('AB')=03", F.xor_cs("AB") == "03",
      F.xor_cs("AB"))                    # 0x41^0x42=0x03
check("xor('K210')=78", F.xor_cs("K210") == "78",
      F.xor_cs("K210"))                  # 0x4B^0x32^0x31^0x30=0x78
check("xor('')=00", F.xor_cs("") == "00")

# ---------- 2) 帧构造/解析往返 ----------
print("== 2) build/parse 往返 ==")
cases = [
    (1, "L", 3, 4.2, 2.15),
    (9999, "S", 0, 0.0, None),
    (12345, "X", 0, -12.7, 0.88),      # seq & 0xFFFF = 57209
    (7, "L", 1, -90.0, 15.0),
    (8, "L", 2, 0.0, 0.30),
]
for seq, st, tid, err, dist in cases:
    f = F.build_frame(seq, st, tid, err, dist)
    p = F.parse_frame(f)
    ok = (p is not None and p["seq"] == (seq & 0xFFFF) and p["state"] == st
          and p["tid"] == tid and abs(p["err_deg"] - err) < 0.05
          and ((dist is None and p["dist_m"] == -1.0)
               or (dist is not None and abs(p["dist_m"] - dist) < 0.005)))
    check("roundtrip %s" % f.strip(), ok, repr(p))

# 已知样例帧, 肉眼可核对协议文档
f = F.build_frame(123, "L", 3, 4.2, 2.15)
check("样例帧格式", f == "K210,123,L,3,4.2,2.15*" + F.xor_cs("K210,123,L,3,4.2,2.15") + "\n", repr(f))
print("   样例: %r" % f)

# 坏帧必须拒收
check("校验错拒收", F.parse_frame(f[:-3] + "ff\n") is None)
check("状态非法拒收", F.parse_frame("K210,1,Z,0,0.0,1.00*%s\n"
                                    % F.xor_cs("K210,1,Z,0,0.0,1.00")) is None)
check("字段缺失拒收", F.parse_frame("K210,1,L,0,0.0*00\n") is None)
check("空行拒收", F.parse_frame("") is None)
check("带\\r容忍", F.parse_frame(f.strip() + "\r\n") is not None)


# ---------- 3) 锁定状态机 ----------
print("== 3) FollowState ==")
def item(tid, x, w=20):
    return (tid, (x, 50, w, 100), False, 3, 2.0, "H")

fs = F.FollowState(lost_frames=5)
CX = 160

# 画面右侧的人(中心 210, 偏 +50) -> 锁它; 左侧人中心 40 偏 -120 更远
st, tid, err, dist = fs.update([item(1, 30), item(2, 200)], CX, True)
check("首次选最居中", (st, tid, err) == ("L", 2, 50), (st, tid, err))

# 重来, 构造无歧义场景
fs = F.FollowState(lost_frames=5)
st, tid, err, dist = fs.update([item(1, 60), item(2, 190)], CX, True)
# 1 中心=70(偏-90), 2 中心=200(偏+40) -> 锁 2
check("锁最居中者", (st, tid, err) == ("L", 2, 40), (st, tid, err))

# 锁定保持: 人移到别处, id 不变
st, tid, err, _ = fs.update([item(1, 100), item(2, 60)], CX, True)
check("保锁不换人", (st, tid) == ("L", 2), (st, tid))

# 锁定目标消失但画面里还有别人 -> 立即改锁最居中者(不傻停)
st, tid, err, _ = fs.update([item(1, 100)], CX, True)
check("目标消失改锁他人", (st, tid, err) == ("L", 1, -50), (st, tid, err))
for _ in range(5):
    fs.update([], CX, True)
# 6 帧后目标重新出现 -> 锁最居中者(允许换人)
st, tid, err, _ = fs.update([item(1, 100)], CX, True)
check("放弃后重新选人", (st, tid) == ("L", 1), (st, tid))
check("换锁计数", fs.switches >= 1, fs.switches)

# 画面一直没人 -> 持续 S
fs2 = F.FollowState(5)
outs = [fs2.update([], CX, True) for _ in range(10)]
check("持续无人全S", all(o[0] == "S" for o in outs))

# 视觉不可用 -> X
st, tid, err, dist = fs2.update([item(1, 100)], CX, False)
check("无模型发X", (st, tid, err, dist) == ("X", 0, 0.0, None))

print()
if FAILS:
    print("FAIL: %d 项 -> %s" % (len(FAILS), FAILS))
    sys.exit(1)
print("ALL PASS")
