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
 *   4) k210_follow_vx_cmd()：按 dist 做距离保持, 生成前后平移指令 vx
 *      （目标距离 = K210_FOLLOW_DIST_CM, 转向误差大时按比例降速）
 *   5) k210_follow_report()：每 200ms 发一行状态回 K210（格式不约定, 供链路确认）
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

/* ======================= 距离保持（FOLLOW 前后平移） ======================= */

/* ★ 锁定距离(cm)：人与底盘的期望间距。改这一个数就换锁定距离。
 *   1 格 = 1cm。常用值：100~150。小于 40 时人贴身，底盘会一直后退。
 *   运行中也能改：k210_follow_set_target_dist_cm(cm)，范围 20~500。 */
#define K210_FOLLOW_DIST_CM     450

/* 运行时目标距离的合法范围(cm), 超出会被钳住 */
#define K210_DIST_CM_MIN        20
#define K210_DIST_CM_MAX        600

/* 距离死区(cm): 实际距离在 目标±此值 内不动, 防止贴着临界点前后窜 */
#define K210_DIST_DEADBAND_CM   20

/* 距离比例系数(rpm/cm): vx = KV * 距离误差。
 * 误差 60cm -> 480rpm; 误差 150cm -> 打满 1200rpm。追得太猛就调小, 太肉就调大。 */
#define K210_FOLLOW_KV          8.0f

/* 前后平移限幅(rpm), 比遥控满幅(BT_VX_MAX_RPM=2000)低, 跟人走够用又不过冲 */
#define K210_VX_MAX             1200

/* 前后平移软起步(rpm/拍, 10ms/拍): 只限制"加速", 减速/停车不受限(安全优先)。
 * 15rpm/拍 -> 从 0 到 1200 约 0.8s, 起步不窜。 */
#define K210_VX_SLEW_UP         15

/* 方向: vx 正 = 前进(chassis 里正 vx 即向前)。
 * 上机若"远了反而后退", 把这里改成 (-1.0f)。 */
#define K210_VX_DIR             (+1.0f)

/* 转向-前进联动: |err_deg| 小于 K210_TURN_SLOW_START 不降速;
 * 到 K210_TURN_SLOW_FULL 时降到 K210_TURN_SLOW_MIN 倍(保底不全停)。
 * 目的: 人在侧边时别一边猛转一边冲。 */
#define K210_TURN_SLOW_START    3.0f
#define K210_TURN_SLOW_FULL     15.0f
#define K210_TURN_SLOW_MIN      0.15f

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
  * @brief  跟随模式下的前后平移指令(rpm), 距离保持环。每 10ms 调一次。
  *         内部完成: 只认 state='L' 且在线; dist 未知(-1)不动; 死区;
  *         P 控制; 转向联动降速; 限幅; 加速软起步(减速立即跟)。
  * @retval 正 = 前进(距离太远), 负 = 后退(太近), 0 = 不动
  * @note   与 k210_follow_wheel_cmd() 互不干扰, 两者一起喂给逆解。
  */
int32_t k210_follow_vx_cmd(void);

/**
  * @brief  清距离环内部状态(软起步斜坡 + 上次输出)。
  *         切换 RC<->FOLLOW 时调用, 避免带着上一模式的斜坡值起步。
  */
void k210_follow_reset(void);

/**
  * @brief  运行中改锁定距离(cm)。会在 20~500 之间自动钳位。
  *         例: k210_follow_set_target_dist_cm(150);  // 改成 1.5m
  */
void k210_follow_set_target_dist_cm(int16_t cm);

/**
  * @brief  读当前锁定距离(cm)
  */
int16_t k210_follow_get_target_dist_cm(void);

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
