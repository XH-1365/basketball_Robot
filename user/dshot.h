/**
  ******************************************************************************
  * @file    dshot.h
  * @brief   DShot300 电调协议输出驱动（TIM1 四路 + TIM8 三路，DMA burst 一位一位发）
  ******************************************************************************
  * 为什么换 DShot
  *   OneShot125 是纯模拟脉宽：没有校验、没有明确的"停车码"，电调靠输入捕获量脉宽，
  *   分辨率有限 + 抗干扰差 -> 相邻档位被读成同一档，甚至出现前档比后档快。
  *   DShot 是纯数字帧：11bit 油门(0~2047) + 4bit CRC，坏帧直接丢弃，
  *   value=0 是明确的"电机停"，信号断了电调自己进失控保护。分辨率 2048 级。
  *
  * 通道映射（与 oneshot125 完全相同，引脚/复用由 CubeMX 配好，本模块不动 GPIO）
  *   TIM1_CH1 -> PE9     TIM1_CH2 -> PE11    TIM1_CH3 -> PE13    TIM1_CH4 -> PE14
  *   TIM8_CH1 -> PC6     TIM8_CH2 -> PI6     TIM8_CH3 -> PI7
  *
  * 位时序（DShot300 = 300kbit/s）
  *   APB2 定时器时钟 168MHz，PSC=0 -> 1 tick = 1/168 us
  *   1 bit = 168MHz / 300kbit = 560 tick = 3.3333us（正好整数，无累积误差）
  *   bit 1 = 高 75% = 420 tick      bit 0 = 高 37.5% = 210 tick
  *
  * 帧结构（16 bit）
  *   [11bit 油门][1bit 遥测请求=0][4bit CRC]
  *   CRC = 前 12 bit 按半字节异或后取低 4 位
  *
  * 实现方式（为什么必须用 DMA，开源都是这么干的）
  *   DShot 每一位的高电平宽度都不一样，硬件 PWM 一个 ARR 只能出等宽波形，
  *   所以必须"每 3.33us 换一次 CCR"。做法是让定时器每次 update 事件触发
  *   一次 DMA burst，一次把 CCR1~CCR4 全写掉：
  *     DMA2_Stream5 / Ch6 -> TIM1_UP，DCR burst 4 拍，写 CCR1~CCR4
  *     DMA2_Stream1 / Ch7 -> TIM8_UP，DCR burst 4 拍，写 CCR1~CCR4（CH4 未用）
  *   CCR 预装载(OCxPE) 保证"这次写的值在下一个 bit 周期才生效"，正好逐位发送。
  *   参考实现：Betaflight 的 USE_DSHOT_DMAR 分支（LL_TIM_ConfigDMABurst +
  *   LL_TIM_EnableDMAReq_UPDATE + 目标 &tim->DMAR + WORD/WORD）。
  *
  * 与 Betaflight 的两点差异（按本项目场景调整，别照抄）
  *   1) 帧率：BF 是每个 PID 循环重启一次 DMA（正常模式），靠飞控 1~8kHz 循环节奏。
  *      本工程主循环 10ms、且每 200ms 有一行串口打印会阻塞约 10ms，
  *      照抄会掉到 100Hz，BLHeli_S 判信号超时。这里改成环形 DMA 连续重发：
  *      一帧 16 数据位 + 34 个空槽(长低电平)，硬件自动出 6kHz 稳态帧流，CPU 卡住也不停。
  *   2) mokhwasomssi 的库在 DMA 传输完成中断里 __HAL_TIM_DISABLE_DMA（他注释
  *      "I don't know why :("）——那是给一次性 DMA 收尾的，环形模式下关掉请求
  *      会让输出直接停，绝对不能加。
  *
  * 用法
  *   DShot_Init();                    // 上电即持续发送 value=0 的帧(电机停)
  *   HAL_Delay(DSHOT_ARM_MS);         // 等电调解锁，听初始化音
  *   DShot_SetAllThrottle(0.5f);      // 50% 油门
  *   DShot_Stop();                    // 停
  *
  * 注意
  *   1) 电调侧 BLHeli_S 的 Input Protocol 必须是 Auto / DShot300 才认这套帧；
  *      若锁死在 OneShot125，要先在 BLHeliSuite 里改成 Auto 或 DShot300。
  *   2) 本驱动不发 DShot 命令字(1~47)，也不支持双向遥测(eRPM)。
  *      BLHeli_S 想要遥测必须刷 Bluejay 固件。
  *   3) 与 OSH125_Init() 互斥：两个模块都想改 TIM1/TIM8 的 PSC/ARR，只能启用一个。
  ******************************************************************************
  */

#ifndef __DSHOT_H
#define __DSHOT_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* ============================ 位时序参数 ================================== */

/* 定时器输入时钟：APB2 定时器时钟 168MHz（SYSCLK 168M，APB2 分频 2 -> 定时器 x2） */
#define DSHOT_TIM_CLK_HZ        168000000UL

/* 波特率（kbit/s）：150 / 300 / 600，BLHeli_S 都认。300 最稳，600 已接近上限 */
#define DSHOT_KBIT              300UL

