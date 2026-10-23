/**
  ******************************************************************************
  * @file    dshot.c
  * @brief   DShot300 电调协议输出驱动（TIM1 四路 + TIM8 三路，DMA burst 逐位发送）
  ******************************************************************************
  * 时序推导
  *   SYSCLK 168MHz，APB2 分频 2 -> PCLK2 84MHz -> 定时器时钟 x2 = 168MHz。
  *   PSC = 0    -> 1 tick = 1/168 us = 5.952ns
  *   ARR = 559  -> 560 tick = 3.3333us = 1 bit（300kbit/s，正好整除无误差）
  *   CCR = 420  -> 高电平 2.5us = 75%   -> bit 1
  *   CCR = 210  -> 高电平 1.25us = 37.5% -> bit 0
  *   CCR = 0    -> 整槽低电平，用作帧间隔
  *
  * 发送机制
  *   每个 update 事件(bit 边界)触发一次 DMA burst，把 CCR1~CCR4 一起写掉。
  *   OCPE 预装载让"这次写的值"在下一个 bit 周期生效，于是天然逐位发送。
  *   DMA 环形模式 -> 一帧发完自动从头再来，CPU 完全不用管。
  *
  * 一帧占 50 个槽（50 x 3.333us = 166.67us = 6kHz）：
  *   槽 0~15  16 个数据位（MSB 在前）
  *   槽 16~49 34 个空槽，线上保持低电平 -> 帧间隔 113us
  ******************************************************************************
  */

/* Includes ------------------------------------------------------------------*/
#include "dshot.h"
#include "tim.h"

/* ============================ 内部常量 ==================================== */

/* 每个槽写 4 个 CCR（TIM1 全用；TIM8 第 4 个写的是没启用的 CH4，无害） */
#define DSHOT_WORDS_PER_SLOT    4U

/* 一个定时器一帧要搬多少个 32bit 字 */
#define DSHOT_BUF_WORDS         (DSHOT_PERIOD_SLOTS * DSHOT_WORDS_PER_SLOT)

/* TIM8 实际只用 3 路 */
#define DSHOT_TIM8_CH_NUM       3U

/* ============================ 内部变量 ==================================== */

/* DMA 搬运源缓冲：必须常驻、不能是局部变量 */
static uint32_t s_buf_tim1[DSHOT_BUF_WORDS];
static uint32_t s_buf_tim8[DSHOT_BUF_WORDS];

static DMA_HandleTypeDef s_hdma_tim1_up;    /* DMA2_Stream5 / Ch6 -> TIM1_UP */
static DMA_HandleTypeDef s_hdma_tim8_up;    /* DMA2_Stream1 / Ch7 -> TIM8_UP */

static uint16_t s_value[DSHOT_CH_NUM];      /* 各路当前值 0~2047 */
static uint16_t s_packet;                   /* 最近一帧 16bit 内容，调试用 */
static uint8_t  s_ready;                    /* 1 = DMA 已经在跑 */

/* ============================ 内部函数 ==================================== */

/**
  * @brief  11bit 油门 -> 16bit DShot 帧（12bit 数据 + 4bit CRC）
  * @param  value 0~2047
  * @retval 16bit 待发送内容，bit15 先发
  */
static uint16_t dshot_make_packet(uint16_t value)
{
    uint16_t packet;
    uint16_t crc;

    /* bit0 是遥测请求位，本驱动恒置 0 */
    packet = (uint16_t)((value & DSHOT_VALUE_MAX) << 1U);

    /* CRC-4：12bit 数据按半字节异或后取低 4 位。
       与 Betaflight / mokhwasomssi 的写法等价（他们是循环 3 次 csum ^= 数据） */
    crc = (uint16_t)((packet ^ (packet >> 4U) ^ (packet >> 8U)) & 0x0FU);

    return (uint16_t)((packet << 4U) | crc);
}

/**
  * @brief  取某一槽该输出多少 CCR 值
  * @param  packet 16bit 帧内容
  * @param  slot   槽号 0~49
  */
static uint32_t dshot_slot_ticks(uint16_t packet, uint32_t slot)
{
    uint16_t bit;

    /* 数据位之后的空槽：整槽低电平，作为帧间隔 */
    if (slot >= DSHOT_DATA_BITS)
    {
        return 0U;
    }

    /* MSB 先发：槽 0 对应 bit15 */
    bit = (uint16_t)((packet >> (DSHOT_DATA_BITS - 1U - slot)) & 1U);

    return (bit != 0U) ? (uint32_t)DSHOT_BIT1_TICKS : (uint32_t)DSHOT_BIT0_TICKS;
}

/**
  * @brief  按当前 s_value[] 填充某个定时器的 DMA 缓冲
  * @param  dst    目标缓冲
  * @param  first  该定时器第一路的全局通道号（TIM1=0，TIM8=4）
  * @param  nch    该定时器实际使用的通道数
  */
