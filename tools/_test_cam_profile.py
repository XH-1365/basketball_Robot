# -*- coding: utf-8 -*-
"""
双镜头配置逻辑的 PC 端单测（不需要板子）。

做法: 在导入 body_detect 之前，把 machine/image/lcd/sensor/fpioa_manager/maix
全部换成桩模块，然后直接调 apply_cam_profile()，看型号匹配和参数覆盖对不对。

用法: python tools/_test_cam_profile.py
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

FAILS = []


def check(cond, msg, extra=""):
    print(("  [OK] " if cond else "  [!!] ") + msg + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(msg)


class _Stub(object):
    """不认识的方法一律当无参可调用占位，避免桩模块写一堆空函数。"""
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        f = lambda *a, **kw2: None
        setattr(self, k, f)
        return f


# ---- sensor 桩: get_id 可换 ----
class _SensorStub(_Stub):
    def __init__(self):
        _Stub.__init__(self)
        self.QVGA = 2
        self.RGB565 = 1
        self.id_value = 22080
        self.id_raises = False

    def get_id(self):
        if self.id_raises:
            raise OSError("i2c fail")
        return self.id_value


sens = _SensorStub()
sys.modules["sensor"] = sens
sys.modules["image"] = _Stub(Image=lambda **kw: _Stub(), __name__="image")
sys.modules["lcd"] = _Stub()
sys.modules["machine"] = _Stub()
sys.modules["fpioa_manager"] = _Stub(fm=_Stub())
sys.modules["maix"] = _Stub(GPIO=_Stub(), KPU=_Stub())

import body_detect as bd  # noqa: E402

print("== 1) CAM_PROFILES 结构 ==")
check(set(bd.CAM_PROFILES.keys()) == {"GC2145", "OV5640"},
      "两个镜头档案齐全", sorted(bd.CAM_PROFILES.keys()))
for name, p in bd.CAM_PROFILES.items():
    check(all(k in p for k in ("label", "ids", "hmirror", "vflip", "focal_px", "cam_cy")),
          "%s 字段完整" % name, sorted(p.keys()))
    check(isinstance(p["ids"], tuple) and p["ids"], "%s ids 非空元组" % name, p["ids"])

print("\n== 2) AUTO 识别 ==")
bd.CAM_KIND = "AUTO"

sens.id_value = 0x5640
kind = bd.apply_cam_profile()
check(kind == "OV5640", "id=0x5640 -> OV5640", kind)
check(bd.VFLIP is True and bd.HMIRROR is False, "OV5640 方向 vflip=True/hmirror=False",
      (bd.VFLIP, bd.HMIRROR))
check(bd.FOCAL_PX == 0, "OV5640 未标定 -> focal_px=0（测距自动关闭）", bd.FOCAL_PX)

sens.id_value = 45
kind = bd.apply_cam_profile()
check(kind == "GC2145", "id=45 -> GC2145", kind)
check(bd.VFLIP is False and bd.HMIRROR is False, "GC2145 方向两者皆 False",
      (bd.VFLIP, bd.HMIRROR))
check(abs(bd.FOCAL_PX - 408.9) < 1e-6 and bd.CAM_CY == 102,
      "GC2145 标定值 408.9/102", (bd.FOCAL_PX, bd.CAM_CY))

sens.id_value = 12345
kind = bd.apply_cam_profile()
check(kind == "GC2145", "未知 id -> 回退 GC2145", kind)

sens.id_raises = True
kind = bd.apply_cam_profile()
check(kind == "GC2145", "get_id 抛异常 -> 回退 GC2145", kind)
sens.id_raises = False

print("\n== 3) 强制指定 CAM_KIND ==")
bd.CAM_KIND = "OV5640"
sens.id_value = 45              # 硬件说是 GC2145，但代码强制 OV5640
kind = bd.apply_cam_profile()
check(kind == "OV5640", "强制 CAM_KIND=OV5640 生效（不看 id）", kind)
check(bd.VFLIP is True, "强制模式下 VFLIP 仍按 OV5640 生效", bd.VFLIP)

bd.CAM_KIND = "不存在的型号"
kind = bd.apply_cam_profile()
check(kind == "GC2145", "非法 CAM_KIND -> 回退 GC2145", kind)

print("\n== 4) focal_px=0 时测距自动失效 ==")
bd.CAM_KIND = "OV5640"
bd.apply_cam_profile()
d, ok = bd.estimate_dist(200)          # 框高 200px
check(d is None and ok is False, "OV5640(未标定) estimate_dist 返回 None", (d, ok))
d2, ok2 = bd.est_dist_ground(239)
check(d2 is None and ok2 is False, "OV5640(未标定) 地面法也返回 None", (d2, ok2))

bd.CAM_KIND = "GC2145"
bd.apply_cam_profile()
d3, ok3 = bd.estimate_dist(200)
check(ok3 is True and d3 is not None and 3.0 < d3 < 4.0,
      "GC2145 框高200px -> 约 3.5m", (d3, ok3))

print("\n" + ("===== 全部通过 =====" if not FAILS else "===== %d 项失败 =====" % len(FAILS)))
sys.exit(0 if not FAILS else 1)
