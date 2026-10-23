# -*- coding: utf-8 -*-
"""修复: kf 必须在 led_ind_task 之前赋值, 否则首拍是野指针."""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(ROOT, 'Core', 'Src', 'main.c')
t = open(P, 'rb').read().decode('utf-8')

def rep(old, new, tag):
    global t
    n = t.count(old)
    assert n == 1, '%s: hit %d' % (tag, n)
    t = t.replace(old, new, 1)

# 1. bt_rc_update 后立刻取 kf
rep('\t\tbt = bt_rc_update();        /* 内部处理超时离线(摇杆自动归零) */\n',
    '\t\tbt = bt_rc_update();        /* 内部处理超时离线(摇杆自动归零) */\n'
    '\t\tkf = k210_follow_get();\n',
    'kf-early')

# 2. 删掉后面那份重复赋值
rep('\t\tk210_follow_task();         /* K210 看门狗/超时处理 */\n'
    '\t\tkf = k210_follow_get();\n',
    '\t\tk210_follow_task();         /* K210 看门狗/超时处理 */\n',
    'kf-dup')

open(P, 'wb').write(t.encode('utf-8'))
print('kf order fix OK')
