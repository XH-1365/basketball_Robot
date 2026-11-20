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
#include "iwdg.h"
#include "tim.h"
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
#include "stepper.h"   /* 俯仰步进: TIM1_CH1(PE9)+DIR(PE11)+限位(PE13) */
#include "debug_port.h"
#include "led_ind.h"
#include "pid.h"
#include "k210_follow.h"
#include "tim.h"
#include "dshot.h"
#include "robot_config.h"      /* ★ 全部可调参数集中在这个文件 ★ */
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
/*
 * ★ 可调参数已全部移到 user/robot_config.h ★
 * 本文件不再定义任何调参宏；要改 PID、刹车、油门、斜坡，去那个文件。
 * 下面只保留 SWD 在线监控用的共享数据结构。
 */

typedef struct
{
	uint32_t magic;
	uint32_t tick;              /* HAL_GetTick(), 判断固件是否在跑 */
	uint32_t mode;              /* 0=RC 1=FOLLOW */
	uint32_t bt_online;         /* 蓝牙链路 0/1 */
	int32_t  vx;
	int32_t  vy;
	int32_t  w;
	int32_t  wheel[4];          /* 逆解目标转速 RB/LB/LF/RF */
	int32_t  rpm[4];            /* CAN 反馈转速 RB/LB/LF/RF */
	int32_t  k210_w;            /* 跟随转向指令(rpm) */
	int32_t  k210_err_x10;      /* K210 水平误差, 单位0.1deg */
	uint32_t k210_frames;       /* 校验通过帧数 */
	uint32_t k210_bad;          /* 校验失败帧数 */
	uint32_t k210_drop;         /* seq 丢帧数 */
	uint32_t k210_age_ms;       /* 距最近一帧时间, 0xFFFFFFFF=从未收到 */
	uint32_t k210_online;       /* 500ms 看门狗内 0/1 */
	uint32_t k210_state;        /* 'L'/'S'/'X' ASCII */
	int32_t  k210_dist_x100;    /* K210 估距(cm), -100=未知 */
	int32_t  k210_vx;           /* 距离保持前后平移指令(rpm) */
	int32_t  esc_speed_x100;    /* 无刷速度档 0~100 */
	int32_t  esc_out_x100;      /* 实际输出油门 0~100 */
	uint32_t esc_pkt;           /* 最近 DShot 16bit 帧 */
	uint32_t esc_a_hold;        /* A 键判定结果 0/1 (排查自转) */
	uint32_t esc_key2;          /* 按键2 原始字节 (排查自转) */
	int32_t  stepper_pos;       /* 步进相对零位步数(升+/降-/碰限位清零) */
	uint32_t stepper_lim;       /* 步进限位压住 0/1 */
} v2_dbg_t;

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

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
/* SWD 监控共享块: 主循环每拍写, pyocd 只读 */
volatile v2_dbg_t V2_dbg = { V2_DBG_MAGIC };

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

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

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_CAN1_Init();
  MX_CAN2_Init();
  MX_USART1_UART_Init();
  MX_USART6_UART_Init();
  MX_IWDG_Init();
  MX_TIM1_Init();
  MX_TIM8_Init();
  /* USER CODE BEGIN 2 */
  can_filter_init();
  bt_rc_init();                 /* 塔克蓝牙模块: USART1(PA9/PB7) 115200 8N1 */
  debug_port_init();            /* 调试串口: USART6(PG14/PG9) 接DAPLink虚拟串口 */
  led_ind_init();               /* 板载三色LED: 无串口也能看蓝牙状态 */
  debug_print("chassis bt-rc up\r\n");
  /* MX_TIM1_Init / MX_TIM8_Init 由 CubeMX 生成代码在上面的初始化块里调用,
   * 这里绝对不能再调一次(会重复初始化 PWM 通道)。见 ctrl_2005.ioc 的 functionlistsort。 */
  stepper_init();               /* 步进: DIR(PE11) 输出 + 限位(PE13) 输入 + PWM 通道启动 */
  DShot_Init();                 /* DShot300 环形 DMA, 上电即持续发零油门帧 */
  {
    /* 等电调解锁(BLHeli_S 约 1~3s), 期间必须持续发帧并喂狗 */
    uint32_t arm_until = HAL_GetTick() + DSHOT_ARM_MS;
    while (HAL_GetTick() < arm_until)
    {
      HAL_IWDG_Refresh(&hiwdg);
      HAL_Delay(10);
    }
  }
  debug_print("esc dshot300 armed\r\n");
  k210_follow_init();           /* K210 视觉跟随: USART6(PG9/PG14) 115200 8N1 */
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
		uint8_t i;
		int32_t vx;
		int32_t vy;
		int32_t w;
		int32_t wheel[CHASSIS_MOTOR_NUM];
		const bt_rc_t *bt;
		static uint8_t mode = MODE_RC;    /* 0=蓝牙遥控 1=K210跟随 */
		static bool last_key2 = false;
		const k210_follow_t *kf;

		HAL_Delay(10);
		HAL_IWDG_Refresh(&hiwdg);   /* 喂狗不依赖遥控数据, 防止断连复位 */

		bt = bt_rc_update();        /* 内部处理超时离线(摇杆自动归零) */

		/* 俯仰步进: 方向键 上=升 下=降 松开=停; 内部做斜坡/限位/换向保护 */
		stepper_set_dir(bt_rc_dir());
		stepper_task_10ms();
		kf = k210_follow_get();
		led_ind_task(mode, kf->online, (kf->online && kf->state == 'L') ? 1u : 0u);  /* LED: 模式+目标状态 */
		k210_follow_task();         /* K210 看门狗/超时处理 */

		/* key2 按下边沿 -> 切换 RC/FOLLOW, 清四轮积分 */
		if (bt->key2 == BT_KEY2_START && !last_key2)
		{
			mode = (mode == MODE_RC) ? MODE_FOLLOW : MODE_RC;
			for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
			{
				MY_PID[i].integral = 0;
			}
			k210_follow_reset();   /* 清距离环软起步斜坡, 别带上一模式的状态 */
			debug_print("mode -> %s\r\n", (mode == MODE_RC) ? "RC" : "FOLLOW");
		}
		last_key2 = (bt->key2 == BT_KEY2_START);

		/*
		 * 摇杆映射 —— 与全向底盘工程(DR16版)保持一致:
		 *   右摇杆Y -> vx  前后平移  (对应 DR16 ch3)
		 *   右摇杆X -> vy  左右平移  (对应 DR16 ch2)
		 *   左摇杆X -> w   旋转      (对应 DR16 ch0)
		 * 遥控器"上推"原始值为负, 所以 vx 取负抵消。
		 * 满量程/方向宏见 bt_rc.h 的 BT_VX_MAX_RPM / BT_VX_DIR 等。
		 */
		if (mode == MODE_FOLLOW)
		{
			/* 跟随模式: 只做朝向跟踪(err_deg), 不前进也不后退, 横移不用。
			 * vx 这行保留调用是为了把"要不要追人"集中在一个开关里
			 * (K210_FOLLOW_VX_ENABLE=0 时它恒返回 0, 连斜坡状态都不跑)。
			 * K210 离线/丢人时两路指令都返回 0, 原地停住不瞎走。 */
			vx = k210_follow_vx_cmd();
			vy = 0;
			w  = k210_follow_wheel_cmd();
		}
		else if (bt_rc_is_online())
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

		/* 轮速目标斜坡限幅: 削掉指令阶跃, 防瞬间大电流破抓地打滑 */
		{
			static int32_t wheel_ramp[CHASSIS_MOTOR_NUM] = {0};
			for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
			{
				int32_t diff = wheel[i] - wheel_ramp[i];
				if (diff > WHEEL_SLEW_RPM_PER_TICK)
				{
					diff = WHEEL_SLEW_RPM_PER_TICK;
				}
				if (diff < -WHEEL_SLEW_RPM_PER_TICK)
				{
					diff = -WHEEL_SLEW_RPM_PER_TICK;
				}
				wheel_ramp[i] += diff;
				wheel[i] = wheel_ramp[i];
			}
		}

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

		/* ---- 3 路无刷 (TIM8 CH1~CH3): A 键使能 + LB/RB 调速 ---- */
		{
			static float esc_speed = ESC_SPEED_INIT;  /* 油门档位 0~1, LB/RB 调 */
			static float esc_out = -1.0f;      /* 实际输出(斜坡后的值) */
			static float esc_write = -1.0f;    /* 上次下发给电调的值 */
			static uint32_t esc_speed_tick = 0;
			float out;
			uint8_t a_hold = bt_rc_key_a();
			int8_t esc_key = 0;

			/* RB 加速 / LB 减速, 每 ESC_SPEED_TICK_MS 变 ESC_SPEED_STEP 档
			 * 注意: 按键在 key2 的位掩码里(LB=bit6, RB=bit7); key1 是方向枚举不是位掩码
			 * 方向键已改控俯仰步进, 无刷速度改用肩键; A 键仍是使能(松开出力归 0) */
			if ((bt->key2 & BT_KEY2_RB) != 0u)
			{
				esc_key = 1;
			}
			else if ((bt->key2 & BT_KEY2_LB) != 0u)
			{
				esc_key = -1;
			}

			if (esc_key != 0)
			{
				uint32_t elapsed = HAL_GetTick() - esc_speed_tick;
				if (elapsed >= ESC_SPEED_TICK_MS)
				{
					uint32_t steps = elapsed / ESC_SPEED_TICK_MS;
					esc_speed_tick += steps * ESC_SPEED_TICK_MS;
					esc_speed += (float)esc_key * ESC_SPEED_STEP * (float)steps;
					if (esc_speed < 0.0f) { esc_speed = 0.0f; }
					if (esc_speed > 1.0f) { esc_speed = 1.0f; }
				}
			}
			else
			{
				esc_speed_tick = HAL_GetTick();
			}

			out = (a_hold != 0u) ? (esc_speed * ESC_RUN_THROTTLE) : 0.0f;

			/* 首拍从 0 起步, 避免 -1 占位值被当成有效输出 */
			if (esc_out < 0.0f)
			{
				esc_out = 0.0f;
			}

			/* 油门斜坡: 升降各约 1s(每拍 1%), 不瞬间跳变 */
			if (esc_out < out)
			{
				esc_out += ESC_RAMP_STEP;
				if (esc_out > out) { esc_out = out; }
			}
			else if (esc_out > out)
			{
				esc_out -= ESC_RAMP_STEP;
				if (esc_out < out) { esc_out = out; }
			}

			/* 值真的变了才下发(减少 DMA 重启次数) */
			if (esc_out != esc_write)
			{
				esc_write = esc_out;
				DShot_SetAllThrottle(esc_out);
			}

			V2_dbg.esc_speed_x100 = (int32_t)(esc_speed * 100.0f + 0.5f);   /* 当前油门档位 */
			V2_dbg.esc_out_x100 = (int32_t)(esc_out * 100.0f + 0.5f);
			V2_dbg.esc_pkt = DShot_GetPacket();
			V2_dbg.esc_a_hold = a_hold;
			V2_dbg.esc_key2 = bt->key2;
			V2_dbg.stepper_pos = stepper_get_pos();
			V2_dbg.stepper_lim = stepper_limit_active();
		}
		k210_follow_report(mode);   /* 200ms 节流回传, 走 USART6(K210 可见) */

		/* 刷新 SWD 监控块 */
		{
			V2_dbg.tick = HAL_GetTick();
			V2_dbg.mode = mode;
			V2_dbg.bt_online = bt_rc_is_online() ? 1u : 0u;
			V2_dbg.vx = vx;
			V2_dbg.vy = vy;
			V2_dbg.w = w;
			for (i = 0; i < CHASSIS_MOTOR_NUM; i++)
			{
				V2_dbg.wheel[i] = wheel[i];
				V2_dbg.rpm[i] = C[i].speed_rpm;
			}
			V2_dbg.k210_w = k210_follow_wheel_cmd();
			V2_dbg.k210_err_x10 = kf->err_deg_x10;
			V2_dbg.k210_frames = kf->frame_cnt;
			V2_dbg.k210_bad = kf->bad_cnt;
			V2_dbg.k210_drop = kf->drop_cnt;
			V2_dbg.k210_online = kf->online;
			V2_dbg.k210_state = (uint32_t)(uint8_t)kf->state;
			V2_dbg.k210_dist_x100 = kf->dist_x100;
			/* 注意: 不能在这里再调 k210_follow_vx_cmd(), 它带状态(斜坡),
			 * 每拍调两次会让软起步速度翻倍。用主循环算好的 vx 即可。 */
			V2_dbg.k210_vx = (mode == MODE_FOLLOW) ? vx : 0;
			V2_dbg.k210_age_ms = (kf->last_tick == 0u) ? 0xFFFFFFFFu
			                   : (HAL_GetTick() - kf->last_tick);
		}

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
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
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

  /** Initializes the CPU, AHB and APB buses clocks
  */
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

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
