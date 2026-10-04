#include "pid.h"                  // Device header


static int PID_Limit(int value, int limit)
{
    if (limit <= 0)
    {
        return value;
    }

    if (value > limit)
    {
        return limit;
    }

    if (value < -limit)
    {
        return -limit;
    }

    return value;
}


int PID_Calculate(PID_Controller *pid, int measured)
{
    int error, derivative;
    int p_out, i_out, d_out;

    // 计算误差
    error = pid->setpoint - measured;

    // 积分项
    pid->integral += error;

    // 微分项
    derivative = error - pid->last_error;

    // 更新上一次误差
    pid->last_error = error;

    // PID计算
    p_out = (int)(pid->kp * error);
    i_out = (int)(pid->ki * pid->integral);
    i_out = PID_Limit(i_out, pid->max_iout);
    if (pid->ki != 0.0f)
    {
        pid->integral = (int)(i_out / pid->ki);
    }
    d_out = (int)(pid->kd * derivative);

    pid->output = p_out + i_out + d_out;
    pid->output = PID_Limit(pid->output, pid->max_output);

    return pid->output;
}

void PID_Reset(PID_Controller *pid)
{
    pid->last_error = 0;
    pid->integral = 0;
    pid->output = 0;
}
