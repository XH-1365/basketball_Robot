/**
  ******************************************************************************
  * @file    led_ind.h
  * @brief   板载三色 LED 指示 (PH10/B PH11/G PH12/R, C板板载)
  *
  *          用途: 不依赖串口, 用颜色直接看出运行状态 (V2)
  *            ---- 手动遥控(RC) ----
  *            绿灯 常亮       = RC 模式, 蓝牙在线
  *            绿灯 1Hz 慢闪   = RC 模式, 蓝牙离线
  *            蓝灯 常亮       = (RC下) 曾收到过蓝牙有效帧
  *            红灯 5Hz 快闪   = (RC下) 蓝牙坏帧活动 (err_cnt 在涨)
  *            ---- 自动跟随(FOLLOW) ----
  *            蓝灯 常亮       = 跟随中, 已锁定目标 (K210 state='L')
  *            红灯 1Hz 慢闪   = 跟随中, K210 在线但画面里没人 (S/X)
  *            红灯 5Hz 快闪   = 跟随中, K210 离线 (超时/没接)
  *
  *          C板 LED 为共阳/低电平点亮, 见 led_ind.c 里的 LED_ACTIVE_LOW
  ******************************************************************************
  */
#ifndef LED_IND_H
#define LED_IND_H

#include "main.h"

/* 是否启用 LED 指示 (不想用就设 0) */
#define LED_IND_EN   1

/* 模式编号: 与 main.c 的 MODE_RC / MODE_FOLLOW 数值一致 */
#define LED_MODE_RC      0u
#define LED_MODE_FOLLOW  1u

/* C 板板载三色 LED 引脚 */
#define LED_R_PORT   GPIOH
#define LED_R_PIN    GPIO_PIN_12
#define LED_G_PORT   GPIOH
#define LED_G_PIN    GPIO_PIN_11
#define LED_B_PORT   GPIOH
#define LED_B_PIN    GPIO_PIN_10

/* 1 = 低电平点亮(常见共阳接法), 0 = 高电平点亮 */
#define LED_ACTIVE_LOW  1

void led_ind_init(void);
/* 主循环里周期调用(建议 >= 20ms):
 *   mode        LED_MODE_RC / LED_MODE_FOLLOW
 *   k210_online K210 看门狗是否在线 0/1
 *   has_target  跟随是否锁定到人 0/1 (online && state=='L')
 */
void led_ind_task(uint8_t mode, uint8_t k210_online, uint8_t has_target);

#endif /* LED_IND_H */
