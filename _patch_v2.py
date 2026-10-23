# -*- coding: utf-8 -*-
"""MY_底盘_V2 K210 跟随集成补丁:
1. main.c   : include / PD(mode+SWD监控块定义) / PV(V2_dbg) / init / 主循环(模式切换+跟随控制+监控刷新)
2. it.c     : include + USART6_IRQHandler(RXNE 寄存器级收帧)
3. uvprojx  : RM2006 组加 k210_follow.c/h
4. k210_follow.c 去掉 UTF-8 BOM(防 armcc 告警)
每处替换 assert 命中 1 次, 保留原换行风格, 不加 BOM。
"""
import io, os, sys

ROOT = os.path.dirname(os.path.abspath(__file__))

def load(fn):
    with open(os.path.join(ROOT, fn), 'rb') as f:
        raw = f.read()
    assert raw[:3] != b'\xef\xbb\xbf', fn + ' has BOM'
    return raw.decode('utf-8')

def save(fn, text):
    with open(os.path.join(ROOT, fn), 'wb') as f:
        f.write(text.encode('utf-8'))
    print('saved:', fn)

def replace_once(text, old, new, tag):
    n = text.count(old)
    assert n == 1, '%s: anchor hit %d times' % (tag, n)
    return text.replace(old, new, 1)

# ---------------- main.c (LF) ----------------
NL = '\n'
t = load(os.path.join('Core', 'Src', 'main.c'))

t = replace_once(t,
    '#include "pid.h"' + NL + '/* USER CODE END Includes */',
    '#include "pid.h"' + NL + '#include "k210_follow.h"' + NL + '/* USER CODE END Includes */',
    'main-include')

pd_block = (
'/*' + NL +
' * ==================== 运行模式 (V2: 蓝牙遥控 / K210 视觉跟随) ====================' + NL +
' * key2 按下边沿切换 RC <-> FOLLOW; 切换时清四轮 PID 积分防残留。' + NL +
' * FOLLOW 只做转向跟随: 平移清零, w = K210 水平误差 P 控制(参数见 k210_follow.h)。' + NL +
' */' + NL +
'#define MODE_RC      0u' + NL +
'#define MODE_FOLLOW  1u' + NL +
NL +
'/*' + NL +
' * ==================== SWD 在线监控 ====================' + NL +
' * 双串口都被占用(USART1=蓝牙, USART6=K210)后, 调试信息改走 SWD:' + NL +
' * 主循环每拍刷新 V2_dbg, PC 端用 _swd_mon_v2.py(pyocd) 不停机轮询读取。' + NL +
' * magic 用来确认读到的地址/固件是配套版本。' + NL +
' */' + NL +
'#define V2_DBG_MAGIC 0x56324442u  /* \'V2DB\' */' + NL +
NL +
'typedef struct' + NL +
'{' + NL +
'\tuint32_t magic;' + NL +
'\tuint32_t tick;              /* HAL_GetTick(), 判断固件是否在跑 */' + NL +
'\tuint32_t mode;              /* 0=RC 1=FOLLOW */' + NL +
'\tuint32_t bt_online;         /* 蓝牙链路 0/1 */' + NL +
'\tint32_t  vx;' + NL +
'\tint32_t  vy;' + NL +
'\tint32_t  w;' + NL +
'\tint32_t  wheel[4];          /* 逆解目标转速 RB/LB/LF/RF */' + NL +
'\tint32_t  rpm[4];            /* CAN 反馈转速 RB/LB/LF/RF */' + NL +
'\tint32_t  k210_w;            /* 跟随转向指令(rpm) */' + NL +
'\tint32_t  k210_err_x10;      /* K210 水平误差, 单位0.1deg */' + NL +
'\tuint32_t k210_frames;       /* 校验通过帧数 */' + NL +
'\tuint32_t k210_bad;          /* 校验失败帧数 */' + NL +
'\tuint32_t k210_drop;         /* seq 丢帧数 */' + NL +
'\tuint32_t k210_age_ms;       /* 距最近一帧时间, 0xFFFFFFFF=从未收到 */' + NL +
'\tuint32_t k210_online;       /* 500ms 看门狗内 0/1 */' + NL +
'\tuint32_t k210_state;        /* \'L\'/\'S\'/\'X\' ASCII */' + NL +
'} v2_dbg_t;' + NL +
NL)
t = replace_once(t, '/* USER CODE END PD */', pd_block + '/* USER CODE END PD */', 'main-pd')

