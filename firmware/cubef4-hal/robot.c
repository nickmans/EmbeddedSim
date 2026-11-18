// Application logic shared with a future generated project via its user sections.
#include "robot.h"

enum { Window = 20, Period = 1000 };
static TIM_HandleTypeDef *drive;
static const uint32_t channels[] = {TIM_CHANNEL_1, TIM_CHANNEL_2};
static const uint16_t direction_pins[] = {GPIO_PIN_4, GPIO_PIN_5};
static uint32_t ticks;

struct Wheel {
    TIM_HandleTypeDef *encoder;
    uint16_t previous;
    int32_t counts;
    int32_t history[Window];
    float integral;
    uint8_t forward;
    uint8_t pending;
    uint8_t blank;
};
static struct Wheel wheels[2];

void Robot_Start(TIM_HandleTypeDef *pwm, TIM_HandleTypeDef *left_encoder,
                 TIM_HandleTypeDef *right_encoder)
{
    drive = pwm;
    wheels[0].encoder = left_encoder;
    wheels[1].encoder = right_encoder;
    for (unsigned side = 0; side < 2; ++side) {
        wheels[side].previous = (uint16_t)__HAL_TIM_GET_COUNTER(wheels[side].encoder);
        wheels[side].forward = 1;
    }
}

static float magnitude(float value)
{
    return value < 0.0f ? -value : value;
}

static float target(unsigned side)
{
    if (ticks >= 200 && ticks < 2000) return 10.0f;
    if (ticks >= 2800 && ticks < 4400) return side ? 5.0f : -5.0f;
    if (ticks >= 5200 && ticks < 7000) return side ? 10.0f : 6.0f;
    if (ticks >= 7800 && ticks < 9600) return -8.0f;
    return 0.0f;
}

static void output(struct Wheel *wheel, unsigned side, float effort)
{
    uint32_t compare = 0;
    const uint8_t forward = effort >= 0.0f;
    if (wheel->blank && --wheel->blank == 3) {
        wheel->forward = wheel->pending;
        HAL_GPIO_WritePin(GPIOA, direction_pins[side], wheel->forward ? GPIO_PIN_SET : GPIO_PIN_RESET);
    }
    if (!wheel->blank && magnitude(effort) >= 0.002f) {
        if (forward != wheel->forward) {
            wheel->pending = forward;
            wheel->blank = 6;
        } else {
            compare = (uint32_t)(Period * magnitude(effort) + 0.5f);
        }
    }
    __HAL_TIM_SET_COMPARE(drive, channels[side], compare);
}

void Robot_Step(TIM_HandleTypeDef *timer)
{
    if (timer != drive) return;
    const unsigned slot = ticks++ % Window;
    for (unsigned side = 0; side < 2; ++side) {
        struct Wheel *wheel = &wheels[side];
        const uint16_t count = (uint16_t)__HAL_TIM_GET_COUNTER(wheel->encoder);
        int32_t delta = (uint16_t)(count - wheel->previous);
        if (delta >= 32768) delta -= 65536;
        wheel->previous = count;
        wheel->counts += delta;
        const float speed = (wheel->counts - wheel->history[slot]) * (6.28318530718f / (4096 * 0.020f));
        wheel->history[slot] = wheel->counts;
        const float reference = target(side);
        const float error = reference - speed;
        const float candidate = wheel->integral + 0.02f * 0.001f * error;
        const float unsaturated = 0.04f * error + candidate;
        if (!wheel->blank && !((unsaturated > 1 && error > 0) || (unsaturated < -1 && error < 0))) {
            wheel->integral = candidate;
        }
        float effort = 0.04f * error + wheel->integral;
        if (reference == 0.0f && magnitude(speed) < 0.10f) {
            wheel->integral = 0.0f;
            effort = 0.0f;
        }
        if (effort > 1.0f) effort = 1.0f;
        if (effort < -1.0f) effort = -1.0f;
        output(wheel, side, effort);
    }
}
