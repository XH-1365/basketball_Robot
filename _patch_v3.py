# -*- coding: utf-8 -*-
"""MY_底盘_V3 合并补丁: 底盘(V2) + LANRC 7路无刷(DShot300) 同板固件.
1. bt_rc.h/c  : 追加 LANRC 的 A 键油门/方向键调速接口(底盘逻辑不动)
2. hal_conf   : 打开 HAL_TIM_MODULE_ENABLED
3. main.c     : tim/dshot 初始化 + ESC 油门逻辑 + V2_dbg 加 3 个 ESC 字段
4. uvprojx    : Application/User/Core 加 tim.c, RM2006 组加 dshot.c
每处 assert 命中 1 次, 不加 BOM。
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
NL = '\n'  # 本项目源码为 LF

def load(p):
    raw = open(p, 'rb').read()
    assert raw[:3] != b'\xef\xbb\xbf', p + ' BOM'
    return raw.decode('utf-8')

def save(p, t):
    open(p, 'wb').write(t.encode('utf-8'))
    print('saved:', os.path.relpath(p, ROOT))

def rep(t, old, new, tag):
    n = t.count(old)
    assert n == 1, '%s: hit %d' % (tag, n)
    return t.replace(old, new, 1)

# ---------- 1. bt_rc.h ----------
p = os.path.join(ROOT, 'BlueTooth', 'bt_rc.h')
t = load(p)
t = rep(t, '#endif /* BT_RC_H */',
    '/* ---- V3 追加: 与 LANRC 工程共用的按键接口 ----' + NL +
    ' * 按键2是位掩码: bit0=A bit1=B bit3=X bit4=Y bit6=LB bit7=RB' + NL +
    ' * 按键1是方向枚举(不是位掩码): 1=上 3=右 5=下 7=左' + NL +
    ' */' + NL +
    '#define BT_KEY2_A             0x01' + NL +
    '#define BT_DPAD_UP            1' + NL +
    '#define BT_DPAD_DOWN          5' + NL +
    NL +
    'uint8_t bt_rc_key_a(void);   /* A 键按住=1; 离线恒 0 */' + NL +
    'int8_t  bt_rc_dir(void);     /* 方向键上=+1 下=-1 其他=0; 离线恒 0 */' + NL +
    NL +
    '#endif /* BT_RC_H */',
    'bt_rc-h')
save(p, t)

# ---------- 2. bt_rc.c ----------
p = os.path.join(ROOT, 'BlueTooth', 'bt_rc.c')
t = load(p)
t = t.rstrip(NL) + NL + NL
t += '/* ---- V3 追加: LANRC 油门控制用的按键接口 ---- */' + NL
t += 'uint8_t bt_rc_key_a(void)' + NL
t += '{' + NL
t += '    if (!bt_rc_is_online())' + NL
t += '    {' + NL
t += '        return 0u;' + NL
t += '    }' + NL
t += '    return (bt_rc.key2 & BT_KEY2_A) ? 1u : 0u;' + NL
t += '}' + NL
t += NL
t += 'int8_t bt_rc_dir(void)' + NL
t += '{' + NL
t += '    if (!bt_rc_is_online())' + NL
t += '    {' + NL
t += '        return 0;' + NL
t += '    }' + NL
t += '    if (bt_rc.key1 == BT_DPAD_UP)' + NL
t += '    {' + NL
t += '        return 1;' + NL
t += '    }' + NL
t += '    if (bt_rc.key1 == BT_DPAD_DOWN)' + NL
t += '    {' + NL
t += '        return -1;' + NL
t += '    }' + NL
t += '    return 0;' + NL
t += '}' + NL
save(p, t)

# ---------- 3. hal_conf ----------
p = os.path.join(ROOT, 'Core', 'Inc', 'stm32f4xx_hal_conf.h')
t = load(p)
t = rep(t, '/* #define HAL_TIM_MODULE_ENABLED */',
        '#define HAL_TIM_MODULE_ENABLED', 'hal-tim')
save(p, t)

# ---------- 4. main.c ----------
p = os.path.join(ROOT, 'Core', 'Src', 'main.c')
t = load(p)

t = rep(t, '#include "k210_follow.h"' + NL,
        '#include "k210_follow.h"' + NL + '#include "tim.h"' + NL + '#include "dshot.h"' + NL,
        'includes')

t = rep(t, '#define WHEEL_SLEW_RPM_PER_TICK  150',
        '#define WHEEL_SLEW_RPM_PER_TICK  150' + NL +
        NL +
        '/*' + NL +
        ' * ==================== 7 路无刷 (LANRC DShot300, 同一块 C 板) ====================' + NL +
        ' * 与 LANRC 工程同一套操作: A 键(key2 bit0)按住 = 油门使能,' + NL +
        ' * 方向键上/下(key1)调速; 松开 A 立即停车, 速度档保留。' + NL +
        ' * key2 的 B 键(bit1=BT_KEY2_START)仍是 RC/FOLLOW 模式切换, 与 A 键不冲突。' + NL +
        ' */' + NL +
        '#define ESC_RUN_THROTTLE   1.0f   /* 满档油门上限 0.0~1.0 */' + NL +
        '#define ESC_SPEED_STEP     0.025f /* 每 ESC_SPEED_TICK_MS 调 2.5%, 0->100% 约 2s */' + NL +
        '#define ESC_SPEED_TICK_MS  50u' + NL +
        '#define ESC_SPEED_INIT     0.0f',
        'esc-pd')

# V2_dbg 加 3 个 ESC 字段
t = rep(t, '\tuint32_t k210_state;        /* \'L\'/\'S\'/\'X\' ASCII */' + NL + '} v2_dbg_t;',
        '\tuint32_t k210_state;        /* \'L\'/\'S\'/\'X\' ASCII */' + NL +
        '\tint32_t  esc_speed_x100;    /* 无刷速度档 0~100 */' + NL +
        '\tint32_t  esc_out_x100;      /* 实际输出油门 0~100 */' + NL +
        '\tuint32_t esc_pkt;           /* 最近 DShot 16bit 帧 */' + NL +
        '} v2_dbg_t;',
        'dbg-fields')

# USER CODE 2: TIM + DShot 初始化
t = rep(t,
    '  k210_follow_init();           /* K210 视觉跟随: USART6(PG9/PG14) 115200 8N1 */',
    '  MX_TIM8_Init();               /* 7 路无刷电调: TIM8_CH1~3 (PC6/PI6/PI7) */' + NL +
    '  MX_TIM1_Init();               /*               TIM1_CH1~4 (PE9/PE11/PE13/PE14) */' + NL +
    '  DShot_Init();                 /* DShot300 环形 DMA, 上电即持续发零油门帧 */' + NL +
    '  {' + NL +
    '    /* 等电调解锁(BLHeli_S 约 1~3s), 期间必须持续发帧并喂狗 */' + NL +
    '    uint32_t arm_until = HAL_GetTick() + DSHOT_ARM_MS;' + NL +
    '    while (HAL_GetTick() < arm_until)' + NL +
    '    {' + NL +
    '      HAL_IWDG_Refresh(&hiwdg);' + NL +
    '      HAL_Delay(10);' + NL +
    '    }' + NL +
    '  }' + NL +
    '  debug_print("esc dshot300 armed\\r\\n");' + NL +
    '  k210_follow_init();           /* K210 视觉跟随: USART6(PG9/PG14) 115200 8N1 */',
    'init')

# 主循环: CAN 输出后加 ESC 逻辑
esc_block = (
'\t\t/* ---- 7 路无刷 (LANRC 同款操作): A 键使能 + 方向键调速 ---- */' + NL +
'\t\t{' + NL +
'\t\t\tstatic float esc_speed = ESC_SPEED_INIT;' + NL +
'\t\t\tstatic float esc_out = -1.0f;      /* 强制首拍写一次 */' + NL +
'\t\t\tstatic uint32_t esc_speed_tick = 0;' + NL +
'\t\t\tfloat out;' + NL +
'\t\t\tuint8_t a_hold = bt_rc_key_a();' + NL +
'\t\t\tint8_t key_updown = bt_rc_dir();' + NL +
NL +
'\t\t\tif (key_updown != 0)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tuint32_t elapsed = HAL_GetTick() - esc_speed_tick;' + NL +
'\t\t\t\tif (elapsed >= ESC_SPEED_TICK_MS)' + NL +
'\t\t\t\t{' + NL +
'\t\t\t\t\tuint32_t steps = elapsed / ESC_SPEED_TICK_MS;' + NL +
'\t\t\t\t\tesc_speed_tick += steps * ESC_SPEED_TICK_MS;' + NL +
'\t\t\t\t\tesc_speed += (float)key_updown * ESC_SPEED_STEP * (float)steps;' + NL +
'\t\t\t\t\tif (esc_speed < 0.0f) { esc_speed = 0.0f; }' + NL +
'\t\t\t\t\tif (esc_speed > 1.0f) { esc_speed = 1.0f; }' + NL +
'\t\t\t\t}' + NL +
'\t\t\t}' + NL +
'\t\t\telse' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_speed_tick = HAL_GetTick();' + NL +
'\t\t\t}' + NL +
NL +
'\t\t\tout = (a_hold != 0u) ? (esc_speed * ESC_RUN_THROTTLE) : 0.0f;' + NL +
'\t\t\tif (out != esc_out)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_out = out;' + NL +
'\t\t\t\tDShot_SetAllThrottle(out);' + NL +
'\t\t\t}' + NL +
NL +
'\t\t\tV2_dbg.esc_speed_x100 = (int32_t)(esc_speed * 100.0f + 0.5f);' + NL +
'\t\t\tV2_dbg.esc_out_x100 = (int32_t)(esc_out * 100.0f + 0.5f);' + NL +
'\t\t\tV2_dbg.esc_pkt = DShot_GetPacket();' + NL +
'\t\t}' + NL)
t = rep(t, '\t\tk210_follow_report(mode);   /* 200ms 节流回传, 走 USART6(K210 可见) */',
        esc_block + '\t\tk210_follow_report(mode);   /* 200ms 节流回传, 走 USART6(K210 可见) */',
        'esc-loop')
save(p, t)

# ---------- 5. uvprojx ----------
p = os.path.join(ROOT, 'MDK-ARM', 'ctrl_2005.uvprojx')
t = load(p)
# tim.c 跟 main.c 同组 (Application/User/Core)
t = rep(t,
    '              <FileName>main.c</FileName>' + NL +
    '              <FileType>1</FileType>' + NL +
    '              <FilePath>../Core/Src/main.c</FilePath>' + NL +
    '            </File>',
    '              <FileName>main.c</FileName>' + NL +
    '              <FileType>1</FileType>' + NL +
    '              <FilePath>../Core/Src/main.c</FilePath>' + NL +
    '            </File>' + NL +
    '            <File>' + NL +
    '              <FileName>tim.c</FileName>' + NL +
    '              <FileType>1</FileType>' + NL +
    '              <FilePath>../Core/Src/tim.c</FilePath>' + NL +
    '            </File>',
    'uv-tim')
# dshot.c 加到 RM2006 组 (k210_follow.h 之后)
t = rep(t,
    '              <FileName>k210_follow.h</FileName>' + NL +
    '              <FileType>5</FileType>' + NL +
    '              <FilePath>..\\user\\k210_follow.h</FilePath>' + NL +
    '            </File>',
    '              <FileName>k210_follow.h</FileName>' + NL +
    '              <FileType>5</FileType>' + NL +
    '              <FilePath>..\\user\\k210_follow.h</FilePath>' + NL +
    '            </File>' + NL +
    '            <File>' + NL +
    '              <FileName>dshot.c</FileName>' + NL +
    '              <FileType>1</FileType>' + NL +
    '              <FilePath>..\\user\\dshot.c</FilePath>' + NL +
    '            </File>' + NL +
    '            <File>' + NL +
    '              <FileName>dshot.h</FileName>' + NL +
    '              <FileType>5</FileType>' + NL +
    '              <FilePath>..\\user\\dshot.h</FilePath>' + NL +
    '            </File>',
    'uv-dshot')
save(p, t)

print('ALL V3 PATCHES OK')