t = replace_once(t, '/* USER CODE END PV */',
    '/* SWD 监控共享块: 主循环每拍写, pyocd 只读 */' + NL +
    'volatile v2_dbg_t V2_dbg = { V2_DBG_MAGIC };' + NL + NL +
    '/* USER CODE END PV */', 'main-pv')

t = replace_once(t,
    '  debug_print("chassis bt-rc up\\r\\n");',
    '  debug_print("chassis bt-rc up\\r\\n");' + NL +
    '  k210_follow_init();           /* K210 视觉跟随: USART6(PG9/PG14) 115200 8N1 */',
    'main-init')

t = replace_once(t,
    '\t\tconst bt_rc_t *bt;' + NL,
    '\t\tconst bt_rc_t *bt;' + NL +
    '\t\tstatic uint8_t mode = MODE_RC;    /* 0=蓝牙遥控 1=K210跟随 */' + NL +
    '\t\tstatic bool last_key2 = false;' + NL,
    'main-decl')

t = replace_once(t,
    '\t\tled_ind_task();             /* 板载LED指示蓝牙链路状态 */' + NL,
    '\t\tled_ind_task();             /* 板载LED指示蓝牙链路状态 */' + NL +
    '\t\tk210_follow_task();         /* K210 看门狗/超时处理 */' + NL +
    NL +
    '\t\t/* key2 按下边沿 -> 切换 RC/FOLLOW, 清四轮积分 */' + NL +
    '\t\tif (bt->key2 == BT_KEY2_START && !last_key2)' + NL +
    '\t\t{' + NL +
    '\t\t\tmode = (mode == MODE_RC) ? MODE_FOLLOW : MODE_RC;' + NL +
    '\t\t\tfor (i = 0; i < CHASSIS_MOTOR_NUM; i++)' + NL +
    '\t\t\t{' + NL +
    '\t\t\t\tMY_PID[i].integral = 0;' + NL +
    '\t\t\t}' + NL +
    '\t\t\tdebug_print("mode -> %s\\r\\n", (mode == MODE_RC) ? "RC" : "FOLLOW");' + NL +
    '\t\t}' + NL +
    '\t\tlast_key2 = (bt->key2 == BT_KEY2_START);' + NL,
    'main-key2')

t = replace_once(t,
    '\t\tif (bt_rc_is_online())' + NL,
    '\t\tif (mode == MODE_FOLLOW)' + NL +
    '\t\t{' + NL +
    '\t\t\t/* 跟随模式: 只转向, 平移清零; K210 离线/丢人时 k210_follow_wheel_cmd() 返回 0 */' + NL +
    '\t\t\tvx = 0;' + NL +
    '\t\t\tvy = 0;' + NL +
    '\t\t\tw  = k210_follow_wheel_cmd();' + NL +
    '\t\t}' + NL +
    '\t\telse if (bt_rc_is_online())' + NL,
    'main-mode')

dbg_block = (
'\t\tk210_follow_report(mode);   /* 200ms 节流回传, 走 USART6(K210 可见) */' + NL +
NL +
'\t\t/* 刷新 SWD 监控块 */' + NL +
'\t\t{' + NL +
'\t\t\tconst k210_follow_t *kf = k210_follow_get();' + NL +
'\t\t\tV2_dbg.tick = HAL_GetTick();' + NL +
'\t\t\tV2_dbg.mode = mode;' + NL +
'\t\t\tV2_dbg.bt_online = bt_rc_is_online() ? 1u : 0u;' + NL +
'\t\t\tV2_dbg.vx = vx;' + NL +
'\t\t\tV2_dbg.vy = vy;' + NL +
'\t\t\tV2_dbg.w = w;' + NL +
'\t\t\tfor (i = 0; i < CHASSIS_MOTOR_NUM; i++)' + NL +
'\t\t\t{' + NL +
'\t\t\t\tV2_dbg.wheel[i] = wheel[i];' + NL +
'\t\t\t\tV2_dbg.rpm[i] = C[i].speed_rpm;' + NL +
'\t\t\t}' + NL +
'\t\t\tV2_dbg.k210_w = k210_follow_wheel_cmd();' + NL +
'\t\t\tV2_dbg.k210_err_x10 = kf->err_deg_x10;' + NL +
'\t\t\tV2_dbg.k210_frames = kf->frame_cnt;' + NL +
'\t\t\tV2_dbg.k210_bad = kf->bad_cnt;' + NL +
'\t\t\tV2_dbg.k210_drop = kf->drop_cnt;' + NL +
'\t\t\tV2_dbg.k210_online = kf->online;' + NL +
'\t\t\tV2_dbg.k210_state = (uint32_t)(uint8_t)kf->state;' + NL +
'\t\t\tV2_dbg.k210_age_ms = (kf->last_tick == 0u) ? 0xFFFFFFFFu' + NL +
'\t\t\t                   : (HAL_GetTick() - kf->last_tick);' + NL +
'\t\t}' + NL)
t = replace_once(t,
    '\t\tCAN_cmd_chassis(speed[0], speed[1], speed[2], speed[3]);' + NL,
    '\t\tCAN_cmd_chassis(speed[0], speed[1], speed[2], speed[3]);' + NL + NL + dbg_block,
    'main-dbg')
