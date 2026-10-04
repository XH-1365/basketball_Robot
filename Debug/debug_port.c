/**
  ******************************************************************************
  * @file    debug_port.c
  * @brief   调试串口: USART6 (PG14=TX / PG9=RX), 115200 8N1
  *          C板3-pin UART口, 可接板载DAPLink虚拟串口或USB转TTL
  ******************************************************************************
  */
#include "debug_port.h"
#include "usart.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define DEBUG_TX_BUF_LEN  160

static char dbg_buf[DEBUG_TX_BUF_LEN];

void debug_port_init(void)
{
    /* GPIO/时钟/NVIC 在 MX_USART6_UART_Init() -> HAL_UART_MspInit() 中完成 */
}

void debug_print(const char *fmt, ...)
{
    va_list args;
    int len;

    va_start(args, fmt);
    len = vsnprintf(dbg_buf, DEBUG_TX_BUF_LEN, fmt, args);
    va_end(args);

    if (len <= 0)
    {
        return;
    }
    if (len >= DEBUG_TX_BUF_LEN)
    {
        len = DEBUG_TX_BUF_LEN - 1;
    }

    HAL_UART_Transmit(&huart6, (uint8_t *)dbg_buf, (uint16_t)len, 50);
}
