# DR16 / DBUS 模块 —— 已停用（2026-11-19）

## 现状

`DR16_DT7.c` / `DR16_DT7.h` **不再参与编译**，已从 Keil 工程的 `DR16_DT7` 分组里移除。

原因：本车遥控走**蓝牙（USART1，塔克模块）**，DBUS(DT7 接收机) 这条路从来没真正跑过：

- 旧 `main.c` 里**从来没有调用** `MX_USART3_UART_Init()`（`git log -S` 查过，自首个提交起就没有），
  所以 `huart3.RxState` 一直是 `HAL_UART_STATE_RESET`；
- `dbus_uart_init()` 只做 `__HAL_UART_ENABLE_IT(IDLE)` + `uart_receive_dma_no_it()`，
  而后者要求 `RxState == HAL_UART_STATE_READY`（只有 `HAL_UART_Init` 会设置），
  否则直接返回 `HAL_BUSY`；USART3 时钟也没开。**整条接收通路是死的。**
- `dbus_uart_init()` 也确实没有任何调用者。

所以在 2026-11-19 把这套死代码彻底摘出去了，避免 CubeMX 生成代码时
突然把 USART3 初始化补上、让一条从未验证过的通路"活过来"。

## 具体动了什么

- `ctrl_2005.ioc`：删掉 `USART3` IP、`PC10`/`PC11` 引脚、`Dma.*`（USART3_RX 在 DMA1_Stream1）、
  `NVIC.USART3_IRQn`、`NVIC.DMA1_Stream1_IRQn`；`Mcu.IP*`/`Mcu.Pin*` 已重新连续编号
  （`IPNb=10`、`PinsNb=25`）；`functionlistsort` 去掉 `MX_DMA_Init` 与 `MX_USART3_UART_Init`。
- 生成结果：`Core/Src/dma.c`、`Core/Inc/dma.h` 被 CubeMX 自动删除；
  `usart.c` 不再有 `huart3` / `MX_USART3_UART_Init`；`it.c` 不再有
  `USART3_IRQHandler` / `DMA1_Stream1_IRQHandler`；`main.c` 不再 `#include "dma.h"`
  也不再调 `MX_DMA_Init()`。
  > DShot 用的是 DMA2（`dshot.c` 自己 `__HAL_RCC_DMA2_CLK_ENABLE()`），不受影响。
- `Core/Src/stm32f4xx_it.c` 的 `USER CODE BEGIN Includes` 里删掉了 `#include "DR16_DT7.h"`。
- Keil 工程（`ctrl_2005.uvprojx` / `ctrl_2005.uvoptx`）删掉了 `DR16_DT7` 分组。
  验证过：之后连续两次 Generate Code 都不会把它加回来。

## 将来要恢复 DBUS

1. 在 CubeMX 里加回 `USART3`（异步，100000，9 位字长 + 偶校验）→ 引脚 PC10/PC11；
2. 加回 `DMA1_Stream1` / `USART3_RX`（循环模式、字节对齐、低优先级）；
3. 打开 `NVIC.USART3_IRQn` 与 `NVIC.DMA1_Stream1_IRQn`；
4. 在 Keil 工程里新建 `DR16_DT7` 分组并把 `DR16_DT7.c` 加进去；
5. `main.c` 的 `USER CODE BEGIN 2` 里加 `MX_USART3_UART_Init();` 和 `dbus_uart_init();`
   ——注意顺序，`dbus_uart_init()` 必须在 `HAL_UART_Init` 之后；
6. `it.c` 的 `USER CODE BEGIN Includes` 里加回 `#include "DR16_DT7.h"`，
   并把 `uart_receive_handler(&huart3);` 放回 `USER CODE BEGIN USART3_IRQn 0`
   （或直接改用 `HAL_UARTEx_ReceiveToIdle_DMA`，比这套老写法干净）。
