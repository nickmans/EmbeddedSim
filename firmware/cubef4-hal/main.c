// Handwritten HAL integration fixture. Startup, linker and SystemInit come from ST.
#include "robot.h"

#if __FPU_USED != 1U
#error This fixture qualifies Cortex-M4 FPv4-SP hard-float execution.
#endif

static TIM_HandleTypeDef pwm = {.Instance = TIM2};
static TIM_HandleTypeDef left = {.Instance = TIM3};
static TIM_HandleTypeDef right = {.Instance = TIM4};
static volatile float data_probe = 1.25f;
static volatile uint32_t bss_probe;

static void require(int condition)
{
    if (condition) return;
    __disable_irq();
    for (;;) __WFI();
}

void HAL_MspInit(void)
{
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    __HAL_RCC_PWR_CLK_ENABLE();
}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

void TIM2_IRQHandler(void)
{
    HAL_TIM_IRQHandler(&pwm);
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *timer)
{
    Robot_Step(timer);
}

static void configure_clock(void)
{
    RCC_OscInitTypeDef oscillator = {
        .OscillatorType = RCC_OSCILLATORTYPE_HSI,
        .HSIState = RCC_HSI_ON,
        .HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT,
        .PLL = {.PLLState = RCC_PLL_NONE},
    };
    require(HAL_RCC_OscConfig(&oscillator) == HAL_OK);

    RCC_ClkInitTypeDef clock = {
        .ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                     RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2,
        .SYSCLKSource = RCC_SYSCLKSOURCE_HSI,
        .AHBCLKDivider = RCC_SYSCLK_DIV1,
        .APB1CLKDivider = RCC_HCLK_DIV1,
        .APB2CLKDivider = RCC_HCLK_DIV2,
    };
    require(HAL_RCC_ClockConfig(&clock, FLASH_LATENCY_0) == HAL_OK);
    require(SystemCoreClock == 16000000U && HAL_RCC_GetHCLKFreq() == 16000000U);
    require(HAL_RCC_GetPCLK1Freq() == 16000000U && HAL_RCC_GetPCLK2Freq() == 8000000U);
}

static void configure_gpio(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    GPIO_InitTypeDef pin = {
        .Pin = GPIO_PIN_4 | GPIO_PIN_5,
        .Mode = GPIO_MODE_OUTPUT_PP,
        .Pull = GPIO_NOPULL,
        .Speed = GPIO_SPEED_FREQ_LOW,
    };
    HAL_GPIO_WritePin(GPIOA, pin.Pin, GPIO_PIN_SET);
    HAL_GPIO_Init(GPIOA, &pin);

    pin.Mode = GPIO_MODE_AF_PP;
    pin.Pin = GPIO_PIN_0 | GPIO_PIN_1;
    pin.Alternate = GPIO_AF1_TIM2;
    HAL_GPIO_Init(GPIOA, &pin);
    pin.Pin = GPIO_PIN_6 | GPIO_PIN_7;
    pin.Alternate = GPIO_AF2_TIM3;
    HAL_GPIO_Init(GPIOA, &pin);
    pin.Alternate = GPIO_AF2_TIM4;
    HAL_GPIO_Init(GPIOB, &pin);
}

static void init_encoder(TIM_HandleTypeDef *timer)
{
    timer->Init = (TIM_Base_InitTypeDef){
        .CounterMode = TIM_COUNTERMODE_UP,
        .Period = 65535,
        .ClockDivision = TIM_CLOCKDIVISION_DIV1,
        .AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE,
    };
    TIM_Encoder_InitTypeDef input = {
        .EncoderMode = TIM_ENCODERMODE_TI12,
        .IC1Polarity = TIM_ICPOLARITY_RISING,
        .IC1Selection = TIM_ICSELECTION_DIRECTTI,
        .IC1Prescaler = TIM_ICPSC_DIV1,
        .IC2Polarity = TIM_ICPOLARITY_RISING,
        .IC2Selection = TIM_ICSELECTION_DIRECTTI,
        .IC2Prescaler = TIM_ICPSC_DIV1,
    };
    require(HAL_TIM_Encoder_Init(timer, &input) == HAL_OK);
    require(HAL_TIM_Encoder_Start(timer, TIM_CHANNEL_ALL) == HAL_OK);
}

static void configure_timers(void)
{
    __HAL_RCC_TIM2_CLK_ENABLE();
    __HAL_RCC_TIM3_CLK_ENABLE();
    __HAL_RCC_TIM4_CLK_ENABLE();
    init_encoder(&left);
    init_encoder(&right);

    pwm.Init = (TIM_Base_InitTypeDef){
        .Prescaler = 15,
        .CounterMode = TIM_COUNTERMODE_UP,
        .Period = 999,
        .ClockDivision = TIM_CLOCKDIVISION_DIV1,
        .AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE,
    };
    TIM_OC_InitTypeDef output = {
        .OCMode = TIM_OCMODE_PWM1,
        .Pulse = 0,
        .OCPolarity = TIM_OCPOLARITY_HIGH,
        .OCFastMode = TIM_OCFAST_DISABLE,
    };
    require(HAL_TIM_PWM_Init(&pwm) == HAL_OK);
    require(HAL_TIM_PWM_ConfigChannel(&pwm, &output, TIM_CHANNEL_1) == HAL_OK);
    require(HAL_TIM_PWM_ConfigChannel(&pwm, &output, TIM_CHANNEL_2) == HAL_OK);
    Robot_Start(&pwm, &left, &right);

    require(HAL_TIM_PWM_Start(&pwm, TIM_CHANNEL_1) == HAL_OK);
    require(HAL_TIM_PWM_Start(&pwm, TIM_CHANNEL_2) == HAL_OK);
    __HAL_TIM_CLEAR_FLAG(&pwm, TIM_FLAG_UPDATE);
    HAL_NVIC_SetPriority(TIM2_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
    require(HAL_TIM_Base_Start_IT(&pwm) == HAL_OK);
}

int main(void)
{
    require(bss_probe == 0 && data_probe == 1.25f);
    require((SCB->CPACR & (15UL << 20)) == (15UL << 20));
    // Volatile loads prevent constant folding and make FP execution observable.
    require(data_probe * data_probe == 1.5625f);
    require(HAL_Init() == HAL_OK);
    configure_clock();

    const uint32_t start = HAL_GetTick();
    HAL_Delay(5);
    const uint32_t elapsed = HAL_GetTick() - start;
    require(elapsed >= 6 && elapsed <= 8);

    configure_gpio();
    configure_timers();
    for (;;) __WFI();
}