save(os.path.join('Core', 'Src', 'main.c'), t)

# ---------------- stm32f4xx_it.c (CRLF) ----------------
NL = '\r\n'
t = load(os.path.join('Core', 'Src', 'stm32f4xx_it.c'))

t = replace_once(t,
    '#include "DR16_DT7.h"',
    '#include "DR16_DT7.h"' + NL + '#include "k210_follow.h"',
    'it-include')

irq = (
'/*' + NL +
' * K210 视觉跟随接收: USART6(PG9) RXNE 中断。' + NL +
' * bt_rc.c 已占用 HAL_UART_RxCpltCallback, 这里直接寄存器级收字节。' + NL +
' */' + NL +
'void USART6_IRQHandler(void)' + NL +
'{' + NL +
'\tuint32_t sr = USART6->SR;' + NL +
NL +
'\tif (sr & (USART_SR_ORE | USART_SR_FE | USART_SR_NE | USART_SR_PE))' + NL +
'\t{' + NL +
'\t\t(void)USART6->DR;       /* 先SR后DR, 清错误标志 */' + NL +
'\t}' + NL +
'\tif (sr & USART_SR_RXNE)' + NL +
'\t{' + NL +
'\t\tk210_follow_on_rx((uint8_t)(USART6->DR & 0xFFU));' + NL +
'\t}' + NL +
'}' + NL)
t = replace_once(t,
    '/* USER CODE BEGIN 1 */' + NL + NL + '/* USER CODE END 1 */',
    '/* USER CODE BEGIN 1 */' + NL + NL + irq + NL + '/* USER CODE END 1 */',
    'it-irq')
save(os.path.join('Core', 'Src', 'stm32f4xx_it.c'), t)

# ---------------- ctrl_2005.uvprojx (LF) ----------------
NL = '\n'
t = load(os.path.join('MDK-ARM', 'ctrl_2005.uvprojx'))

t = replace_once(t,
    '            <File>' + NL +
    '              <FileName>chassis_solve.h</FileName>' + NL +
    '              <FileType>5</FileType>' + NL +
    '              <FilePath>..\\user\\chassis_solve.h</FilePath>' + NL +
    '            </File>',
    '            <File>' + NL +
    '              <FileName>chassis_solve.h</FileName>' + NL +
    '              <FileType>5</FileType>' + NL +
    '              <FilePath>..\\user\\chassis_solve.h</FilePath>' + NL +
    '            </File>' + NL +
    '            <File>' + NL +
    '              <FileName>k210_follow.c</FileName>' + NL +
    '              <FileType>1</FileType>' + NL +
    '              <FilePath>..\\user\\k210_follow.c</FilePath>' + NL +
    '            </File>' + NL +
    '            <File>' + NL +
    '              <FileName>k210_follow.h</FileName>' + NL +
    '              <FileType>5</FileType>' + NL +
    '              <FilePath>..\\user\\k210_follow.h</FilePath>' + NL +
    '            </File>',
    'uvprojx-files')
save(os.path.join('MDK-ARM', 'ctrl_2005.uvprojx'), t)

# ---------------- k210_follow.c 去 BOM ----------------
p = os.path.join(ROOT, 'user', 'k210_follow.c')
raw = open(p, 'rb').read()
if raw[:3] == b'\xef\xbb\xbf':
    open(p, 'wb').write(raw[3:])
    print('k210_follow.c: BOM stripped')
else:
    print('k210_follow.c: no BOM')

print('ALL PATCHES OK')
