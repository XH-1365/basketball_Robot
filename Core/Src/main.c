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
#include "k210_follow.h"
#include "tim.h"
#include "dshot.h"
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
/*
 * 20261023 实测调参: 原参数 KP=1.6/KI=0.01 表现为提速肉 + 四轮静差消不掉跑偏。
 * KP 1.6->2.6: 满误差 P 输出从 20% 提到 32% 满电流, 提速明显;
 * KI 0.01->0.08: 100rpm 静差约 1.3s 补完(原来要 10s), 各轮静差自然消除, 不再靠硬拉增益;
 * KD 按原 KP:KD≈0.75 比例跟随。抖/啸叫先降 KP, 不到位加 KD。
 */
/* 基准参数 (一号 RB / 三号 LF / 四号 RF) —— 行驶手感 */
#define PID_BASE_KP   2.6f
#define PID_BASE_KI   0.08f
#define PID_BASE_KD   1.6f

/* 二号电机 LB (左后, 0x202) —— 保持 1.5 倍相对硬度 */
#define PID_2_KP      3.9f
#define PID_2_KI      0.08f
#define PID_2_KD      2.4f

/*
 * ==================== 松杆刹车 ====================
 * 现象: 松开摇杆后车有惯性滑行。
 * 原因: 1) KP 偏小制动力不足  2) 匀速时累积的积分残留继续推车  3) KD 只在误差突变的第一拍起作用。
 * 对策: 摇杆归零且车未停稳时 -> 清积分 + KP/KD 乘以 CHASSIS_BRAKE_GAIN 强力拉回零速;
 *       四轮转速都低于 CHASSIS_BRAKE_EXIT_RPM 视为停稳, 恢复正常增益。
 */
#define CHASSIS_BRAKE_GAIN      2.5f    /* 刹车时 KP/KD 放大倍数 (3.5->2.5: 已有斜坡限幅削掉阶跃, 不需要那么狠) */

/*
 * ==================== 轮速目标斜坡限幅 (防打滑) ====================
 * 20261023 SWD 实测: 指令阶跃(0->2250rpm一拍)+大力矩 -> 轮子破抓地打滑,
 * 稳态轮速 +-100~200rpm 摆动, 超调最高 10.6%。
 * 对策: 每拍(10ms)目标最多变化 WHEEL_SLEW_RPM_PER_TICK, 0->2250 约 150ms。
 * 调法: 还打滑减小; 起步肉/不跟手加大。0 = 关闭斜坡(恢复阶跃)。
 */
#define WHEEL_SLEW_RPM_PER_TICK  150

/*
 * ==================== 7 路无刷 (LANRC DShot300, 同一块 C 板) ====================
 * 与 LANRC 工程同一套操作: A 键(key2 bit0)按住 = 油门使能,
 * 方向键上/下(key1)调速; 松开 A 立即停车, 速度档保留。
 * key2 的 B 键(bit1=BT_KEY2_START)仍是 RC/FOLLOW 模式切换, 与 A 键不冲突。
 */
#define ESC_RUN_THROTTLE   1.0f   /* 满档油门上限 0.0~1.0 */
#define ESC_SPEED_STEP     0.025f /* 每 ESC_SPEED_TICK_MS 调 2.5%, 0->100% 约 2s */
#define ESC_SPEED_TICK_MS  50u
#define ESC_SPEED_INIT     0.0f
/* 油门斜坡: 每拍(10ms)变化 1%, 0->100% 约 1s, 升降同速(用户要求慢慢变) */
#define ESC_RAMP_STEP      0.01f
#define CHASSIS_BRAKE_EXIT_RPM  60      /* 四轮 |rpm| 都低于此值 = 停稳 */
/*
 * ==================== 运行模式 (V2: 蓝牙遥控 / K210 视觉跟随) ====================
 * key2 按下边沿切换 RC <-> FOLLOW; 切换时清四轮 PID 积分防残留。
 * FOLLOW = 转向跟随 + 距离保持:
 *   w  = K210 水平误差(err_deg) P 控制
 *   vx = K210 距离(dist) P 控制, 锁定距离见 k210_follow.h 的 K210_FOLLOW_DIST_CM
 *   vy = 0(横移不用)
 * 参数全在 k210_follow.h, 上机反了翻 K210_FOLLOW_DIR / K210_VX_DIR。
 */
#define MODE_RC      0u
#define MODE_FOLLOW  1u

/*
 * ==================== SWD 在线监控 ====================
 * 双串口都被占用(USART1=蓝牙, USART6=K210)后, 调试信息改走 SWD:
 * 主循环每拍刷新 V2_dbg, PC 端用 _swd_mon_v2.py(pyocd) 不停机轮询读取。
 * magic 用来确认读到的地址/固件是配套版本。
 */
#define V2_DBG_MAGIC 0x56324442u  /* 'V2DB' */

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
} v2_dbg_t;

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
/* SWD 监控共享块: 主循环每拍写, pyocd 只读 */
volatile v2_dbg_t V2_dbg = { V2_DBG_MAGIC };

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
  MX_TIM8_Init();               /* 7 路无刷电调: TIM8_CH1~3 (PC6/PI6/PI7) */
  MX_TIM1_Init();               /*               TIM1_CH1~4 (PE9/PE11/PE13/PE14) */
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

  while (1)
  {
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
			/* 跟随模式: 转向(err_deg) + 前后距离保持(dist), 横移不用。
			 * K210 离线/丢人时两个指令都返回 0, 原地停住不瞎走。 */
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

		/* ---- 7 路无刷 (LANRC 同款操作): A 键使能 + 方向键调速 ---- */
		{
			static float esc_speed = ESC_SPEED_INIT;
			static float esc_out = -1.0f;      /* 实际输出(斜坡后的值) */
			static float esc_write = -1.0f;    /* 上次下发给电调的值 */
			static uint32_t esc_speed_tick = 0;
			float out;
			uint8_t a_hold = bt_rc_key_a();
			int8_t key_updown = bt_rc_dir();

			if (key_updown != 0)
			{
				uint32_t elapsed = HAL_GetTick() - esc_speed_tick;
				if (elapsed >= ESC_SPEED_TICK_MS)
				{
					uint32_t steps = elapsed / ESC_SPEED_TICK_MS;
					esc_speed_tick += steps * ESC_SPEED_TICK_MS;
					esc_speed += (float)key_updown * ESC_SPEED_STEP * (float)steps;
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

			V2_dbg.esc_speed_x100 = (int32_t)(esc_speed * 100.0f + 0.5f);
			V2_dbg.esc_out_x100 = (int32_t)(esc_out * 100.0f + 0.5f);
			V2_dbg.esc_pkt = DShot_GetPacket();
			V2_dbg.esc_a_hold = a_hold;
			V2_dbg.esc_key2 = bt->key2;
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
