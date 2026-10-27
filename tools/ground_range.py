# -*- coding: utf-8 -*-
"""
地面法能测的距离范围 —— 用来决定相机怎么装。

为什么需要这个:
  地面法靠"脚尖在画面的第几行"反算距离。画面的行是有限的(0~H-1),
  所以能看到的【地面距离】也是一个有限区间。相机架太低或俯角太平,
  近处的人脚就掉到画面外面去了 —— 这时候地面法不是"不准", 是【根本测不到】。

几何:
  第 y 行对应相对光轴的俯角  beta = atan((y - cy) / f)
  叠加相机俯角后视线与水平面的夹角 alpha = pitch + beta
  地面距离 D = hc / tan(alpha)

  画面底边 y=H-1  -> alpha = pitch + atan((H-1-cy)/f)  -> 最近能测
  画面顶边 y=0    -> alpha = pitch + atan(-cy/f)       -> 最远能测
      (注意: alpha <= 0 说明这条视线朝天, 看不到地面 -> 那一侧无上限)

用法:
  python tools/ground_range.py                    # 默认 hc=1.20
  python tools/ground_range.py --hc=1.50
  python tools/ground_range.py --hc=1.20 --f=277 --cy=120 --h=240
"""
import math
import sys


def limits(hc, f, cy, H, pitch_deg):
    """返回 (最近米, 最远米 或 None 表示无上限)。"""
    p = math.radians(pitch_deg)
    a_near = p + math.atan((H - 1 - cy) / f)
    a_far = p + math.atan((0 - cy) / f)
    near = hc / math.tan(a_near) if a_near > 0.001 else None
    far = hc / math.tan(a_far) if a_far > 0.001 else None
    return near, far


def main():
    hc = 1.20
    f = 277.0
    cy = 120.0
    H = 240
    for a in sys.argv[1:]:
        if a.startswith("--hc="):
            hc = float(a[5:])
        elif a.startswith("--f="):
            f = float(a[4:])
        elif a.startswith("--cy="):
            cy = float(a[5:])
        elif a.startswith("--h="):
            H = float(a[3:])

    print("参数: 相机高 %.2f m  FOCAL_PX=%.1f  CAM_CY=%.0f  画面高=%.0f  "
          "(画面底边对应像素角 %.2f 度)"
          % (hc, f, cy, H, math.degrees(math.atan((H - 1 - cy) / f))))

    for pitch in (0, 5, 10, 15, 20, 25, 30, 35):
        near, far = limits(hc, f, cy, H, pitch)
        ns = ("%.2f m" % near) if near else "--(看不到地面)"
        fs = ("%.1f m" % far) if far else "无限远"
        print("  俯角 %2d 度 -> 能测 %8s ~ %8s" % (pitch, ns, fs))

    print("\n怎么读这张表:")
    print("  '能测' 的下限 > 你想测的最近距离 => 近处的人脚已经掉出画面底边了,")
    print("  这一档俯角对近处【无效】(屏幕上会显示 dG=--)。")
    print("  下限越小说明越能覆盖近处; 但俯角越大, 远处越容易被'顶边'截断。")
    print("\n经验值: 相机架 1.5~1.8 m 高、俯角 20~25 度, 一般能覆盖 0.8~10 m,")
    print("        对'房间里的人'这个场景最合适。1.2 m 高 + 俯角 0 是测不了近处的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
