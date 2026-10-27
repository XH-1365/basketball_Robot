/**
  ******************************************************************************
  * @file    k210_follow.c
  * @brief   K210 视觉跟随链路（底盘侧）：收帧解析 + 看门狗 + 转向 P 控制 + 状态回传
  ******************************************************************************
  * 收帧（寄存器级 RXNE 中断，逐字节）
  *   为什么不用 HAL_UART_Receive_IT 回调：全工程只能有一份
  *   HAL_UART_RxCpltCallback，已经被蓝牙模块(bt_rc.c)占用；
  *   且 K210 是定格式 ASCII 行，直接寄存器读最简单，也方便和
  *   debug_print 的 TX 共用同一个 USART6 而互不干扰。
  *
  * 帧校验
  *   "K210,<seq>,<state>,<id>,<err_deg>,<dist_m>*<hh>\n"
  *   hh = 星号前所有字符的 XOR, 两位小写 hex
  *
  * 看门狗
  *   500ms 没有合法帧 -> online=0, state='?' -> 转向指令归零
  ******************************************************************************
  */

/* Includes ------------------------------------------------------------------*/
#include "k210_follow.h"
#include "usart.h"
#include <string.h>
#include <stdio.h>

/* ============================ 内部常量 ==================================== */

#define K210_PREFIX         "K210,"
#define K210_PREFIX_LEN     5U
#define K210_LINE_MAX       48U     /* 协议规定 <40 字节, 留余量 */

/* ============================ 内部变量 ==================================== */

static k210_follow_t s_k210;
static char    s_line[K210_LINE_MAX];
static uint8_t s_line_len;
static uint8_t s_line_overflow;
static uint32_t s_report_tick;
static int32_t  s_last_cmd;     /* 最近一次 wheel_cmd 输出, 回传用 */
static int32_t  s_last_vx;      /* 最近一次 vx_cmd 输出, 软起步斜坡用 */
static int16_t  s_target_dist_cm = K210_FOLLOW_DIST_CM;  /* 运行时锁定距离(cm) */

/* ============================ 内部函数 ==================================== */

/**
  * @brief  两位小写 hex 转数值; 非法字符返回 -1
  */
static int k210_hex2val(char c)
{
    if (c >= '0' && c <= '9') { return c - '0'; }
    if (c >= 'a' && c <= 'f') { return c - 'a' + 10; }
    return -1;
}

/**
  * @brief  解析无符号整数(十进制), 走到非数字或 end 为止
  * @retval 0=成功 -1=一个数字都没有
  */
static int k210_parse_u16(const char **ps, const char *end, uint16_t *out)
{
    const char *p = *ps;
    uint32_t v = 0U;

    if (p >= end || *p < '0' || *p > '9')
    {
        return -1;
    }
    while (p < end && *p >= '0' && *p <= '9')
    {
        v = v * 10U + (uint32_t)(*p - '0');
        if (v > 65535U) { v = 65535U; }
        p++;
    }
    *ps = p;
    *out = (uint16_t)v;
    return 0;
}

/**
  * @brief  解析带符号定点小数: [-]D[.DD] -> 值 * 10^frac_digits
  *         例: frac_digits=1, "-4.2" -> -42
  * @note   小数位不足补零, 多于 frac_digits 的位数直接丢弃(不四舍五入)
  */
