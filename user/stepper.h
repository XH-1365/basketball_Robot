/**
  ******************************************************************************
  * @file    stepper.h
  * @brief   俯仰步进电机驱动（硬件 PWM 发脉冲，非阻塞）
  ******************************************************************************
  * 硬件接线（C 板 PWM 排针）
  *   PE9   TIM1_CH1  -> STEP   脉冲输出，频率 = 步频
  *   PE11  GPIO 输出  -> DIR    方向电平
  *   PE13  GPIO 输入  -> 限位/零位霍尔（低电平触发）
  *
  * 用法（主循环 10ms 调一次即可，不阻塞）
  *   stepper_init();                 // 上电初始化
  *   stepper_set_dir(+1 / -1 / 0);   // 遥控方向键: 上=+1 下=-1 松开=0
  *   stepper_task_10ms();            // 每 10ms 调一次
  ******************************************************************************
  */
#ifndef __STEPPER_H
#define __STEPPER_H

#include "main.h"

/* ==================== 机械与驱动参数: 只改这一段 ==================== */

/* 每圈脉冲数 = 电机全步数 x 驱动器细分
 * 1.8° 两相步进 = 200 全步/圈, 细分 32 -> 200 x 32 = 6400 */
#define STEP_STEPS_PER_REV      6400.0f

/* 最高俯仰转速 (RPM)。60 RPM 时步频 6400Hz, STEP 高电平约 78us */
#define STEP_RPM_MAX            10.0f

/* 起转最低转速 (RPM)。低于此转速扭矩不足易丢步, 斜坡从这里开始 */
#define STEP_RPM_MIN            1.5f

/* 加速度 (RPM/秒)。越大越猛, 越小越平顺 */
#define STEP_ACCEL_RPM_S        200.0f

/* 方向电平: DIR 输出这个电平时朝"升"方向。装反了就改成 0 */
#define STEP_DIR_UP_LEVEL       1u

/* 限位开关有效电平: 霍尔/开关压住时为 0(低有效)。高有效改成 1 */
#define STEP_LIMIT_ACTIVE_LEVEL 0u

/* 限位开关装在行程哪一端:
 *   0 = 装在下端/零位  -> 压住时禁止继续"降"(反转), 允许升
 *   1 = 装在上端      -> 压住时禁止继续"升"(正转), 允许降 */
#define STEP_LIMIT_AT_UP        0u

/* 限位锁死解除时间(ms): 离开限位并持续这么久才允许再次朝该方向走 */
#define STEP_LIMIT_RELEASE_MS   200u

/* PWM 定时器基准: TIM1 时钟 168MHz / (PSC+1) = 1MHz, 即 1 tick = 1us */
#define STEP_TIM_TICK_HZ        1000000UL

/* ==================================================================== */

/* 引脚定义（跟 CubeMX 配置对应, 换脚只改这里） */
#define STEP_PORT               GPIOE
#define STEP_PIN                GPIO_PIN_9
#define STEP_DIR_PORT           GPIOE
#define STEP_DIR_PIN            GPIO_PIN_11
#define STEP_LIMIT_PORT         GPIOE
#define STEP_LIMIT_PIN          GPIO_PIN_13

/* 对外接口 */
void    stepper_init(void);           /* 上电初始化: 停转 + 读限位 + 启动 PWM 通道 */
void    stepper_set_dir(int8_t dir);  /* 指令方向: +1 升 / -1 降 / 0 松手停 */
void    stepper_task_10ms(void);      /* 主循环 10ms 调用: 斜坡 + 限位 + 刷新 PWM */

int8_t  stepper_get_dir(void);        /* 最近一次指令方向 */
float   stepper_get_rpm(void);        /* 当前实际转速 (带符号, >0 = 升) */
uint8_t stepper_limit_active(void);   /* 1 = 限位当前被压住 */
uint8_t stepper_is_moving(void);      /* 1 = 正在转 (|rpm| > 0.05) */
int32_t stepper_get_pos(void);        /* 相对零位步数: 升+ 降-, 碰限位清零 */
float   stepper_get_pos_deg(void);    /* 同上, 换算成角度(度) */

#endif /* __STEPPER_H */
