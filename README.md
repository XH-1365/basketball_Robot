# basketball_Robot

篮球发射机器人 —— 嵌入式控制固件（STM32F407IGHx / RoboMaster C 型开发板）。

## 当前内容

**蓝牙遥控麦轮底盘**（`work_HZD/MY_底盘` 的独立导出）

- 接收器：塔克（TarkBot）X-Protocol 蓝牙手柄 / 微信小程序
- 底盘：4× M3508 麦轮全向底盘，C620 电调，CAN1 速度环
- 遥控：蓝牙 UART（USART1，PA9/PB7），200ms 无帧自动归零
- 解算：全向轮逆解（`user/chassis_solve.c`），X 形轮轴布局
- PID：四轮独立速度环，二号轮（左后 0x202）1.5 倍硬度
- 松杆刹车：摇杆回中沿清积分 + 刹车态 KP/KD 增益放大
- 板载三色 LED 链路指示（PH10=B / PH11=G / PH12=R，低电平点亮），无串口也能判断蓝牙状态
- 保留 DR16/DT7 代码（`DR16_DT7/`），默认走蓝牙

## 目录结构

```
Core/          CubeMX 生成的 HAL 初始化与中断
BlueTooth/     bt_rc.c/h  X-Protocol 帧解析状态机
user/          chassis_solve.c/h  全向轮逆解
PID/           pid.c/h  位置式 PID
DR16_DT7/      DBUS 遥控（保留备用）
Debug/         debug_port、led_ind（灯语指示）
bsp/           CAN 底层
MDK-ARM/       Keil MDK 工程（ctrl_2005.uvprojx）
```

## 编译

Keil MDK-ARM（ARMCC v5）：

```
UV4.exe -j0 -b MDK-ARM/ctrl_2005.uvprojx -o build.log
```

命令行烧录：

```
UV4.exe -f MDK-ARM/ctrl_2005.uvprojx
```

或 pyocd：

```
pyocd flash MDK-ARM/ctrl_2005/ctrl_2005.hex --target stm32f407ighx
```

## LED 灯语

| 灯态 | 含义 |
|---|---|
| 三灯全灭 | 固件没跑 |
| 绿灯 1Hz 慢闪 | 主循环在跑，但蓝牙零帧 |
| 绿灯常亮 | 蓝牙在线（200ms 内有帧） |
| 蓝灯常亮 | 曾收到有效帧（锁存） |
| 红灯 5Hz 快闪 | 帧校验错误在增长 |

## 关键调参宏（`Core/Src/main.c` 顶部）

| 宏 | 默认 | 作用 |
|---|---|---|
| `PID_BASE_KP/KI/KD` | 1.6 / 0.01 / 1.2 | 一号/三号/四号轮行驶手感 |
| `PID_2_KP/KI/KD` | 2.4 / 0.01 / 1.8 | 二号轮（左后），1.5 倍硬度 |
| `CHASSIS_BRAKE_GAIN` | 2.0 | 松杆刹车时 KP/KD 放大倍数 |
| `CHASSIS_BRAKE_EXIT_RPM` | 60 | 四轮 |rpm| 均低于此值判为停稳 |

摇杆/轮向映射宏见 `user/chassis_solve.h`（`VX_DIR` / `VY_DIR` / `W_DIR` / `WHEEL_DIR_x`）与 `BlueTooth/bt_rc.h`（`BT_VX_DIR` 等）。

上机若某方向反了，改对应 `*_DIR` 宏（+1/-1）即可，不用动解算。

## 蓝牙接线

```
蓝牙模块 TX  ->  板 PA9  (USART1_TX)
蓝牙模块 RX  ->  板 PB7  (USART1_RX)
GND 共地
```

注意：板载 USB 调试器的虚拟串口（COMx）与 USART1 **无物理连接**，不要指望从 COMx 看到蓝牙数据。

## 协议

X-Protocol 帧格式：
```
AA 55 | 帧长 | 帧号 | 类型 | 数据... | 校验和
```
帧号：手柄 `0xA0` / APP `0x20` / 小程序 `0x90`

小程序为单摇杆，固件内置 `BT_SINGLE_STICK_FALLBACK` 兼容层把左摇杆镜像到右摇杆，避免平动失效。