static int k210_parse_fixed(const char **ps, const char *end, uint8_t frac_digits, int32_t *out)
{
    const char *p = *ps;
    int32_t sign = 1;
    int32_t intpart = 0;
    int32_t frac = 0;
    uint8_t cnt = 0;

    if (p < end && *p == '-') { sign = -1; p++; }
    else if (p < end && *p == '+') { p++; }

    if (p >= end || *p < '0' || *p > '9')
    {
        return -1;
    }
    while (p < end && *p >= '0' && *p <= '9')
    {
        intpart = intpart * 10 + (*p - '0');
        if (intpart > 30000) { intpart = 30000; }   /* 防溢出, 协议值远小于此 */
        p++;
    }
    if (p < end && *p == '.')
    {
        p++;
        while (p < end && *p >= '0' && *p <= '9' && cnt < frac_digits)
        {
            frac = frac * 10 + (*p - '0');
            cnt++;
            p++;
        }
    }
    while (cnt < frac_digits)
    {
        frac *= 10;
        cnt++;
    }
    while (p < end && *p >= '0' && *p <= '9') { p++; }  /* 丢弃多余小数位 */

    while (frac_digits > 0U)
    {
        intpart *= 10;
        frac_digits--;
    }
    *out = sign * (intpart + frac);
    *ps = p;
    return 0;
}

/**
  * @brief  处理一行完整数据(不含行尾), 校验并更新 s_k210
  */
static void k210_process_line(const char *line, uint8_t len)
{
    const char *star;
    const char *p;
    const char *end = line + len;
    int hh_hi;
    int hh_lo;
    uint16_t calc = 0U;
    uint16_t recv;
    uint16_t seq;
    uint16_t id;
    int32_t err;
    int32_t dist;
    char state;

    /* 1) 前缀 */
    if (len < (K210_PREFIX_LEN + 4U) || memcmp(line, K210_PREFIX, K210_PREFIX_LEN) != 0)
    {
        s_k210.bad_cnt++;
        return;
    }

    /* 2) 找星号, 算 XOR */
    star = memchr(line, '*', len);
    if (star == NULL || (end - star) != 3)          /* '*hh' 正好 3 字符 */
    {
        s_k210.bad_cnt++;
        return;
    }
    for (p = line; p < star; p++)
    {
        calc ^= (uint16_t)(uint8_t)*p;
    }
    hh_hi = k210_hex2val(star[1]);
    hh_lo = k210_hex2val(star[2]);
    if (hh_hi < 0 || hh_lo < 0)
    {
        s_k210.bad_cnt++;
        return;
    }
    recv = (uint16_t)((hh_hi << 4) | hh_lo);
    if (recv != (calc & 0xFFU))
    {
        s_k210.bad_cnt++;
        return;
    }

    /* 3) 字段: K210,<seq>,<state>,<id>,<err>,<dist>  (p 现在指向星号前) */
    p = line + K210_PREFIX_LEN;
    if (k210_parse_u16(&p, star, &seq) != 0 || p >= star || *p != ',')
    {
        s_k210.bad_cnt++;
        return;
    }
    p++;
    state = *p;
    if ((state != 'L' && state != 'S' && state != 'X') || (p + 1 >= star) || p[1] != ',')
    {
        s_k210.bad_cnt++;
        return;
    }
    p += 2;
    if (k210_parse_u16(&p, star, &id) != 0 || p >= star || *p != ',')
    {
        s_k210.bad_cnt++;
        return;
    }
    p++;
    if (k210_parse_fixed(&p, star, 1, &err) != 0 || p >= star || *p != ',')
    {
        s_k210.bad_cnt++;
        return;
    }
    p++;
    if (k210_parse_fixed(&p, star, 2, &dist) != 0)
    {
        s_k210.bad_cnt++;
        return;
    }

    /* 4) 全部通过: 丢帧统计(seq 环回按 65536 算) */
    if (s_k210.last_tick != 0U)
    {
        uint16_t diff = (uint16_t)(seq - s_k210.seq);
        if (diff > 1U)
        {
            s_k210.drop_cnt += diff - 1U;
        }
    }

    s_k210.seq         = seq;
    s_k210.id          = id;
    s_k210.state       = state;
    s_k210.err_deg_x10 = (int16_t)err;
    s_k210.dist_x100   = (int16_t)dist;
    s_k210.frame_cnt++;
    s_k210.last_tick   = HAL_GetTick();
    s_k210.online      = 1U;
}

/* ============================ 对外接口 ==================================== */

