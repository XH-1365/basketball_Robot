/**
  ******************************************************************************
  * @file    k210_follow.h
  * @brief   K210 视觉跟随链路（底盘侧接收 + 转向指令生成）
  ******************************************************************************
  * 协议（《底盘跟随串口协议》v1.0, E:/K210/docs/底盘跟随串口协议.md）
  *   K210,seq,state,id,err_deg,dist_m*hh\n   约 8Hz, ASCII, XOR 校验
  *   state: L=锁定人  S=画面没人  X=视觉不可用
  *   err_deg: 人相对画面中心水平偏角, 正=人在右侧 -> 底盘应右转(顺时针)
  *
  * 接线（底盘 = 大疆 C 板）
  *   USART6, 115200 8N1, 3.3V TTL, 两板共地
  *   K210 IO8(TXD) -> C 板 PG9(RX)
  *   C 板 PG14(TX) -> K210 IO6(RXD)   [与调试输出共用, K210 会以 [CHAS] 回显]
  *
  * 本模块职责
  *   1) USART6 逐字节中断收帧 + XOR 校验 + 字段解析（独立寄存器级 ISR,
  *      不占用 HAL 的 RxCpltCallback——那个已经被蓝牙模块占了）
  *   2) 500ms 看门狗：超时判 K210 掉线
  *   3) k210_follow_wheel_cmd()：按 err_deg 做 P 控制生成旋转指令 w
  *   4) k210_follow_report()：每 200ms 发一行状态回 K210（格式不约定, 供链路确认）
  ******************************************************************************
  */

#ifndef K210_FOLLOW_H
#define K210_FOLLOW_H

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"

/* ============================ 可调参数 ==================================== */

/* P 控制增益: w(rpm) = KP * err_deg。
 * err 全量程约 ±21.4 度, KP=80 时 18.8 度即打满 1500rpm 旋转。
 * 协议文档建议 Kp≈2 是它自己的量纲, 这里直接用 rpm/度。转向过冲减小 KP。 */
#define K210_FOLLOW_KP          80.0f

/* 死区(度): 人在画面中心 ±0.8 度内不转, 防止原地抖动 */
#define K210_DEADBAND_DEG       0.8f

/* 旋转指令限幅(rpm), 与蓝牙摇杆旋转满幅 BT_W_MAX_RPM 一致 */
#define K210_W_MAX              1500

/* 方向: 协议规定 err_deg 正 = 人在画面右。
 * chassis W_DIR=+1 时 w 正 = 逆时针; 20261023 上机实测需取 +1 才朝人转。
 * (原按协议推的是 -1, 实机转向相反, 实测为准改 +1。)
 * 如果以后换了底盘/装反电机又反了, 改回 (-1.0f)。 */
#define K210_FOLLOW_DIR         (+1.0f)

/* 看门狗(ms): 超过此时长没收到任何合法帧 -> 判 K210 掉线, 输出归零 */
#define K210_FOLLOW_WATCHDOG_MS 500u

/* 状态回传周期(ms): 每次向 K210 发一行 RM,... 状态 */
#define K210_REPORT_MS          200u

/* ============================ 数据结构 ==================================== */

typedef struct
{
    uint8_t  online;        /* 1 = 看门狗时间内有合法帧 */
    char     state;         /* 'L'=锁定 'S'=没人 'X'=视觉不可用 '?'=从未收到/超时 */
    int16_t  err_deg_x10;   /* 水平偏角×10, 正=人在画面右 */
    int16_t  dist_x100;     /* 估距(m)×100; -100 = 未知(协议里的 -1) */
    uint16_t id;            /* 跟踪目标 id */
    uint16_t seq;           /* 最近帧序号 */
    uint32_t frame_cnt;     /* 校验通过帧计数 */
    uint32_t bad_cnt;       /* 校验失败帧计数 */
    uint32_t drop_cnt;      /* 按 seq 估计的丢帧数 */
    uint32_t last_tick;     /* 最近合法帧时刻(HAL_GetTick) */
} k210_follow_t;

/* ============================ 对外接口 ==================================== */

/**
  * @brief  初始化: 打开 USART6 RXNE 中断。在 MX_USART6_UART_Init() 之后调用。
  * @note   TX 方向与 debug_print 共用 PG14, 本模块不做 TX 初始化。
  */
void k210_follow_init(void);

/**
  * @brief  逐字节喂入(在 USART6_IRQHandler 里调用)
  */
void k210_follow_on_rx(uint8_t byte);

/**
  * @brief  主循环任务: 看门狗判离线。每 10ms 调一次。
  */
void k210_follow_task(void);

/**
  * @brief  跟随模式下的旋转指令(rpm)。
  *         内部完成: 只认 state='L' 且在线; 死区; P 控制; 限幅。
  *         非 'L' / 掉线 / 死区内一律返回 0。
  */
int32_t k210_follow_wheel_cmd(void);

/**
  * @brief  向 K210 回传一行状态: RM,<mode>,<state>,<err_deg>,<w>\n
  *         内部自带 200ms 节流, 主循环每拍调用即可。
  * @param  follow_mode 1 = 底盘当前处于跟随模式
  */
void k210_follow_report(uint8_t follow_mode);

/**
  * @brief  读最新解析结果(调试用)
  */
const k210_follow_t *k210_follow_get(void);

#ifdef __cplusplus
}
#endif

#endif /* K210_FOLLOW_H */
