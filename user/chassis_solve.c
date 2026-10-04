/**
  ******************************************************************************
  * @file    chassis_solve.c
  * @brief   全向轮(Omni)底盘逆运动学解算 —— 矩形四角布置
  *
  * ============================ 几何模型 ============================
  *
  * 车体坐标系: x 向前(车头), y 向左, 原点在车体几何中心。
  *
  *                 前 (+x)
  *      ┌──────────────────────────┐
  *      │  LF(-Lx,+Ly)  RF(+Lx,+Ly)│
  *      │      ○───────○           │
  *      │      │   ╲ ╱  │           │   ← 四个轮轴呈 X 形,
  *      │      │   ╱ ╲  │           │     指向车体中心(对角线方向)
  *      │      ○───────○           │
  *      │  LB(-Lx,-Ly)  RB(+Lx,-Ly)│
  *      └──────────────────────────┘
  *                 后 (-x)
  *
  * 全向轮特性: 辊子与轮轴垂直, 轮子只能沿"垂直于轮轴"的方向驱动车体,
  * 沿轮轴方向自由滑动(不产生力)。
  *
  * 矩形四角 + 轮轴指向对角线时, 每个轮子的"驱动方向"就是该角指向外侧
  * 的对角线方向(单位向量, 已乘 √2 去掉根号, 保留整数运算):
  *
  *      轮子   位置(-Lx..+Lx, -Ly..+Ly)   驱动方向 dx  dy
  *      LF     (-Lx, +Ly)                  -1        +1
  *      RF     (+Lx, +Ly)                  +1        +1
  *      LB     (-Lx, -Ly)                  -1        -1
  *      RB     (+Lx, -Ly)                  +1        -1
  *
  * ============================ 速度合成 ============================
  *
  * 刚体上任意点 P 的速度:  v(P) = (vx, vy) + w × r(P)
  * 其中 r(P) = 该点相对中心的位置向量, w 为绕 z 轴角速度(逆时针为正)。
  *
  *      旋转项:  w × r = w * (-r_y, +r_x)
  *      即 vx(P) = vx - w*r_y
  *         vy(P) = vy + w*r_x
  *
  * 轮子线速度 = v(P) · 驱动方向单位向量(乘 √2 后):
  *
  *      LF: (-1)*(vx - w*Ly) + (+1)*(vy + w*(-Lx)) = -vx + vy + w*(Ly + Lx)
  *      RF: (+1)*(vx - w*Ly) + (+1)*(vy + w*(+Lx)) = +vx + vy + w*(Lx - Ly)
  *      LB: (-1)*(vx + w*Ly) + (-1)*(vy + w*(-Lx)) = -vx - vy + w*(Lx - Ly)
  *      RB: (+1)*(vx + w*Ly) + (-1)*(vy + w*(+Lx)) = +vx - vy - w*(Lx + Ly)
  *
  * 注意旋转项系数四个轮子并不相同(取决于 Lx 和 Ly 是否相等)。
  * 对标准方阵底盘(Lx == Ly == L)可简化为:
  *
  *      LF: -vx + vy + 2L*w
  *      RF: +vx + vy + 0
  *      LB: -vx - vy + 0
  *      RB: +vx - vy - 2L*w
  *
  * 这个结果说明: 方阵底盘纯旋转时只有 LF 和 RB 出力, RF 和 LB 不动 ——
  * 这是矩形四角全向轮的固有特性(那两个轮子的驱动方向过瞬心)。
  *
  * 工程上通常把旋转项统一归一化, 引入 ROT_X100 系数把 2L 折算掉,
  * 使四个轮子都参与旋转, 这样扭矩更大、控制更稳。下面采用这种方式。
  *
  * ============================ 符号约定 ============================
  *
  * 上面推导出的符号可能与真实电机安装方向相反。因此每个轮子都留了
  * WHEEL_DIR_x 修正宏 —— 上机测试时哪个轮反转就翻哪个, 不要改公式。
  ******************************************************************************
  */
#include "chassis_solve.h"

void chassis_inverse_kinematics(int32_t vx, int32_t vy, int32_t w, int32_t *wheel)
{
    int32_t vx_d;
    int32_t vy_d;
    int32_t w_d;
    int32_t rot;

    if (wheel == 0)
    {
        return;
    }

    /* 整体方向修正(推杆方向反了改这几个宏) */
    vx_d = vx * VX_DIR;
    vy_d = vy * VY_DIR;
    w_d  = w  * W_DIR;

    /*
     * 旋转项归一化: 严格几何下 LF/RB 的系数为 ±2L, RF/LB 为 0。
     * 为了让四个轮子共同出力(扭矩更大、不易被摩擦卡住), 这里统一
     * 取相同系数, 由 ROT_X100 标定大小。
     * 若你想要严格几何解, 把 CHASSIS_ROT_STRICT 打开即可。
     */
    rot = (w_d * ROT_X100) / 100;

#if CHASSIS_ROT_STRICT
    /* 严格几何解(方阵底盘): 只有 LF / RB 参与旋转 */
    wheel[MOTOR_IDX_LF] = (-vx_d + vy_d + 2 * rot) * WHEEL_DIR_LF;
    wheel[MOTOR_IDX_RF] = ( vx_d + vy_d          ) * WHEEL_DIR_RF;
    wheel[MOTOR_IDX_LB] = (-vx_d - vy_d          ) * WHEEL_DIR_LB;
    wheel[MOTOR_IDX_RB] = ( vx_d - vy_d - 2 * rot) * WHEEL_DIR_RB;
#else
    /* 归一化解: 四轮均分旋转量(工程常用) */
    wheel[MOTOR_IDX_LF] = (-vx_d + vy_d + rot) * WHEEL_DIR_LF;
    wheel[MOTOR_IDX_RF] = ( vx_d + vy_d + rot) * WHEEL_DIR_RF;
    wheel[MOTOR_IDX_LB] = (-vx_d - vy_d + rot) * WHEEL_DIR_LB;
    wheel[MOTOR_IDX_RB] = ( vx_d - vy_d + rot) * WHEEL_DIR_RB;
#endif
}

void chassis_forward_kinematics(const int32_t *wheel, int32_t *vx, int32_t *vy, int32_t *w)
{
    int32_t lf, rf, lb, rb;

    if (wheel == 0)
    {
        return;
    }

    /* 先还原方向修正, 得到"几何量" */
    lf = wheel[MOTOR_IDX_LF] * WHEEL_DIR_LF;
    rf = wheel[MOTOR_IDX_RF] * WHEEL_DIR_RF;
    lb = wheel[MOTOR_IDX_LB] * WHEEL_DIR_LB;
    rb = wheel[MOTOR_IDX_RB] * WHEEL_DIR_RB;

    /*
     * 由逆解反推(归一化解):
     *      LF = -vx + vy + rot
     *      RF = +vx + vy + rot
     *      LB = -vx - vy + rot
     *      RB = +vx - vy + rot
     *
     * 求 vx: (RF + RB - LF - LB) / 4
     * 求 vy: (LF + RF - LB - RB) / 4
     * 求 w : (LF + RF + LB + RB) / 4 - 平动项残留(平动项和为0)
     */
    if (vx != 0)
    {
        *vx = ( rf + rb - lf - lb) / 4;
    }
    if (vy != 0)
    {
        *vy = ( lf + rf - lb - rb) / 4;
    }
    if (w != 0)
    {
        *w = ( lf + rf + lb + rb) / 4;
    }
}
