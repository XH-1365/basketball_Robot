/**
  ******************************************************************************
  * @file    stepper.c
  * @brief   俯仰步进电机驱动（硬件 PWM 发脉冲，非阻塞）
  ******************************************************************************
  * 工作方式
  *   TIM1_CH1 输出 50% 占空比 PWM 作为 STEP 脉冲，改 ARR 就是改步频（=转速）。
  *   每 10ms 由主循环调 stepper_task_10ms()，只做浮点斜坡 + 改两个寄存器，
  *   不占 CPU、不阻塞底盘控制。
  *
  * 保护
  *   1) 换向必须先停：转速降到 0 才翻 DIR 引脚，避免高速换向丢步/异响。
  *   2) 限位锁死：PE13 压住时立即停转，并锁住"正压着限位"的那个方向；
  *      离开限位并持续 STEP_LIMIT_RELEASE_MS 才解锁，反向永远允许。
  ******************************************************************************
  */
#include "stepper.h"
#include "tim.h"
#include <math.h>       /* fabsf */

extern TIM_HandleTypeDef htim1;

/* ============================ 内部状态 ==================================== */

static float    s_rpm;              /* 当前转速, 带符号: >0 升, <0 降 */
static int8_t   s_cmd_dir;          /* 遥控指令方向: +1 / -1 / 0 */
static int8_t   s_cur_dir;          /* DIR 引脚当前代表的方向 */
static uint8_t  s_lock_up;          /* 1 = 禁止继续朝"升"方向 */
static uint8_t  s_lock_dn;          /* 1 = 禁止继续朝"降"方向 */
static uint32_t s_limit_seen_tick;  /* 最后一次看到限位有效的时刻 */
static float    s_step_frac;        /* 步数累加器的小数部分 */
static uint32_t s_steps;            /* 估算累计步数（调试用） */

/* ============================ 内部函数 ==================================== */

/**
  * @brief  把 DIR 引脚设成指定方向
  */
static void stepper_write_dir(int8_t dir)
{
    GPIO_PinState level;

    if (dir > 0)
    {
        level = (STEP_DIR_UP_LEVEL != 0u) ? GPIO_PIN_SET : GPIO_PIN_RESET;
    }
    else
    {
        level = (STEP_DIR_UP_LEVEL != 0u) ? GPIO_PIN_RESET : GPIO_PIN_SET;
    }

    HAL_GPIO_WritePin(STEP_DIR_PORT, STEP_DIR_PIN, level);
    s_cur_dir = (dir > 0) ? 1 : -1;
}

/**
  * @brief  按转速刷新 STEP 脉冲频率
  * @param  rpm 当前转速（带符号），|rpm| 小于阈值时输出恒低，电机不动
  */
static void stepper_apply_pwm(float rpm)
{
    float f_hz;
    uint32_t arr;
    uint32_t ccr;

    f_hz = (rpm >= 0.0f) ? rpm : -rpm;
    f_hz = f_hz * STEP_STEPS_PER_REV / 60.0f;   /* rpm -> 步/秒 */

    if (f_hz < 0.5f)
    {
        /* 停止: CCR = 0, PWM1 模式下输出恒低, 不产生 STEP 边沿 */
        __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, 0u);
        return;
    }

    arr = (uint32_t)((float)STEP_TIM_TICK_HZ / f_hz);
    if (arr < 4u)
    {
        arr = 4u;                               /* 最高 250kHz, 防止脉宽过窄 */
    }
    arr -= 1u;

    /* 50% 占空比; 但脉宽不得低于 2us(A4988/DRV8825 要求 >= 1us) */
    ccr = arr / 2u;
    if (ccr < 2u)
    {
        ccr = 2u;
    }

    __HAL_TIM_SET_AUTORELOAD(&htim1, arr);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, ccr);
}

/* ============================ 对外接口 ==================================== */

void stepper_init(void)
{
    GPIO_InitTypeDef gpio = {0};

    s_rpm             = 0.0f;
    s_cmd_dir         = 0;
    s_lock_up         = 0u;
    s_lock_dn         = 0u;
    s_step_frac       = 0.0f;
    s_steps           = 0u;
    s_limit_seen_tick = HAL_GetTick() - STEP_LIMIT_RELEASE_MS;  /* 上电不算锁死 */

    /* ---- PE11(DIR) / PE13(限位) 归本模块管, 不依赖 MX_GPIO_Init ---- */
    __HAL_RCC_GPIOE_CLK_ENABLE();

    /* DIR: 推挽输出, 初值给"升" */
    HAL_GPIO_WritePin(STEP_DIR_PORT, STEP_DIR_PIN,
                      (STEP_DIR_UP_LEVEL != 0u) ? GPIO_PIN_SET : GPIO_PIN_RESET);
    gpio.Pin   = STEP_DIR_PIN;
    gpio.Mode  = GPIO_MODE_OUTPUT_PP;
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(STEP_DIR_PORT, &gpio);

    /* 限位/零位霍尔: 输入 + 内部上拉(开关接地时低有效) */
    gpio.Pin  = STEP_LIMIT_PIN;
    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_PULLUP;
    HAL_GPIO_Init(STEP_LIMIT_PORT, &gpio);

    /* 先定方向引脚, 再把 STEP 拉低, 最后开通道 */
    stepper_write_dir(1);
    __HAL_TIM_SET_AUTORELOAD(&htim1, 999u);
    __HAL_TIM_SET_COMPARE(&htim1, TIM_CHANNEL_1, 0u);
    (void)HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
}

