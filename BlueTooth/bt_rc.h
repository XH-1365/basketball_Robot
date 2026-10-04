/**
  ******************************************************************************
  * @file    bt_rc.h
  * @brief   塔克(XTARK)蓝牙串口模块 SBTCOM1 遥控数据接收
  *          X-Protocol 变帧长协议解析 (USART1, 115200 8N1 固定)
  *
  * 支持的遥控源(帧号 frame_id):
  *   0x20 手机APP    类型0x01摇杆模式 / 0x02手柄模式, 共12字节:
  *       AA 55 0C 20 TY 左X 左Y 右X 右Y 键1 键2 SUM
  *   0x90 微信小程序 类型0x01摇杆模式, 共9字节:
  *       AA 55 09 90 01 摇X 摇Y 键1 SUM
  *   0xA0 蓝牙手柄   类型0x01标准数据, 共15字节:
  *       AA 55 0F A0 01 左X 左Y 右X 右Y 键1 键2 键3 右扳机 左扳机 SUM
  *                   类型0x00连接提示, 共7字节:
  *       AA 55 07 A0 00 55/FF SUM   (0x55=已连接, 0xFF=断开)
  *
  * 所有摇杆量为有符号8位, 范围 -127~+127, 中位 0。
  ******************************************************************************
  */
#ifndef BT_RC_H
#define BT_RC_H

#include "main.h"
#include "usart.h"

/* ===================== 用户可调参数 ===================== */

#define BT_HUART              huart1       /* 蓝牙模块所在串口(C板4-pin: PA9=TX / PB7=RX) */
#define BT_FRAME_MAX          36           /* 单帧最大字节数(含校验), 协议最长15字节, 留余量 */
#define BT_ONLINE_TIMEOUT_MS  200          /* 超过该时间无有效帧判定离线 */

#define BT_JOY_DEADBAND       8            /* 摇杆死区(0~127), 消除中位漂移 */

/* 摇杆(-127~127) -> 底盘目标转速(rpm) 满量程, 自己调 */
#define BT_VX_MAX_RPM         2000         /* 左摇杆Y: 前后平移 */
#define BT_VY_MAX_RPM         2000         /* 左摇杆X: 左右平移 */
#define BT_W_MAX_RPM          1500         /* 右摇杆X: 旋转 */

/* 方向约定: 车子某方向反了就把对应宏改成 (-1) */
#define BT_VX_DIR             (+1)         /* 摇杆上推 = 车头前进 */
#define BT_VY_DIR             (+1)         /* 摇杆右推 = 车向右平移 */
#define BT_W_DIR              (+1)         /* 右摇杆右推 = 顺时针旋转 */

/* 调试打印开关(通过 USART6/DAPLink 虚拟串口输出, 115200) */
#define BT_DEBUG_EN           1
#define BT_DEBUG_PERIOD_MS    500

/*
 * 单摇杆源兼容(微信小程序 FRAME_ID=0x90 只上报一个摇杆, rx/ry 恒为0)。
 * 打开后: 若最近一帧来自小程序, 主循环读到的 rx/ry 会自动镜像自 lx/ly,
 *         让"右摇杆管平动"的映射在小程序下依然可用。
 * 关掉(0)则小程序模式下无法平动, 只能旋转。
 */
#define BT_SINGLE_STICK_FALLBACK  1
/* USER CODE END */

/* ===================== 按键位定义 ===================== */
/* APP(0x20)键1 / 小程序(0x90)键1: */
#define BT_KEY_R2             0x80
#define BT_KEY_R1             0x40
#define BT_KEY_L2             0x20
#define BT_KEY_L1             0x10
#define BT_KEY_Y              0x08
#define BT_KEY_X              0x04
#define BT_KEY_B              0x02
#define BT_KEY_A              0x01
/* APP(0x20)键2: bit7=K4 bit6=K3 bit5=K2 bit4=K1 bit1=START bit0=SELECT */
#define BT_KEY2_K1            0x10
#define BT_KEY2_K2            0x20
#define BT_KEY2_K3            0x40
#define BT_KEY2_K4            0x80
#define BT_KEY2_START         0x02
#define BT_KEY2_SELECT        0x01
/* 小程序(0x90)键1 高4位与APP相同, 低4位是K1~K4: bit3=K4 bit2=K3 bit1=K2 bit0=K1 */

/* 帧号 */
#define BT_FRAME_ID_APP       0x20         /* 手机APP */
#define BT_FRAME_ID_MINI      0x90         /* 微信小程序 */
#define BT_FRAME_ID_GAMEPAD   0xA0         /* 蓝牙手柄(X3S/G6S) */

/* ===================== 数据结构 ===================== */

typedef struct
{
    int16_t lx;         /* 左摇杆X  -127~127 */
    int16_t ly;         /* 左摇杆Y  -127~127 */
    int16_t rx;         /* 右摇杆X  -127~127 */
    int16_t ry;         /* 右摇杆Y  -127~127 */
    uint8_t key1;       /* 按键1 */
    uint8_t key2;       /* 按键2 */
    uint8_t key3;       /* 按键3(仅蓝牙手柄) */
    uint8_t trig_r;     /* 右扳机 0~255(仅蓝牙手柄) */
    uint8_t trig_l;     /* 左扳机 0~255(仅蓝牙手柄) */
    uint8_t link;       /* 手柄连接状态: 1=已连接 0=断开/未知 */
    uint8_t frame_id;   /* 最近一帧来源: BT_FRAME_ID_xxx */
    uint8_t frame_type; /* 最近一帧类型 */
    uint32_t last_tick; /* 最近有效帧时刻(HAL_GetTick), 0=从未收到 */
    uint32_t ok_cnt;    /* 校验通过帧计数 */
    uint32_t err_cnt;   /* 帧长非法/校验失败计数 */
} bt_rc_t;

/* 接口 */
void bt_rc_init(void);              /* 使能接收中断, 在外设初始化之后调用 */
const bt_rc_t *bt_rc_update(void);  /* 主循环调用: 处理超时, 返回最新遥控数据 */
uint8_t bt_rc_is_online(void);      /* 1=在线(超时时间内有有效帧) */

#endif /* BT_RC_H */
