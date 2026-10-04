/**
  ******************************************************************************
  * @file    led_ind.c
  * @brief   板载三色 LED 指示, 用于无串口判断蓝牙链路状态
  ******************************************************************************
  */
#include "led_ind.h"

#if LED_IND_EN

#include "bt_rc.h"

static void led_write(GPIO_TypeDef *port, uint16_t pin, int on)
{
#if LED_ACTIVE_LOW
    HAL_GPIO_WritePin(port, pin, on ? GPIO_PIN_RESET : GPIO_PIN_SET);
#else
    HAL_GPIO_WritePin(port, pin, on ? GPIO_PIN_SET : GPIO_PIN_RESET);
#endif
}

void led_ind_init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOH_CLK_ENABLE();

    gpio.Pin   = LED_R_PIN | LED_G_PIN | LED_B_PIN;
    gpio.Mode  = GPIO_MODE_OUTPUT_PP;
    gpio.Pull  = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(GPIOH, &gpio);

    led_write(LED_R_PORT, LED_R_PIN, 0);
    led_write(LED_G_PORT, LED_G_PIN, 0);
    led_write(LED_B_PORT, LED_B_PIN, 0);
}

void led_ind_task(void)
{
    static uint32_t last_tick = 0;
    static uint32_t slow_cnt  = 0;      /* 1Hz 慢闪计数 */
    static uint32_t fast_cnt  = 0;      /* 5Hz 快闪计数 */
    static uint32_t last_ok   = 0;
    static uint32_t last_err  = 0;
    const bt_rc_t  *bt;
    uint32_t now = HAL_GetTick();

    /* 约 20ms 一次, 不依赖精确周期 */
    if (now - last_tick < 20u)
    {
        return;
    }
    last_tick = now;

    /* 1Hz: 每 500ms 翻转一次 */
    if (++slow_cnt >= 25u) { slow_cnt = 0; }
    /* 5Hz: 每 100ms 翻转一次 */
    if (++fast_cnt >= 5u)  { fast_cnt = 0; }

    bt = bt_rc_update();

    /* ---- 绿灯: 蓝牙链路状态 ---- */
    if (bt_rc_is_online())
    {
        led_write(LED_G_PORT, LED_G_PIN, 1);            /* 在线: 常亮 */
    }
    else
    {
        led_write(LED_G_PORT, LED_G_PIN, (slow_cnt < 12u) ? 1 : 0);  /* 离线: 1Hz 慢闪 */
    }

    /* ---- 蓝灯: 曾经收到过有效帧 (锁存) ---- */
    if (bt->ok_cnt != 0u)
    {
        led_write(LED_B_PORT, LED_B_PIN, 1);            /* 有有效帧: 常亮 */
    }
    else
    {
        led_write(LED_B_PORT, LED_B_PIN, 0);            /* 从没收到: 灭 */
    }

    /* ---- 红灯: 错误帧活动 (err_cnt 增长时快闪, 停就灭) ---- */
    if (bt->err_cnt != last_err)
    {
        last_err = bt->err_cnt;
        last_ok  = now;                                 /* 复用: 记录错误活动时刻 */
    }
    if (bt->err_cnt != 0u && (now - last_ok) < 1000u)
    {
        led_write(LED_R_PORT, LED_R_PIN, (fast_cnt < 3u) ? 1 : 0);   /* 5Hz 快闪 */
    }
    else
    {
        led_write(LED_R_PORT, LED_R_PIN, 0);
    }
}

#else   /* LED_IND_EN == 0 */

void led_ind_init(void) { }
void led_ind_task(void) { }

#endif