void stepper_set_dir(int8_t dir)
{
    if (dir > 0)
    {
        s_cmd_dir = 1;
    }
    else if (dir < 0)
    {
        s_cmd_dir = -1;
    }
    else
    {
        s_cmd_dir = 0;
    }
}

void stepper_task_10ms(void)
{
    const float dt = 0.01f;
    const float d_rpm = STEP_ACCEL_RPM_S * dt;
    int8_t target;
    uint8_t lim;

    /* ---------------- 1. 限位检测与锁死 ---------------- */
    lim = (HAL_GPIO_ReadPin(STEP_LIMIT_PORT, STEP_LIMIT_PIN) ==
           ((STEP_LIMIT_ACTIVE_LEVEL != 0u) ? GPIO_PIN_SET : GPIO_PIN_RESET)) ? 1u : 0u;

    if (lim != 0u)
    {
        /* 压住就锁死"朝限位方向"的那一边, 与当前指令无关 —— 松手再按也不会漏保护;
           反方向永远放行, 保证能退出来 */
#if (STEP_LIMIT_AT_UP != 0u)
        s_lock_up = 1u;
#else
        s_lock_dn = 1u;
#endif

        s_limit_seen_tick = HAL_GetTick();
        s_rpm = 0.0f;                    /* 撞上立即停, 不走斜坡 */
        stepper_apply_pwm(0.0f);
        return;
    }

    /* 限位已释放, 持续够久才解锁(防止抖动反复触发) */
    if ((HAL_GetTick() - s_limit_seen_tick) > STEP_LIMIT_RELEASE_MS)
    {
        s_lock_up = 0u;
        s_lock_dn = 0u;
    }

    /* ---------------- 2. 目标方向(被锁的方向一律当 0) ---------------- */
    target = s_cmd_dir;
    if ((target > 0) && (s_lock_up != 0u))
    {
        target = 0;
    }
    if ((target < 0) && (s_lock_dn != 0u))
    {
        target = 0;
    }

    /* ---------------- 3. 斜坡 ---------------- */
    if (target == 0)
    {
        /* 松手或方向被禁: 平滑降到 0 */
        if (s_rpm > 0.0f)
        {
            s_rpm -= d_rpm;
            if (s_rpm < 0.0f) { s_rpm = 0.0f; }
        }
        else if (s_rpm < 0.0f)
        {
            s_rpm += d_rpm;
            if (s_rpm > 0.0f) { s_rpm = 0.0f; }
        }
    }
    else if (((s_rpm > 0.0f) && (target < 0)) || ((s_rpm < 0.0f) && (target > 0)))
    {
        /* 反向指令: 先减到 0, 下一拍再换向加速 */
        if (s_rpm > 0.0f)
        {
            s_rpm -= d_rpm;
            if (s_rpm < 0.0f) { s_rpm = 0.0f; }
        }
        else
        {
            s_rpm += d_rpm;
            if (s_rpm > 0.0f) { s_rpm = 0.0f; }
        }
    }
    else
    {
        /* 同向或从静止起步: 静止时才允许翻 DIR */
        if ((s_rpm == 0.0f) && (s_cur_dir != target))
        {
            stepper_write_dir(target);
        }

        s_rpm += (target > 0) ? d_rpm : -d_rpm;

        /* 从 0 起步时不要停在 STEP_RPM_MIN 以下的"爬行区", 直接给最低有效转速 */
        if (((target > 0) && (s_rpm < STEP_RPM_MIN)) || ((target < 0) && (s_rpm > -STEP_RPM_MIN)))
        {
            /* 只有在还没有达到过最低转速时才顶到 STEP_RPM_MIN;
               减速过程由上面的分支处理, 这里只负责起步 */
            if (fabsf(s_rpm) < STEP_RPM_MIN)
            {
                s_rpm = (target > 0) ? STEP_RPM_MIN : -STEP_RPM_MIN;
            }
        }

        if (s_rpm > STEP_RPM_MAX)  { s_rpm = STEP_RPM_MAX; }
        if (s_rpm < -STEP_RPM_MAX) { s_rpm = -STEP_RPM_MAX; }
    }

    /* ---------------- 4. 输出 ---------------- */
    stepper_apply_pwm(s_rpm);

    /* ---------------- 5. 步数估算(调试用) ---------------- */
    {
        float df = fabsf(s_rpm) * STEP_STEPS_PER_REV / 60.0f * dt;
        s_step_frac += df;
        if (s_step_frac >= 1.0f)
        {
            uint32_t whole = (uint32_t)s_step_frac;
            s_steps += whole;
            s_step_frac -= (float)whole;
        }
    }
}

int8_t stepper_get_dir(void)
{
    return s_cmd_dir;
}

float stepper_get_rpm(void)
{
    return s_rpm;
}

uint8_t stepper_limit_active(void)
{
    return (HAL_GPIO_ReadPin(STEP_LIMIT_PORT, STEP_LIMIT_PIN) ==
            ((STEP_LIMIT_ACTIVE_LEVEL != 0u) ? GPIO_PIN_SET : GPIO_PIN_RESET)) ? 1u : 0u;
}

uint8_t stepper_is_moving(void)
{
    return (fabsf(s_rpm) > 0.05f) ? 1u : 0u;
}

/************************ (C) COPYRIGHT *****END OF FILE***********************/