/* 1 bit 占多少 tick：168000000 / 1000 / 300 = 560 */
#define DSHOT_BIT_TICKS         (DSHOT_TIM_CLK_HZ / 1000UL / DSHOT_KBIT)

/* ARR：计数 0~559 正好 560 个 tick */
#define DSHOT_ARR               (DSHOT_BIT_TICKS - 1UL)

/* bit 1：高电平 75%；bit 0：高电平 37.5% */
#define DSHOT_BIT1_TICKS        ((DSHOT_BIT_TICKS * 3UL) / 4UL)     /* 420 */
#define DSHOT_BIT0_TICKS        ((DSHOT_BIT_TICKS * 3UL) / 8UL)     /* 210 */

/* 一帧有效数据 16 位 */
#define DSHOT_DATA_BITS         16U

/* ---- 帧重复周期 ----------------------------------------------------------
 * 一个"槽"= 1 bit 时间 = 3.333us。
 * 6kHz -> 周期 166.67us -> 正好 50 个槽，其中前 16 个发数据，后 34 个 CCR=0
 * (整槽低电平) 作为帧间隔。
 * 34 槽 x 3.33us = 113us 低电平，远大于协议要求的"至少 1 bit"，
 * 同时 6kHz 的刷新率与飞控 4~8kHz 主循环同一量级，BLHeli_S 不会判超时。
 */
#define DSHOT_FRAME_HZ          6000UL

/* 每帧占多少个 bit 槽：168MHz / 6kHz = 28000 tick，再 / 560 = 50 槽 */
#define DSHOT_PERIOD_SLOTS      ((DSHOT_TIM_CLK_HZ / DSHOT_FRAME_HZ) / DSHOT_BIT_TICKS)
#define DSHOT_IDLE_SLOTS        (DSHOT_PERIOD_SLOTS - DSHOT_DATA_BITS)     /* 34 */

/* 编译期校验：槽数必须整除，否则帧率不准 */
#if (DSHOT_PERIOD_SLOTS * DSHOT_BIT_TICKS * DSHOT_FRAME_HZ) != DSHOT_TIM_CLK_HZ
#error "DSHOT_PERIOD_SLOTS 与 DSHOT_FRAME_HZ / 位时序不自洽"
#endif

/* 油门值域：0 = 停；1~47 = 命令字；48~2047 = 油门 */
#define DSHOT_VALUE_MAX         2047U
#define DSHOT_VALUE_SPIN_MIN    48U
#define DSHOT_VALUE_STOP        0U

/* 输出路数，必须与下方通道枚举、dshot.c 的映射一致 */
#define DSHOT_CH_NUM            7U

/* 上电保持零油门的时间(ms)。电调要看到连续合法帧才解锁，1~3s 视固件而定 */
#define DSHOT_ARM_MS            2000U

/* ============================ 通道枚举 ==================================== */
typedef enum
{
    DSHOT_TIM1_CH1 = 0,     /* PE9  */
    DSHOT_TIM1_CH2,         /* PE11 */
    DSHOT_TIM1_CH3,         /* PE13 */
    DSHOT_TIM1_CH4,         /* PE14 */
    DSHOT_TIM8_CH1,         /* PC6  */
    DSHOT_TIM8_CH2,         /* PI6  */
    DSHOT_TIM8_CH3          /* PI7  */
} dshot_ch_t;

/* ============================ 对外接口 ==================================== */

/**
  * @brief  初始化 7 路 DShot 输出：改 PSC/ARR 成 300kbit 位时序，配好 DMA burst，
  *         启动 PWM 与环形 DMA。上电后硬件自动不停重发 value=0 的帧。
  * @note   必须在 MX_TIM1_Init() / MX_TIM8_Init() 之后调用；与 OSH125_Init() 互斥。
  */
void DShot_Init(void);

/**
  * @brief  设定某一路的原始值 0~2047（超 2047 钳位；1~47 属命令字，一律按 0 处理）。
  */
void DShot_SetValue(uint8_t ch, uint16_t value);

/**
  * @brief  设定全部 7 路的原始值 0~2047。
  */
void DShot_SetAllValue(uint16_t value);

/**
  * @brief  按油门比例设定全部 7 路：0.0f -> 停(0)，其余线性映射到 48~2047。
  * @param  throttle 0.0~1.0，超范围钳位，NaN 当 0
  */
void DShot_SetAllThrottle(float throttle);

/**
  * @brief  全部停车（value=0）。注意仍会持续发帧，不是把信号停掉。
  */
void DShot_Stop(void);

/**
  * @brief  读回某一路当前设定值 0~2047；通道号非法返回 0。
  */
uint16_t DShot_GetValue(uint8_t ch);

/**
  * @brief  读回最近一帧的 16bit 内容（12bit 数据 + 4bit CRC），调试用。
  *         例：value=0 -> 0x0000；value=100 -> 0x0C84
  */
uint16_t DShot_GetPacket(void);

#ifdef __cplusplus
}
#endif

#endif /* __DSHOT_H */
