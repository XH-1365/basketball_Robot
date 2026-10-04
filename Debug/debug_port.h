/**
  ******************************************************************************
  * @file    debug_port.h
  * @brief   调试串口: USART6 (C板3-pin UART口: PG14=TX / PG9=RX),
  *          接板载DAPLink虚拟串口或USB转TTL, 115200 8N1
  ******************************************************************************
  */
#ifndef DEBUG_PORT_H
#define DEBUG_PORT_H

#include "main.h"
#include <stdint.h>

void debug_port_init(void);                    /* USART6 初始化 */
void debug_print(const char *fmt, ...);        /* 阻塞打印(自动加\r\n) */

#endif /* DEBUG_PORT_H */