void k210_follow_init(void)
{
    memset(&s_k210, 0, sizeof(s_k210));
    s_k210.state = '?';
    s_line_len = 0U;
    s_line_overflow = 0U;
    s_last_cmd = 0;

    /* RX 用寄存器级中断, 与 HAL 的 TX(阻塞式)互不干扰 */
    __HAL_UART_ENABLE_IT(&huart6, UART_IT_RXNE);
}

void k210_follow_on_rx(uint8_t byte)
{
    if (byte == '\r')
    {
        return;                     /* 容忍 \r\n 行尾 */
    }
    if (byte == '\n')
    {
        if (s_line_overflow == 0U && s_line_len > 0U)
        {
            s_line[s_line_len] = '\0';
            k210_process_line(s_line, s_line_len);
        }
        else if (s_line_overflow != 0U)
        {
            s_k210.bad_cnt++;       /* 超长行整行丢弃 */
        }
        s_line_len = 0U;
        s_line_overflow = 0U;
        return;
    }
    if (s_line_len >= (K210_LINE_MAX - 1U))
    {
        s_line_overflow = 1U;       /* 继续吃字符直到行尾, 但不保存 */
        return;
    }
    s_line[s_line_len++] = (char)byte;
}

void k210_follow_task(void)
{
    if (s_k210.online != 0U &&
        (HAL_GetTick() - s_k210.last_tick) > K210_FOLLOW_WATCHDOG_MS)
    {
        s_k210.online = 0U;
        s_k210.state = '?';         /* 掉线, 转向指令会归零 */
    }
}

int32_t k210_follow_wheel_cmd(void)
{
    float err_deg;
    float w;

    s_last_cmd = 0;

    /* 只有 '在线 + 已锁定人' 才跟; 'S'(没人)/'X'(视觉挂)/掉线 都停 */
    if (s_k210.online == 0U || s_k210.state != 'L')
    {
        return 0;
    }

    err_deg = (float)s_k210.err_deg_x10 / 10.0f;

    /* 死区: 人基本居中就不转 */
    if (err_deg > -K210_DEADBAND_DEG && err_deg < K210_DEADBAND_DEG)
    {
        return 0;
    }

    w = K210_FOLLOW_KP * err_deg * K210_FOLLOW_DIR;
    if (w > (float)K210_W_MAX) { w = (float)K210_W_MAX; }
    if (w < -(float)K210_W_MAX) { w = -(float)K210_W_MAX; }

    s_last_cmd = (int32_t)w;
    return s_last_cmd;
}

