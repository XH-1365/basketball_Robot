/**
  ******************************************************************************
  * @file    bt_rc.c
  * @brief   塔克(XTARK)蓝牙串口模块遥控数据解析 (X-Protocol)
  *
  * 实现说明:
  *  - USART1 逐字节中断接收(HAL_UART_Receive_IT 1字节), 比 DMA+IDLE 更适合变帧长
  *  - 状态机: 找帧头AA 55 -> 读帧长(合法性检查, 防缓冲区越界) -> 收数据 -> 校验和
  *  - 相比官方例程的改进:
  *      1. 帧长上限检查, LEN 非法直接丢弃重新同步(官方例程会越界写缓冲区)
  *      2. 任意状态收到非法字节立即回到帧头搜索, 不会卡死
  *      3. 超时离线判定, 断连后摇杆自动归零, 不会保持最后速度乱跑
  *      4. 同时兼容 手机APP(0x20)/微信小程序(0x90)/蓝牙手柄(0xA0) 三种帧号
  *      5. 方向键防抖: 按住时偶发丢方向在 BT_DIR_HOLD_MS 内沿用上一方向,
  *         避免俯仰步进走走停停(见 bt_rc_dir)
  *  - 注意: HAL_UART_RxCpltCallback / HAL_UART_ErrorCallback 全工程只能定义一份,
  *          已从 main.c 移除, 统一在本文件处理
  ******************************************************************************
  */
#include "bt_rc.h"
#include <string.h>

#if BT_DEBUG_EN
#include "debug_port.h"
#endif

/* ---------------- 内部状态 ---------------- */
static bt_rc_t bt_rc;                 /* 解析结果 */
static UART_HandleTypeDef *bt_huart = &BT_HUART;

static uint8_t  rx_byte;              /* 单字节接收缓冲 */
static uint8_t  frame_buf[BT_FRAME_MAX];
static uint8_t  frame_idx;            /* 当前已收字节数 */
static uint8_t  frame_len;            /* 本帧预期总长 */
static uint16_t frame_sum;            /* 校验和累加 */

/* 方向键防抖状态(只在 bt_rc_dir 里用) */
static int8_t   dir_last;             /* 上一次有效方向 +1/-1/0 */
static uint32_t dir_hold_tick;        /* 最后一次看到该方向的时刻 */
static uint32_t dir_bridge_cnt;       /* 被防抖桥接的调用次数(调试用) */

static int8_t bt_sign8(uint8_t v)
{
    return (int8_t)v;
}

/* 帧解码: frame_buf 内已是一帧校验通过的数据 */
static void bt_decode_frame(void)
{
    uint8_t id   = frame_buf[3];
    uint8_t type = frame_buf[4];
    const uint8_t *d = &frame_buf[5]; /* 数据区首地址 */

    switch (id)
    {
        case BT_FRAME_ID_APP:        /* 手机APP, 12字节: 左X 左Y 右X 右Y 键1 键2 */
        {
            if (frame_len == 12 && (type == 0x01 || type == 0x02))
            {
                bt_rc.lx   = bt_sign8(d[0]);
                bt_rc.ly   = bt_sign8(d[1]);
                bt_rc.rx   = bt_sign8(d[2]);
                bt_rc.ry   = bt_sign8(d[3]);
                bt_rc.key1 = d[4];
                bt_rc.key2 = d[5];
                bt_rc.frame_id   = id;
                bt_rc.frame_type = type;
                bt_rc.link = 1;
                bt_rc.ok_cnt++;
                bt_rc.last_tick = HAL_GetTick();
            }
            break;
        }

        case BT_FRAME_ID_MINI:       /* 微信小程序, 9字节: 摇X 摇Y 键1 */
        {
            if (frame_len == 9 && type == 0x01)
            {
                bt_rc.lx   = bt_sign8(d[0]);
                bt_rc.ly   = bt_sign8(d[1]);
                bt_rc.rx   = 0;
                bt_rc.ry   = 0;
                bt_rc.key1 = d[2];
                bt_rc.frame_id   = id;
                bt_rc.frame_type = type;
                bt_rc.link = 1;
                bt_rc.ok_cnt++;
                bt_rc.last_tick = HAL_GetTick();
            }
            break;
        }

        case BT_FRAME_ID_GAMEPAD:    /* 蓝牙手柄 */
        {
            if (type == 0x01 && frame_len == 15)
            {   /* 标准数据: 左X 左Y 右X 右Y 键1 键2 键3 右扳机 左扳机 */
                bt_rc.lx     = bt_sign8(d[0]);
                bt_rc.ly     = bt_sign8(d[1]);
                bt_rc.rx     = bt_sign8(d[2]);
                bt_rc.ry     = bt_sign8(d[3]);
                bt_rc.key1   = d[4];
                bt_rc.key2   = d[5];
                bt_rc.key3   = d[6];
                bt_rc.trig_r = d[7];
                bt_rc.trig_l = d[8];
                bt_rc.link   = 1;
                bt_rc.frame_id   = id;
                bt_rc.frame_type = type;
                bt_rc.ok_cnt++;
                bt_rc.last_tick = HAL_GetTick();
            }
            else if (type == 0x00 && frame_len == 7)
            {   /* 连接提示帧: 0x55=连接成功 0xFF=断开 */
                bt_rc.link = (d[0] == 0x55) ? 1u : 0u;
                bt_rc.frame_id   = id;
                bt_rc.frame_type = type;
                bt_rc.ok_cnt++;
                bt_rc.last_tick = HAL_GetTick();
            }
            break;
        }

        default:                     /* 其他帧号: 不认识, 丢弃 */
            bt_rc.err_cnt++;
            break;
    }
}

