# -*- coding: utf-8 -*-
"""V3: 油门斜坡(升降各1s) + 自转排查监控字段(a_hold/key2)."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
NL = '\n'
P = os.path.join(ROOT, 'Core', 'Src', 'main.c')

t = open(P, 'rb').read().decode('utf-8')

def rep(old, new, tag):
    global t
    n = t.count(old)
    assert n == 1, '%s: hit %d' % (tag, n)
    t = t.replace(old, new, 1)

# 1. 斜坡宏
rep('#define ESC_SPEED_INIT     0.0f',
    '#define ESC_SPEED_INIT     0.0f' + NL +
    '/* 油门斜坡: 每拍(10ms)变化 1%, 0->100% 约 1s, 升降同速(用户要求慢慢变) */' + NL +
    '#define ESC_RAMP_STEP      0.01f',
    'ramp-macro')

# 2. 监控字段: A键/按键2原始值
rep('\tuint32_t esc_pkt;           /* 最近 DShot 16bit 帧 */' + NL + '} v2_dbg_t;',
    '\tuint32_t esc_pkt;           /* 最近 DShot 16bit 帧 */' + NL +
    '\tuint32_t esc_a_hold;        /* A 键判定结果 0/1 (排查自转) */' + NL +
    '\tuint32_t esc_key2;          /* 按键2 原始字节 (排查自转) */' + NL +
    '} v2_dbg_t;',
    'dbg-fields')

# 3. 主循环: 斜坡替换掉原来的瞬间跳变
old_out = (
'\t\t\tout = (a_hold != 0u) ? (esc_speed * ESC_RUN_THROTTLE) : 0.0f;' + NL +
'\t\t\tif (out != esc_out)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_out = out;' + NL +
'\t\t\t\tDShot_SetAllThrottle(out);' + NL +
'\t\t\t}' + NL)
new_out = (
'\t\t\tout = (a_hold != 0u) ? (esc_speed * ESC_RUN_THROTTLE) : 0.0f;' + NL +
NL +
'\t\t\t/* 首拍从 0 起步, 避免 -1 占位值被当成有效输出 */' + NL +
'\t\t\tif (esc_out < 0.0f)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_out = 0.0f;' + NL +
'\t\t\t}' + NL +
NL +
'\t\t\t/* 油门斜坡: 升降各约 1s(每拍 1%), 不瞬间跳变 */' + NL +
'\t\t\tif (esc_out < out)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_out += ESC_RAMP_STEP;' + NL +
'\t\t\t\tif (esc_out > out) { esc_out = out; }' + NL +
'\t\t\t}' + NL +
'\t\t\telse if (esc_out > out)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_out -= ESC_RAMP_STEP;' + NL +
'\t\t\t\tif (esc_out < out) { esc_out = out; }' + NL +
'\t\t\t}' + NL +
NL +
'\t\t\t/* 值真的变了才下发(减少 DMA 重启次数) */' + NL +
'\t\t\tif (esc_out != esc_write)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tesc_write = esc_out;' + NL +
'\t\t\t\tDShot_SetAllThrottle(esc_out);' + NL +
'\t\t\t}' + NL)
rep(old_out, new_out, 'ramp-loop')

# 4. 新增 esc_write 静态变量
rep('\t\t\tstatic float esc_out = -1.0f;      /* 强制首拍写一次 */' + NL,
    '\t\t\tstatic float esc_out = -1.0f;      /* 实际输出(斜坡后的值) */' + NL +
    '\t\t\tstatic float esc_write = -1.0f;    /* 上次下发给电调的值 */' + NL,
    'esc-write')

# 5. 监控字段填充
rep('\t\t\tV2_dbg.esc_pkt = DShot_GetPacket();' + NL,
    '\t\t\tV2_dbg.esc_pkt = DShot_GetPacket();' + NL +
    '\t\t\tV2_dbg.esc_a_hold = a_hold;' + NL +
    '\t\t\tV2_dbg.esc_key2 = bt->key2;' + NL,
    'dbg-fill')

open(P, 'wb').write(t.encode('utf-8'))
print('V3 ramp+instrument OK')
