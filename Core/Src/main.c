/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : Main program body
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "can.h"
#include "dma.h"
#include "iwdg.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include "CAN_receive.h"
#include "bsp_can.h"
#include "chassis_solve.h"
#include "bt_rc.h"
#include "debug_port.h"
#include "led_ind.h"
#include "pid.h"
/* USER CODE END Includes */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define CHASSIS_MOTOR_NUM 4
#define CHASSIS_3508_MAX_CURRENT 16384      /* M3508(C620) 官方限幅 ±16384 */
#define CHASSIS_PID_MAX_IOUT 3000

/*
 * ==================== 每电机独立速度环 PID ====================
 * 排列顺序与 chassis_solve.h 的电机索引一致:
 *   下标[0] = 一号 RB 右后 0x201
 *   下标[1] = 二号 LB 左后 0x202
 *   下标[2] = 三号 LF 左前 0x203
 *   下标[3] = 四号 RF 右前 0x204
 *
 * "硬" = 响应快、跟手、抗干扰强; 代价是容易抖/啸叫。
 *   - 想更硬: 加大 KP, KD 跟着加一点防超调
 *   - 抖了/啸叫了: 减 KP, 或加 KD
 *   - 到不了目标转速(有静差): 加 KI
 */
/* 基准参数 (一号 RB / 三号 LF / 四号 RF) —— 行驶手感 */
#define PID_BASE_KP   1.6f
#define PID_BASE_KI   0.01f
#define PID_BASE_KD   1.2f

/* 二号电机 LB (左后, 0x202) —— 保持 1.5 倍相对硬度 */
#define PID_2_KP      2.4f
#define PID_2_KI      0.01f
#define PID_2_KD      1.8f

/*
 * ==================== 松杆刹车 ====================
 * 现象: 松开摇杆后车有惯性滑行。
 * 原因: 1) KP 偏小制动力不足  2) 匀速时累积的积分残留继续推车  3) KD 只在误差突变的第一拍起作用。
 * 对策: 摇杆归零且车未停稳时 -> 清积分 + KP/KD 乘以 CHASSIS_BRAKE_GAIN 强力拉回零速;
 *       四轮转速都低于 CHASSIS_BRAKE_EXIT_RPM 视为停稳, 恢复正常增益。
 */
#define CHASSIS_BRAKE_GAIN      2.0f    /* 刹车时 KP/KD 放大倍数, 越大刹得越狠, 过大易顿挫/啸叫 */
#define CHASSIS_BRAKE_EXIT_RPM  60      /* 四轮 |rpm| 都低于此值 = 停稳 */
/* USER CODE END PD */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */
motor_measure_t C[CHASSIS_MOTOR_NUM];
int16_t speed[CHASSIS_MOTOR_NUM] = {0};

PID_Controller MY_PID[CHASSIS_MOTOR_NUM] =
{
	/*                    kp          ki         kd        sp le ig  max_out              max_iout              out */
	/* [0] 一号 RB 右后 */ {PID_BASE_KP, PID_BASE_KI, PID_BASE_KD, 0, 0, 0, CHASSIS_3508_MAX_CURRENT, CHASSIS_PID_MAX_IOUT, 0},
	/* [1] 二号 LB 左后 */ {PID_2_KP,    PID_2_KI,    PID_2_KD,    0, 0, 0, CHASSIS_3508_MAX_CURRENT, CHASSIS_PID_MAX_IOUT, 0},
	/* [2] 三号 LF 左前 */ {PID_BASE_KP, PID_BASE_KI, PID_BASE_KD, 0, 0, 0, CHASSIS_3508_MAX_CURRENT, CHASSIS_PID_MAX_IOUT, 0},
	/* [3] 四号 RF 右前 */ {PID_BASE_KP, PID_BASE_KI, PID_BASE_KD, 0, 0, 0, CHASSIS_3508_MAX_CURRENT, CHASSIS_PID_MAX_IOUT, 0},
};

/* kp/kd 的基准值(每拍会被乘刹车增益覆盖, 所以单独存一份) */
static const float PID_BASE_GAIN[CHASSIS_MOTOR_NUM][2] =
{
	{PID_BASE_KP, PID_BASE_KD},   /* [0] 一号 RB */
	{PID_2_KP,    PID_2_KD},      /* [1] 二号 LB */
	{PID_BASE_KP, PID_BASE_KD},   /* [2] 三号 LF */
	{PID_BASE_KP, PID_BASE_KD},   /* [3] 四号 RF */
};
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
/* 摇杆原始值(-127~127) -> 目标转速(rpm): 死区 + 满量程缩放 + 方向 */
static int16_t bt_joy_map(int16_t raw, int8_t dir, int16_t max_rpm)
{
	if (raw > -BT_JOY_DEADBAND && raw < BT_JOY_DEADBAND)
	{
		return 0;
	}
	return (int16_t)(dir * raw * max_rpm / 127);
}
/* USER CODE END 0 */