/* 逐字节状态机, 在串口接收完成中断上下文中执行 */
static void bt_rx_state_machine(uint8_t byte)
{
    if (frame_idx == 0)              /* 等帧头1: AA */
    {
        if (byte == 0xAA)
        {
            frame_buf[frame_idx++] = byte;
        }
    }
    else if (frame_idx == 1)         /* 等帧头2: 55 */
    {
        if (byte == 0x55)
        {
            frame_buf[frame_idx++] = byte;
        }
        else
        {
            frame_idx = 0;           /* 重新同步 */
        }
    }
    else if (frame_idx == 2)         /* 帧长 */
    {
        /* 最短帧: 帧头2+长度1+帧号1+校验1 = 5; 上限防越界 */
        if (byte >= 5 && byte <= BT_FRAME_MAX)
        {
            frame_len = byte;
            frame_sum = (uint16_t)(0xAA + 0x55 + byte);
            frame_buf[frame_idx++] = byte;
        }
        else
        {
            frame_idx = 0;
            bt_rc.err_cnt++;
        }
    }
    else                             /* 数据区 + 最后1字节校验 */
    {
        frame_buf[frame_idx] = byte;

        if (frame_idx < (uint8_t)(frame_len - 1))
        {
            frame_sum += byte;
            frame_idx++;
        }
        else                         /* 收到最后1字节: 校验 */
        {
            frame_idx = 0;
            if ((uint8_t)frame_sum == byte)
            {
                bt_decode_frame();
            }
            else
            {
                bt_rc.err_cnt++;
            }
        }
    }
}

/* ---------------- 对外接口 ---------------- */

void bt_rc_init(void)
{
    memset(&bt_rc, 0, sizeof(bt_rc_t));
    frame_idx = 0;
    frame_len = 0;
    frame_sum = 0;
    dir_last       = 0;
    dir_hold_tick  = 0;
    dir_bridge_cnt = 0;

    HAL_UART_Receive_IT(bt_huart, &rx_byte, 1);
}

uint8_t bt_rc_is_online(void)
{
    return (bt_rc.last_tick != 0u) &&
           ((HAL_GetTick() - bt_rc.last_tick) < BT_ONLINE_TIMEOUT_MS);
}

