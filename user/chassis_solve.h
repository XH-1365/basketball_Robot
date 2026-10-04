/**
  ******************************************************************************
  * @file    chassis_solve.h
  * @brief   全向轮(Omni)底盘逆运动学解算 —— 车体坐标系
  *
  * 底盘构型: 矩形四角布置, 4 个全向轮, 辊子与轮轴垂直, 左右镜像
  *
  *              前 (车头)
  *      ┌───────────────────────┐
  *      │  LF(左前)     RF(右前) │
  *      │    ○             ○    │
  *      │    │             │    │
  *      │    ○             ○    │
  *      │  LB(左后)     RB(右后) │
  *      └───────────────────────┘
  *              后
  *
  * 电机 CAN 拨码/ID 映射 (沿用原 3508 拨码, 全挂 CAN1):
  *      index 0 <- 0x201 <- 拨码 1 <- 右后 RB
  *      index 1 <- 0x202 <- 拨码 2 <- 左后 LB
  *      index 2 <- 0x203 <- 拨码 3 <- 左前 LF
  *      index 3 <- 0x204 <- 拨码 4 <- 右前 RF
  *
  * 解算原理详见 chassis_solve.c 顶部注释(含完整几何推导)。
  * 核心: 四个轮轴呈 X 形(指向车体对角线), 每个轮子的驱动方向就是
  * 该角指向外侧的对角线方向; 轮子线速度 = 速度场在该方向上的投影。
  *
  *      >>> 上机发现某个方向反了, 不要改公式, 改下面的 DIR 宏 <<<
  ******************************************************************************
  */
#ifndef CHASSIS_SOLVE_H
#define CHASSIS_SOLVE_H

#include <stdint.h>

/* ===================== 电机数量与索引 ===================== */
#define CHASSIS_MOTOR_NUM   4

#define MOTOR_IDX_RB        0   /* 右后 0x201 拨码1 */
#define MOTOR_IDX_LB        1   /* 左后 0x202 拨码2 */
#define MOTOR_IDX_LF        2   /* 左前 0x203 拨码3 */
#define MOTOR_IDX_RF        3   /* 右前 0x204 拨码4 */

/* ===================== 轮子方向修正 ===================== */
/* 上机测试时: 哪一个轮子转向跟你预期相反, 就把对应的值改成 (-1) */
#define WHEEL_DIR_RB        (+1)
#define WHEEL_DIR_LB        (+1)
#define WHEEL_DIR_LF        (+1)
#define WHEEL_DIR_RF        (+1)

/* ===================== 速度分量方向修正 ===================== */
/* 推杆方向反了改这三个, 不要动矩阵 */
#define VX_DIR              (+1)    /* 前进为正 */
#define VY_DIR              (+1)    /* 向左平移为正 */
#define W_DIR               (+1)    /* 逆时针旋转为正 */

/* ===================== 旋转项处理方式 ===================== */
/*
 * 严格几何下(方阵底盘, Lx == Ly == L), 纯旋转时只有 LF 和 RB 出力:
 *      LF = -vx + vy + 2L*w
 *      RF = +vx + vy
 *      LB = -vx - vy
 *      RB = +vx - vy - 2L*w
 * 这是矩形四角全向轮的固有特性(另外两个轮的驱动方向过瞬心)。
 *
 * 工程上常用做法是让四个轮子均分旋转量(扭矩更大, 不易被静摩擦卡住),
 * 即把 2L 归一化掉, 用统一系数。默认用这种方式(CHASSIS_ROT_STRICT = 0)。
 * 想用严格几何解就设成 1。
 */
#define CHASSIS_ROT_STRICT  0

/* 归一化解里旋转项的权重, 100 = 1.00 倍。纯旋转不够劲或过冲就调这个 */
#define ROT_X100            100

/* ===================== 接口 ===================== */

/**
  * @brief  全向轮逆解: 车体三自由度速度 -> 四个轮子的目标线速度
  * @param  vx     车体前进方向速度 (已含量纲/缩放)
  * @param  vy     车体左移方向速度
  * @param  w      车体旋转角速度
  * @param  wheel  输出数组, 长度 CHASSIS_MOTOR_NUM, 顺序 RB LB LF RF
  * @retval 无
  */
void chassis_inverse_kinematics(int32_t vx, int32_t vy, int32_t w, int32_t *wheel);

/**
  * @brief  正解(可选, 用于把轮速换算回车体速度, 调试/里程计用)
  * @param  wheel  输入轮速数组
  * @param  vx/vy/w  输出车体速度指针(可为 NULL)
  */
void chassis_forward_kinematics(const int32_t *wheel, int32_t *vx, int32_t *vy, int32_t *w);

#endif /* CHASSIS_SOLVE_H */
