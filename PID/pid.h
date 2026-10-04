#ifndef PID_H
#define PID_H

typedef struct
{
    float kp;       // 比例系数
    float ki;       // 积分系数
    float kd;       // 微分系数
    int setpoint;   // 设定值
    int last_error; // 上一次误差
    int integral;   // 积分项
    int max_output; // 输出限幅
    int max_iout;   // 积分限幅
    int output;     // 本次输出
} PID_Controller;

int PID_Calculate(PID_Controller *pid, int measured);
void PID_Reset(PID_Controller *pid);


#endif