int main(void)
{
  HAL_Init();
  SystemClock_Config();

  MX_GPIO_Init();
  MX_DMA_Init();
  MX_CAN1_Init();
  MX_CAN2_Init();
  MX_USART1_UART_Init();
  MX_USART6_UART_Init();
  MX_IWDG_Init();

  /* USER CODE BEGIN 2 */
  can_filter_init();
  bt_rc_init();                 /* 塔克蓝牙模块: USART1(PA9/PB7) 115200 8N1 */
  debug_port_init();            /* 调试串口: USART6(PG14/PG9) 接DAPLink虚拟串口 */
  led_ind_init();               /* 板载三色LED: 无串口也能看蓝牙状态 */
  debug_print("chassis bt-rc up\r\n");
  /* USER CODE END 2 */

  while (1)
  {
    /* USER CODE BEGIN 3 */
		uint8_t i;
		int32_t vx;
		int32_t vy;
		int32_t w;
		int32_t wheel[CHASSIS_MOTOR_NUM];
		const bt_rc_t *bt;

		HAL_Delay(10);
		HAL_IWDG_Refresh(&hiwdg);   /* 喂狗不依赖遥控数据, 防止断连复位 */

		bt = bt_rc_update();        /* 内部处理超时离线(摇杆自动归零) */
		led_ind_task();             /* 板载LED指示蓝牙链路状态 */

		/*
		 * 摇杆映射 —— 与全向底盘工程(DR16版)保持一致:
		 *   右摇杆Y -> vx  前后平移  (对应 DR16 ch3)
		 *   右摇杆X -> vy  左右平移  (对应 DR16 ch2)
		 *   左摇杆X -> w   旋转      (对应 DR16 ch0)
		 * 遥控器"上推"原始值为负, 所以 vx 取负抵消。
		 * 满量程/方向宏见 bt_rc.h 的 BT_VX_MAX_RPM / BT_VX_DIR 等。
		 */
		if (bt_rc_is_online())
		{
			vx = -bt_joy_map(bt->ry, BT_VX_DIR, BT_VX_MAX_RPM);
			vy =  bt_joy_map(bt->rx, BT_VY_DIR, BT_VY_MAX_RPM);
			w  =  bt_joy_map(bt->lx, BT_W_DIR,  BT_W_MAX_RPM);
		}
		else
		{
			vx = 0;
			vy = 0;
			w  = 0;
		}

		/*
		 * 全向轮逆解(矩形四角, 轮轴呈 X 形)。
		 * 输出顺序: wheel[0]=RB(右后1) [1]=LB(左后2) [2]=LF(左前3) [3]=RF(右前4)
		 * 符号/方向修正全部在 chassis_solve.h 的宏里, 上机反了就翻宏。
		 */
		chassis_inverse_kinematics(vx, vy, w, wheel);

		/*
		 * 松杆刹车:
		 *   松杆沿(上一拍有输入, 这一拍全零) -> 清掉四轮积分, 防止残留积分继续推车;
		 *   摇杆归零且任一轮 |rpm| > EXIT_RPM -> 刹车态, KP/KD 乘 CHASSIS_BRAKE_GAIN 强力拉回零速;
		 *   四轮都停稳或摇杆有输入 -> 恢复正常增益。
		 * KP/KD 每拍从基准值重算, 不累积污染。
		 */
		{
			static bool last_stick_zero = false;
			bool stick_zero = (vx == 0 && vy == 0 && w == 0);
			bool brake_edge = stick_zero && !last_stick_zero;
			bool moving = false;
			float gain;

			if (stick_zero)
			{
				for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
				{
					int32_t rpm = C[i].speed_rpm;
					if (rpm < -CHASSIS_BRAKE_EXIT_RPM || rpm > CHASSIS_BRAKE_EXIT_RPM)
					{
						moving = true;
						break;
					}
				}
			}

			if (brake_edge)
			{
				for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
				{
					MY_PID[i].integral = 0;
				}
			}

			gain = (stick_zero && moving) ? CHASSIS_BRAKE_GAIN : 1.0f;
			for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
			{
				MY_PID[i].kp = PID_BASE_GAIN[i][0] * gain;
				MY_PID[i].kd = PID_BASE_GAIN[i][1] * gain;
			}

			last_stick_zero = stick_zero;
		}

		for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
		{
			MY_PID[i].setpoint = wheel[i];
			C[i] = *get_chassis_motor_measure_point(i);
			speed[i] = PID_Calculate(&MY_PID[i], C[i].speed_rpm);
		}

		CAN_cmd_chassis(speed[0], speed[1], speed[2], speed[3]);

#if BT_DEBUG_EN
		{
			static uint32_t last_dbg = 0;
			if (HAL_GetTick() - last_dbg >= BT_DEBUG_PERIOD_MS)
			{
				last_dbg = HAL_GetTick();
				debug_print("id:%02X ty:%02X link:%d lx:%4d ly:%4d rx:%4d ry:%4d k1:%02X k2:%02X ok:%lu err:%lu s:%4d %4d %4d %4d\r\n",
					bt->frame_id, bt->frame_type, bt->link,
					bt->lx, bt->ly, bt->rx, bt->ry, bt->key1, bt->key2,
					bt->ok_cnt, bt->err_cnt,
					C[0].speed_rpm, C[1].speed_rpm, C[2].speed_rpm, C[3].speed_rpm);
			}
		}
#endif
    /* USER CODE END 3 */
  }
}

void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_LSI|RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.LSIState = RCC_LSI_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 6;
  RCC_OscInitStruct.PLL.PLLN = 168;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 4;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
