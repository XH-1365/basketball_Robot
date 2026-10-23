# -*- coding: utf-8 -*-
"""打滑对策: 轮速目标斜坡限幅 + 刹车增益回调."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(ROOT, 'Core', 'Src', 'main.c')
t = open(P, 'rb').read().decode('utf-8')

def rep(old, new, tag):
    global t
    n = t.count(old)
    assert n == 1, '%s: hit %d' % (tag, n)
    t = t.replace(old, new, 1)

# 1. PD 区加斜坡宏, 刹车增益回调
rep('#define CHASSIS_BRAKE_GAIN      3.5f    /* 刹车时 KP/KD 放大倍数, 越大刹得越狠, 过大易顿挫/啸叫 (2.0->3.5: 20261023 实测松杆滑行, 加大制动力) */',
    '#define CHASSIS_BRAKE_GAIN      2.5f    /* 刹车时 KP/KD 放大倍数 (3.5->2.5: 已有斜坡限幅削掉阶跃, 不需要那么狠) */\n'
    '\n'
    '/*\n'
    ' * ==================== 轮速目标斜坡限幅 (防打滑) ====================\n'
    ' * 20261023 SWD 实测: 指令阶跃(0->2250rpm一拍)+大力矩 -> 轮子破抓地打滑,\n'
    ' * 稳态轮速 +-100~200rpm 摆动, 超调最高 10.6%。\n'
    ' * 对策: 每拍(10ms)目标最多变化 WHEEL_SLEW_RPM_PER_TICK, 0->2250 约 150ms。\n'
    ' * 调法: 还打滑减小; 起步肉/不跟手加大。0 = 关闭斜坡(恢复阶跃)。\n'
    ' */\n'
    '#define WHEEL_SLEW_RPM_PER_TICK  150',
    'pd')

# 2. 逆解之后插斜坡限幅
rep('\t\tchassis_inverse_kinematics(vx, vy, w, wheel);\n',
    '\t\tchassis_inverse_kinematics(vx, vy, w, wheel);\n'
    '\n'
    '\t\t/* 轮速目标斜坡限幅: 削掉指令阶跃, 防瞬间大电流破抓地打滑 */\n'
    '\t\t{\n'
    '\t\t\tstatic int32_t wheel_ramp[CHASSIS_MOTOR_NUM] = {0};\n'
    '\t\t\tfor (i = 0; i < CHASSIS_MOTOR_NUM; i++)\n'
    '\t\t\t{\n'
    '\t\t\t\tint32_t diff = wheel[i] - wheel_ramp[i];\n'
    '\t\t\t\tif (diff > WHEEL_SLEW_RPM_PER_TICK)\n'
    '\t\t\t\t{\n'
    '\t\t\t\t\tdiff = WHEEL_SLEW_RPM_PER_TICK;\n'
    '\t\t\t\t}\n'
    '\t\t\t\tif (diff < -WHEEL_SLEW_RPM_PER_TICK)\n'
    '\t\t\t\t{\n'
    '\t\t\t\t\tdiff = -WHEEL_SLEW_RPM_PER_TICK;\n'
    '\t\t\t\t}\n'
    '\t\t\t\twheel_ramp[i] += diff;\n'
    '\t\t\t\twheel[i] = wheel_ramp[i];\n'
    '\t\t\t}\n'
    '\t\t}\n',
    'ramp')

open(P, 'wb').write(t.encode('utf-8'))
print('anti-slip patch OK')
