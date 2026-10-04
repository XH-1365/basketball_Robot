/**
  ******************************************************************************
  * @file    led_ind.h
  * @brief   板载三色 LED 指示 (PH10/R? PH11/G PH12/R, C板板载)
  *
  *          用途: 不依赖串口, 用眼睛就能看出蓝牙链路状态
  *            LED 全灭        = 没跑起来
  *            绿灯 1Hz 慢闪   = 主循环在跑, 但蓝牙没收到任何帧
  *            绿灯 常亮       = 蓝牙在线, 正在收帧 (最近200ms内有有效帧)
  *            绿灯 常亮+红灯闪= 收到了帧但校验/帧长错误 (err_cnt 在涨)
  *            蓝灯 常亮       = 曾经收到过有效帧 (ok_cnt > 0)
  *
  *          C板 LED 为共阳/低电平点亮, 见 led_ind.c 里的 LED_ACTIVE_LOW
  ******************************************************************************
  */
#ifndef LED_IND_H
#define LED_IND_H

#include "main.h"

/* 是否启用 LED 指示 (不想用就设 0) */
#define LED_IND_EN   1

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
void led_ind_task(void);   /* 主循环里周期调用(建议 >= 20ms) */

#endif /* LED_IND_H */
