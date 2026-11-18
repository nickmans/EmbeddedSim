#ifndef EMBEDDEDSIM_CUBEF4_HAL_ROBOT_H
#define EMBEDDEDSIM_CUBEF4_HAL_ROBOT_H

#include "stm32f4xx_hal.h"

void Robot_Start(TIM_HandleTypeDef *pwm, TIM_HandleTypeDef *left_encoder,
                 TIM_HandleTypeDef *right_encoder);
void Robot_Step(TIM_HandleTypeDef *timer);

#endif