const bt_rc_t *bt_rc_update(void)
{
    if (bt_rc.last_tick != 0u &&
        (HAL_GetTick() - bt_rc.last_tick) >= BT_ONLINE_TIMEOUT_MS)
    {
        /* 离线: 摇杆/按键清零, 防止保持最后速度乱跑 */
        bt_rc.lx = 0;
        bt_rc.ly = 0;
        bt_rc.rx = 0;
        bt_rc.ry = 0;
        bt_rc.key1 = 0;
        bt_rc.key2 = 0;
        bt_rc.key3 = 0;
        bt_rc.trig_r = 0;
        bt_rc.trig_l = 0;
    }

#if BT_SINGLE_STICK_FALLBACK
    /*
     * 微信小程序(0x90)只有一个摇杆, 解析时存在 lx/ly, rx/ry 恒为0。
     * 主循环的映射是"右摇杆管平动、左摇杆管旋转", 小程序下会完全没法平动。
     * 这里把 ry/rx 镜像自 ly/lx, 且在镜像模式下把 lx 置0避免同时触发旋转。
     */
    if (bt_rc.frame_id == BT_FRAME_ID_MINI)
    {
        bt_rc.ry = bt_rc.ly;
        bt_rc.rx = bt_rc.lx;
        bt_rc.lx = 0;   /* 防止镜像出来的 rx 又被当成旋转量 */
    }
#endif

    return &bt_rc;
}

/* ---------------- HAL 回调(全工程唯一) ---------------- */

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == bt_huart->Instance)
    {
        bt_rx_state_machine(rx_byte);
        HAL_UART_Receive_IT(bt_huart, &rx_byte, 1);
    }
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    if (huart->Instance == bt_huart->Instance)
    {
        /* 溢出/帧错误等: HAL已中止接收, 清状态机后重启接收 */
        frame_idx = 0;
        HAL_UART_Receive_IT(bt_huart, &rx_byte, 1);
    }
}

/* ---- V3 追加: LANRC 油门控制用的按键接口 ---- */
uint8_t bt_rc_key_a(void)
{
    if (!bt_rc_is_online())
    {
        return 0u;
    }
    return (bt_rc.key2 & BT_KEY2_A) ? 1u : 0u;
}

/* -------------------------------------------------------------------------
 * 方向键(云台俯仰 上/下)防抖
 *
 * 未防抖时的行为: key1 是帧数据字节直取, 没有任何滤波。按住键期间只要有一帧
 * key1 不是 1/5(触点抖动、蓝牙丢帧后重发、APP 触摸抖动), bt_rc_dir() 立刻返回 0,
 * 主循环下一拍就进减速分支, 每 10ms 掉 STEP_ACCEL_RPM_S*0.01 = 2RPM,
 * 于是电机走走停停。
 *
 * 防抖做法: 记录上一次有效方向与其时刻。方向丢失后 BT_DIR_HOLD_MS 内仍返回
 * 上一次方向; 超过该时长才认为真松手返回 0。
 *   - 反向按下(上/下互换)是新的有效方向, 立即生效, 不被窗口拦住;
 *   - 整体离线仍然立刻返回 0(依赖 bt_rc_is_online), 不走防抖;
 *   - 限位保护在 stepper_task_10ms 里独立生效, 与本函数无关, 压住即停。
 * 代价: 真松手后步进要多走 BT_DIR_HOLD_MS 才开始减速。
 * ------------------------------------------------------------------------- */
int8_t bt_rc_dir(void)
{
    int8_t   raw = 0;
    uint32_t now;

    if (!bt_rc_is_online())
    {
        dir_last      = 0;
        dir_hold_tick = 0;
        return 0;
    }

    if (bt_rc.key1 == BT_DPAD_UP)
    {
        raw = 1;
    }
    else if (bt_rc.key1 == BT_DPAD_DOWN)
    {
        raw = -1;
    }

    now = HAL_GetTick();

    if (raw != 0)
    {
        /* 有明确方向(含反向): 立即生效, 只记录时刻 */
        dir_last      = raw;
        dir_hold_tick = now;
        return raw;
    }

    /* 方向丢失: 窗口内沿用上一次方向, 跨过抖动/丢帧 */
    if ((dir_last != 0) && ((now - dir_hold_tick) <= BT_DIR_HOLD_MS))
    {
        dir_bridge_cnt++;
        return dir_last;
    }

    dir_last      = 0;
    dir_hold_tick = 0;
    return 0;
}

uint32_t bt_rc_dir_bridge_cnt(void)
{
    return dir_bridge_cnt;
}
