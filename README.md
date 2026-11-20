# basketball_Robot · 步兵底盘固件

RoboMaster 步兵机器人嵌入式底盘控制固件，运行于大疆 C 型开发板（`STM32F407IGH6`，168 MHz），Keil MDK（ARMCC V5.06）编译。

驱动 4 路 M3508 全向底盘、1 路俯仰步进、3 路无刷，支持蓝牙手柄遥控与 K210 视觉跟随两种模式。

## 最快上手

1. 装 Keil MDK5 + ARMCC V5，打开 `MDK-ARM/ctrl_2005.uvprojx`
2. 编译（或直接用现成的 `MDK-ARM/ctrl_2005/ctrl_2005.hex` 烧录）
3. 接线按 [`docs/接线与维护教程.md`](docs/接线与维护教程.md) 第 3 节
4. 要改参数，只改 [`user/robot_config.h`](user/robot_config.h)

现成固件体积：`Code=20824  RO-data=592  RW-data=440  ZI-data=2776`

## 硬件组成

| 对象 | 数量 | 接口 | 说明 |
|---|---|---|---|
| M3508 + C620 | 4 | CAN1，1 Mbps | 全向轮底盘，编号 RB/LB/LF/RF = 1/2/3/4（0x201~0x204） |
| 42 步进 + TB6600 | 1 | TIM1_CH1 脉冲 + GPIO 方向 | 俯仰轴，8 细分，带机械限位 |
| 无刷 + BLHeli_S 电调 | 3 | TIM8_CH1~3，DShot300 | 环形 DMA 连续发送 |
| 蓝牙手柄 X3S/G6S | 1 | USART1，115200 | 塔克 X-Protocol 帧 |
| K210 视觉模块 | 1 | USART6，115200 | 上报水平误差与目标状态 |
| 三色 LED | 1 | PH10/PH11/PH12 | 共阳，低电平点亮 |

引脚全表见 `docs/接线与维护教程.md` 第 3 节。

## 运行模式

`key2` 的 B 键按下边沿在两种模式间切换，切换时清四轮 PID 积分防残留。

| 模式 | 数据源 | 输出 |
|---|---|---|
| `RC` | 蓝牙手柄摇杆 | `vx` / `vy` / `w` 三轴全向平移与旋转 |
| `FOLLOW` | K210 水平误差 | **只做朝向跟踪**，`w` 由误差 P 控制，`vx = vy = 0` |

`FOLLOW` 的距离保持环代码完整保留，但默认关闭。要恢复追人功能，把 `user/k210_follow.h` 的 `K210_FOLLOW_VX_ENABLE` 改成 `1`，六个距离参数一个没动，K210 侧固件也不用改。

## 目录结构

```
Core/          CubeMX 生成的 HAL 初始化与中断
user/          robot_config.h    ★ 全部可调参数集中在这里
               chassis_solve    全向轮逆解（几何推导在 .c 顶部注释）
               stepper          俯仰步进：梯形加减速 + 限位保护
               dshot            DShot300 帧编码 + 环形 DMA
               k210_follow      视觉跟随：转向环 + 距离环
               CAN_receive      M3508 反馈解析
BlueTooth/     bt_rc             X-Protocol 帧解析状态机
PID/           pid               位置式 PID
Debug/         debug_port、led_ind
bsp/           CAN 底层
MDK-ARM/       Keil 工程（ctrl_2005.uvprojx）
docs/          接线与维护教程
Drivers/       STM32F4 HAL + CMSIS
```

## 编译与烧录

```bash
# 编译
UV4.exe -j0 -b MDK-ARM/ctrl_2005.uvprojx -o build.log

# 烧录（ST-Link 必须在线，否则会挂住）
UV4.exe -f MDK-ARM/ctrl_2005.uvprojx

# 或用 pyocd
pyocd flash MDK-ARM/ctrl_2005/ctrl_2005.hex --target stm32f407ighx
```

成功标志：`0 Error(s), 0 Warning(s)`。

## 调参

所有日常要动的数在 `user/robot_config.h`，按功能分六组，每项都标了单位和调法：

| 组 | 内容 |
|---|---|
| 1 底盘速度环 PID | 四轮 KP/KI/KD、电流限幅、积分限幅 |
| 2 松杆刹车 | 刹车增益倍数、退出转速 |
| 3 轮速斜坡 | 每 10ms 目标最大变化量（防打滑） |
| 4 无刷油门 | 上限、步长、节拍、初始档位、斜坡 |
| 5 运行模式 | `MODE_RC` / `MODE_FOLLOW` |
| 6 SWD 监控 | 共享内存块的 magic |

其余模块参数在各自头文件：`stepper.h`（步进）、`k210_follow.h`（跟随）、`dshot.h`（DShot）、`bt_rc.h`（遥控）、`chassis_solve.h`（轮向与解算）。

**电机正反转不在代码里改**，用 BLHeliSuite 写电调参数：`Motor Direction` → `Reversed` → `Write Setup`，一次写入断电保持。

完整参数表见 `docs/接线与维护教程.md` 第 6 节。

## LED 灯语

| 模式 | 现象 | 含义 |
|---|---|---|
| RC | 绿灯常亮 | 蓝牙在线（200 ms 内有帧） |
| RC | 绿灯 1 Hz 慢闪 | 主循环在跑，但蓝牙零帧 |
| RC | 蓝灯常亮 | 曾收到有效帧（锁存） |
| RC | 红灯 5 Hz 快闪 | 帧校验错误在增长 |
| FOLLOW | 蓝灯常亮 | 已锁定目标 |
| FOLLOW | 红灯 1 Hz 慢闪 | K210 在线，画面无人 |
| FOLLOW | 红灯 5 Hz 快闪 | K210 离线 |
| — | 三灯全灭 | 固件没跑 |

## 调试

两个串口都被占用（USART1 = 蓝牙，USART6 = K210），调试信息改走 SWD：主循环每拍刷新一块共享结构体，PC 端用 pyocd 不停机轮询读取。

⚠️ `USART6` 是一线两用，K210 会收到底盘全部调试文字，所以 K210 侧的解析必须按 `K210,` / `RM,` 前缀过滤。

## 已知注意点

- **步进细分与代码必须对应**：TB6600 拨码改细分后，`user/stepper.h` 的 `STEP_STEPS_PER_REV` 要同步改（8 细分 = 1600，16 = 3200，32 = 6400），否则转速和位置全错。
- **步进精度优先于速度**：`STEP_RPM_MAX` 当前 100 RPM，10 ms 一拍过冲约 6°，松手后减速还要多走一段。精度不够时优先把这个值降下来。
- **`MDK-ARM/ctrl_2005.uvoptx` 必须保留在版本库中**：CubeMX 重新生成代码时要读它，缺失或 0 字节都会让生成失败，且日志看不出原因。
- **`git status` 里 `Drivers/` 下大量修改通常是行尾差异**，用 `git diff --name-only` 确认真实改动。

详细故障排查见 `docs/接线与维护教程.md` 第 7 节。
