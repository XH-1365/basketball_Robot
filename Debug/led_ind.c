/**
  ******************************************************************************
  * @file    led_ind.c
  * @brief   板载三色 LED 指示, 用颜色区分运行状态 (V2)
  *          绿=RC手动  蓝=跟随锁定目标  红闪=跟随没目标/K210离线
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

void led_ind_task(uint8_t mode, uint8_t k210_online, uint8_t has_target)
{
    static uint32_t last_tick  = 0;
    static uint32_t slow_cnt   = 0;      /* 1Hz 慢闪计数 */
    static uint32_t fast_cnt   = 0;      /* 5Hz 快闪计数 */
    static uint32_t last_err   = 0;
    static uint32_t last_err_t = 0;
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

    if (mode == LED_MODE_FOLLOW)
    {
        /* ---- 跟随模式: 蓝=锁定目标, 红1Hz=在线没人, 红5Hz=K210离线 ---- */
        led_write(LED_G_PORT, LED_G_PIN, 0);
        led_write(LED_B_PORT, LED_B_PIN, (has_target != 0u) ? 1 : 0);

        if (has_target != 0u)
        {
            led_write(LED_R_PORT, LED_R_PIN, 0);
        }
        else if (k210_online != 0u)
        {
            led_write(LED_R_PORT, LED_R_PIN, (slow_cnt < 12u) ? 1 : 0);  /* 1Hz 慢闪 */
        }
        else
        {
            led_write(LED_R_PORT, LED_R_PIN, (fast_cnt < 3u) ? 1 : 0);   /* 5Hz 快闪 */
        }
    }
    else
    {
        /* ---- 手动模式: 绿=蓝牙链路, 蓝=收过有效帧, 红=坏帧活动 ---- */
        led_write(LED_R_PORT, LED_R_PIN, 0);

        if (bt_rc_is_online())
        {
            led_write(LED_G_PORT, LED_G_PIN, 1);            /* 在线: 常亮 */
        }
        else
        {
            led_write(LED_G_PORT, LED_G_PIN, (slow_cnt < 12u) ? 1 : 0);  /* 离线: 1Hz 慢闪 */
        }

        led_write(LED_B_PORT, LED_B_PIN, (bt->ok_cnt != 0u) ? 1 : 0);

        if (bt->err_cnt != last_err)
        {
            last_err = bt->err_cnt;
            last_err_t = now;
        }
        if (bt->err_cnt != 0u && (now - last_err_t) < 1000u)
        {
            led_write(LED_R_PORT, LED_R_PIN, (fast_cnt < 3u) ? 1 : 0);   /* 5Hz 快闪 */
        }
    }
}

#else   /* LED_IND_EN == 0 */

void led_ind_init(void) { }
void led_ind_task(uint8_t mode, uint8_t k210_online, uint8_t has_target)
{
    (void)mode; (void)k210_online; (void)has_target;
}

#endif