static void dshot_fill_buffer(uint32_t *dst, uint8_t first, uint8_t nch)
{
    uint16_t pkt[DSHOT_WORDS_PER_SLOT];
    uint32_t slot;
    uint32_t ch;

    /* 预先算好每路的 16bit 帧，避免在槽循环里重复算 CRC */
    for (ch = 0U; ch < DSHOT_WORDS_PER_SLOT; ch++)
    {
        pkt[ch] = (ch < nch) ? dshot_make_packet(s_value[first + ch]) : 0U;
    }

    for (slot = 0U; slot < DSHOT_PERIOD_SLOTS; slot++)
    {
        for (ch = 0U; ch < DSHOT_WORDS_PER_SLOT; ch++)
        {
            *dst++ = (ch < nch) ? dshot_slot_ticks(pkt[ch], slot) : 0U;
        }
    }
}

/**
  * @brief  把定时器配成 DShot 位时序 + DMA burst
  * @param  h     定时器句柄
  * @param  burst TIM_DMABURSTLENGTH_4TRANSFERS / _3TRANSFERS
  * @note   PSC 是带缓冲的，必须在启动计数前写；这里先清 CEN 再改。
  */
static void dshot_timer_config(TIM_HandleTypeDef *h, uint32_t burst)
{
    TIM_TypeDef *t = h->Instance;

    /* 1) 停计数，改 PSC/ARR（ARR 开了缓冲，靠下面的 UG 装进影子寄存器） */
    t->CR1 &= ~TIM_CR1_CEN;
    t->CR1 |= TIM_CR1_ARPE;
    t->PSC  = 0U;
    t->ARR  = (uint32_t)DSHOT_ARR;

    /* 2) 输出比较预装载：DMA 写的 CCR 在下一个 bit 周期才生效 -> 逐位发送的关键 */
    t->CCMR1 |= (TIM_CCMR1_OC1PE | TIM_CCMR1_OC2PE);
    t->CCMR2 |= (TIM_CCMR2_OC3PE | TIM_CCMR2_OC4PE);

    /* 3) 先全部输出低电平，避免启动瞬间冒一个高脉冲（电调会误当油门） */
    t->CCR1 = 0U;
    t->CCR2 = 0U;
    t->CCR3 = 0U;
    t->CCR4 = 0U;

    /* 4) 产生一次更新事件把 PSC/ARR/CCR 装进影子寄存器，再清掉它带来的 UIF。
          必须在打开 DMA 请求之前做，否则会多触发一次搬运。 */
    t->EGR = TIM_EGR_UG;
    t->SR  = ~TIM_SR_UIF;

    /* 5) DMA burst：每次 update 事件连续写 CCR1 起的 burst 个寄存器 */
    t->DCR = (TIM_DMABASE_CCR1 | burst);
}

/**
  * @brief  配置一个 DMA 流：内存 -> 定时器 DMAR，环形，字宽 32bit
  */
static void dshot_dma_config(DMA_HandleTypeDef *hdma, DMA_Stream_TypeDef *stream, uint32_t channel)
{
    hdma->Instance = stream;
    hdma->Init.Channel                 = channel;
    hdma->Init.Direction               = DMA_MEMORY_TO_PERIPH;
    hdma->Init.PeriphInc               = DMA_PINC_DISABLE;
    hdma->Init.MemInc                  = DMA_MINC_ENABLE;
    hdma->Init.PeriphDataAlignment     = DMA_PDATAALIGN_WORD;
    hdma->Init.MemDataAlignment        = DMA_MDATAALIGN_WORD;
    hdma->Init.Mode                    = DMA_CIRCULAR;       /* 发完自动从头再来 */
    hdma->Init.Priority                = DMA_PRIORITY_VERY_HIGH;
    hdma->Init.FIFOMode                = DMA_FIFOMODE_DISABLE;

    (void)HAL_DMA_Init(hdma);
}

/**
  * @brief  把 s_value[] 的变化真正下发到硬件
  * @note   直接操作寄存器而不用 HAL_DMA_Abort + HAL_DMA_Start，省掉 HAL 状态机。
  *         停止的这几微秒里输出会停在最后一个 CCR 上，最多丢一帧，CRC 会挡掉。
  */
static void dshot_apply(void)
{
    if (s_ready == 0U)
    {
        return;
    }

    s_packet = dshot_make_packet(s_value[DSHOT_TIM1_CH1]);

    __HAL_DMA_DISABLE(&s_hdma_tim1_up);
    while ((s_hdma_tim1_up.Instance->CR & DMA_SxCR_EN) != 0U) { }
    dshot_fill_buffer(s_buf_tim1, 0U, 4U);
    __HAL_DMA_SET_COUNTER(&s_hdma_tim1_up, DSHOT_BUF_WORDS);
    __HAL_DMA_ENABLE(&s_hdma_tim1_up);

    __HAL_DMA_DISABLE(&s_hdma_tim8_up);
    while ((s_hdma_tim8_up.Instance->CR & DMA_SxCR_EN) != 0U) { }
    dshot_fill_buffer(s_buf_tim8, 4U, DSHOT_TIM8_CH_NUM);
    __HAL_DMA_SET_COUNTER(&s_hdma_tim8_up, DSHOT_BUF_WORDS);
    __HAL_DMA_ENABLE(&s_hdma_tim8_up);
}