int32_t k210_follow_vx_cmd(void)
{
    float err_cm;
    float err_deg_abs;
    float slow;
    float vx;
    int32_t target;

    /* 掉人/离线: 立刻停车(不走斜坡, 安全优先) */
    if (s_k210.online == 0U || s_k210.state != 'L')
    {
        s_last_vx = 0;
        return 0;
    }

    /* dist 未知(协议 -1 -> dist_x100 = -100): 距离不可信就不瞎走 */
    if (s_k210.dist_x100 < 0)
    {
        s_last_vx = 0;
        return 0;
    }

    /* 距离误差(cm): 正 = 太远(要前进), 负 = 太近(要后退)
     * dist_x100 单位恰好是 cm(协议 dist_m=1.23 -> 123), 不用再换单位 */
    err_cm = (float)s_k210.dist_x100 - (float)s_target_dist_cm;

    /* 死区: 贴着目标距离不动, 防止临界点前后窜(±DEADBAND 内, 含边界) */
    if (err_cm >= -(float)K210_DIST_DEADBAND_CM &&
        err_cm <=  (float)K210_DIST_DEADBAND_CM)
    {
        err_cm = 0.0f;
    }

    /* P 控制: rpm(cm 量纲) */
    vx = K210_FOLLOW_KV * err_cm;

    /* 转向联动降速: 人偏在侧边时别一边猛转一边冲 */
    err_deg_abs = (float)s_k210.err_deg_x10 / 10.0f;
    if (err_deg_abs < 0.0f) { err_deg_abs = -err_deg_abs; }

    if (err_deg_abs <= K210_TURN_SLOW_START)
    {
        slow = 1.0f;
    }
    else if (err_deg_abs >= K210_TURN_SLOW_FULL)
    {
        slow = K210_TURN_SLOW_MIN;
    }
    else
    {
        slow = 1.0f - (1.0f - K210_TURN_SLOW_MIN) *
               (err_deg_abs - K210_TURN_SLOW_START) /
               (K210_TURN_SLOW_FULL - K210_TURN_SLOW_START);
    }
    vx *= slow;

    /* 限幅 */
    if (vx >  (float)K210_VX_MAX) { vx =  (float)K210_VX_MAX; }
    if (vx < -(float)K210_VX_MAX) { vx = -(float)K210_VX_MAX; }

    vx *= K210_VX_DIR;
    target = (int32_t)vx;

    /* 软起步: 只在"同向加速(含从 0 起步)"时限每拍增量;
     * 目标为 0(停车) / 反向 都不限, 该停就立刻停, 该退就立刻退。
     * 注意 last=0 起步时也必须受限, 否则第一拍直接跳到满速。 */
    if (target != 0 &&
        ((target > 0 && s_last_vx >= 0) || (target < 0 && s_last_vx <= 0)))
    {
        if ((target - s_last_vx) > K210_VX_SLEW_UP)
        {
            target = s_last_vx + K210_VX_SLEW_UP;
        }
        else if ((s_last_vx - target) > K210_VX_SLEW_UP)
        {
            target = s_last_vx - K210_VX_SLEW_UP;
        }
    }

    s_last_vx = target;
    return s_last_vx;
}

void k210_follow_reset(void)
{
    s_last_vx  = 0;
    s_last_cmd = 0;
}

void k210_follow_set_target_dist_cm(int16_t cm)
{
    if (cm < K210_DIST_CM_MIN) { cm = K210_DIST_CM_MIN; }
    if (cm > K210_DIST_CM_MAX) { cm = K210_DIST_CM_MAX; }
    s_target_dist_cm = cm;
}

int16_t k210_follow_get_target_dist_cm(void)
{
    return s_target_dist_cm;
}

void k210_follow_report(uint8_t follow_mode)
{
    char buf[96];
    int len;
    int err_i = s_k210.err_deg_x10;
    int err_abs = (err_i < 0) ? -err_i : err_i;

    if ((HAL_GetTick() - s_report_tick) < K210_REPORT_MS)
    {
        return;
    }
    s_report_tick = HAL_GetTick();

    /* RM,<mode>,<state>,E=<err>,W=<w>,D=<dist_cm>,T=<目标cm>,V=<vx>,F=<frames>
     * —— 格式不约定, K210 只做 [CHAS] 回显; D/T/V 是距离保持的现场值 */
    len = snprintf(buf, sizeof(buf), "RM,%s,%c,E=%d.%d,W=%ld,D=%d,T=%d,V=%ld,F=%lu\n",
                   (follow_mode != 0U) ? "FLW" : "RC",
                   s_k210.state,
                   err_i / 10, err_abs % 10,
                   (long)s_last_cmd,
                   (int)s_k210.dist_x100,
                   (int)s_target_dist_cm,
                   (long)s_last_vx,
                   (unsigned long)s_k210.frame_cnt);
    if (len > 0)
    {
        if (len > (int)sizeof(buf) - 1) { len = (int)sizeof(buf) - 1; }
        (void)HAL_UART_Transmit(&huart6, (uint8_t *)buf, (uint16_t)len, 20U);
    }
}

const k210_follow_t *k210_follow_get(void)
{
    return &s_k210;
}

/************************ (C) COPYRIGHT *****END OF FILE***********************/