/**
  * @brief  只存值不做下发（供 SetAll* 批量调用后统一 apply 一次）
  */
static void dshot_store(uint8_t ch, uint16_t value)
{
    if (value > DSHOT_VALUE_MAX)
    {
        value = DSHOT_VALUE_MAX;
    }
    /* 1~47 是 DShot 命令字，本驱动不发命令，按停车处理 */
    if ((value != DSHOT_VALUE_STOP) && (value < DSHOT_VALUE_SPIN_MIN))
    {
        value = DSHOT_VALUE_STOP;
    }
    s_value[ch] = value;
}

/* ============================ 对外接口 ==================================== */

void DShot_Init(void)
{
    uint32_t i;

    for (i = 0U; i < DSHOT_CH_NUM; i++)
    {
        s_value[i] = DSHOT_VALUE_STOP;
    }
    s_packet = 0U;
    s_ready  = 0U;

    __HAL_RCC_DMA2_CLK_ENABLE();

    /* ---------------- TIM1：CH1~CH4（PE9/PE11/PE13/PE14） ---------------- */
    dshot_timer_config(&htim1, TIM_DMABURSTLENGTH_4TRANSFERS);
    dshot_dma_config(&s_hdma_tim1_up, DMA2_Stream5, DMA_CHANNEL_6);

    dshot_fill_buffer(s_buf_tim1, 0U, 4U);
    (void)HAL_DMA_Start(&s_hdma_tim1_up,
                        (uint32_t)s_buf_tim1,
                        (uint32_t)&TIM1->DMAR,
                        DSHOT_BUF_WORDS);

    /* 先开通道（HAL 会置 CCxE 和高级定时器必需的 MOE），再开 update DMA 请求。
       顺序反了的话，DMA 会在通道还没打开时就把一整帧搬完。 */
    (void)HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_2);
    (void)HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_3);
    (void)HAL_TIM_PWM_Start(&htim1, TIM_CHANNEL_4);
    __HAL_TIM_ENABLE_DMA(&htim1, TIM_DMA_UPDATE);

    /* ---------------- TIM8：CH1~CH3（PC6/PI6/PI7） ---------------- */
    dshot_timer_config(&htim8, TIM_DMABURSTLENGTH_4TRANSFERS);
    dshot_dma_config(&s_hdma_tim8_up, DMA2_Stream1, DMA_CHANNEL_7);

    dshot_fill_buffer(s_buf_tim8, 4U, DSHOT_TIM8_CH_NUM);
    (void)HAL_DMA_Start(&s_hdma_tim8_up,
                        (uint32_t)s_buf_tim8,
                        (uint32_t)&TIM8->DMAR,
                        DSHOT_BUF_WORDS);

    (void)HAL_TIM_PWM_Start(&htim8, TIM_CHANNEL_1);
    (void)HAL_TIM_PWM_Start(&htim8, TIM_CHANNEL_2);
    (void)HAL_TIM_PWM_Start(&htim8, TIM_CHANNEL_3);
    __HAL_TIM_ENABLE_DMA(&htim8, TIM_DMA_UPDATE);

    s_ready  = 1U;
    s_packet = dshot_make_packet(DSHOT_VALUE_STOP);
}

void DShot_SetValue(uint8_t ch, uint16_t value)
{
    if ((uint32_t)ch >= DSHOT_CH_NUM)
    {
        return;
    }

    dshot_store(ch, value);
    dshot_apply();
}

void DShot_SetAllValue(uint16_t value)
{
    uint32_t i;

    for (i = 0U; i < DSHOT_CH_NUM; i++)
    {
        dshot_store((uint8_t)i, value);
    }
    dshot_apply();
}

void DShot_SetAllThrottle(float throttle)
{
    uint16_t value;

    /* NaN 参与任何比较都为假，会一路漏下去，必须先挡掉 */
    if (throttle != throttle)
    {
        throttle = 0.0f;
    }

    if (throttle <= 0.0f)
    {
        value = DSHOT_VALUE_STOP;
    }
    else
    {
        if (throttle > 1.0f)
        {
            throttle = 1.0f;
        }
        value = (uint16_t)((float)DSHOT_VALUE_SPIN_MIN
                           + throttle * (float)(DSHOT_VALUE_MAX - DSHOT_VALUE_SPIN_MIN)
                           + 0.5f);
    }

    DShot_SetAllValue(value);
}

void DShot_Stop(void)
{
    DShot_SetAllValue(DSHOT_VALUE_STOP);
}

uint16_t DShot_GetValue(uint8_t ch)
{
    if ((uint32_t)ch >= DSHOT_CH_NUM)
    {
        return 0U;
    }
    return s_value[ch];
}

uint16_t DShot_GetPacket(void)
{
    return s_packet;
}

/************************ (C) COPYRIGHT *****END OF FILE***********************/
