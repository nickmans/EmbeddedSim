#include "stm32f4xx_hal.h"

static void check(int condition)
{
    if (!condition) {
        __disable_irq();
        for (;;) __WFI();
    }
}

static volatile unsigned interrupts;
static volatile unsigned flags_seen;
static volatile unsigned tick_deltas[4];
static volatile unsigned irq_deltas[4];

void SysTick_Handler(void)
{
    ++interrupts;
    HAL_IncTick();
    HAL_GPIO_TogglePin(GPIOA, GPIO_PIN_5);
}

static volatile uint32_t *alias(uint32_t address, unsigned bit)
{
    return (volatile uint32_t *)(0x42000000U + (address - 0x40000000U) * 32U + bit * 4U);
}

static void clock_tree(uint32_t source, uint32_t hpre, uint32_t ppre1, uint32_t ppre2, uint32_t latency)
{
    RCC_ClkInitTypeDef config = {
        .ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2,
        .SYSCLKSource = source, .AHBCLKDivider = hpre, .APB1CLKDivider = ppre1, .APB2CLKDivider = ppre2,
    };
    check(HAL_RCC_ClockConfig(&config, latency) == HAL_OK);
}

static void timed_delay(unsigned phase, unsigned hclk, unsigned divider)
{
    check(SystemCoreClock == hclk && HAL_RCC_GetHCLKFreq() == hclk);
    if (divider == 8) {
        SysTick->LOAD = hclk / divider / 1000U - 1U;
        SysTick->VAL = 0;
        HAL_SYSTICK_CLKSourceConfig(SYSTICK_CLKSOURCE_HCLK_DIV8);
    }
    const unsigned start_tick = HAL_GetTick(), start_irq = interrupts;
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_SET);
    HAL_Delay(10);
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_RESET);
    tick_deltas[phase] = HAL_GetTick() - start_tick;
    irq_deltas[phase] = interrupts - start_irq;
}

int main(void)
{
    check(HAL_Init() == HAL_OK);
    __HAL_RCC_GPIOB_CLK_ENABLE();
    volatile uint32_t *gpio = alias((uint32_t)&RCC->AHB1ENR, 0);
    *gpio = 1;
    check(*gpio == 1 && (RCC->AHB1ENR & 3) == 3);
    *gpio = 0;
    check(*gpio == 0 && (RCC->AHB1ENR & 3) == 2);
    *gpio = 1;
    volatile uint32_t *timer = alias((uint32_t)&RCC->APB1ENR, 0);
    *timer = 1;
    check(*timer == 1 && (RCC->APB1ENR & 1));
    *timer = 0;
    check(*timer == 0 && !(RCC->APB1ENR & 1));
    GPIO_InitTypeDef pins = {
        .Pin = GPIO_PIN_4 | GPIO_PIN_5, .Mode = GPIO_MODE_OUTPUT_PP,
    };
    HAL_GPIO_Init(GPIOA, &pins);
    timed_delay(0, 16000000, 1);

    RCC_OscInitTypeDef oscillator = {
        .OscillatorType = RCC_OSCILLATORTYPE_HSI, .HSIState = RCC_HSI_ON,
        .HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT,
        .PLL = {.PLLState = RCC_PLL_ON, .PLLSource = RCC_PLLSOURCE_HSI,
                .PLLM = 8, .PLLN = 168, .PLLP = RCC_PLLP_DIV2, .PLLQ = 4},
    };
    check(HAL_RCC_OscConfig(&oscillator) == HAL_OK);
    check(*alias((uint32_t)&RCC->CR, 24) == 1 && (RCC->CR & RCC_CR_PLLRDY));
    clock_tree(RCC_SYSCLKSOURCE_PLLCLK, RCC_SYSCLK_DIV1, RCC_HCLK_DIV4, RCC_HCLK_DIV2, FLASH_LATENCY_5);
    timed_delay(1, 168000000, 1);
    clock_tree(RCC_SYSCLKSOURCE_PLLCLK, RCC_SYSCLK_DIV2, RCC_HCLK_DIV2, RCC_HCLK_DIV1, FLASH_LATENCY_5);
    timed_delay(2, 84000000, 8);
    clock_tree(RCC_SYSCLKSOURCE_HSI, RCC_SYSCLK_DIV1, RCC_HCLK_DIV1, RCC_HCLK_DIV2, FLASH_LATENCY_0);
    timed_delay(3, 16000000, 1);
    *alias((uint32_t)&RCC->CR, 24) = 0;
    check(*alias((uint32_t)&RCC->CR, 24) == 0 &&
          !(RCC->CR & RCC_CR_PLLRDY) && (RCC->CR & RCC_CR_HSIRDY));

    // Observe an underflow with SysTick exceptions disabled.
    SysTick->CTRL = SysTick_CTRL_ENABLE_Msk | SysTick_CTRL_CLKSOURCE_Msk;
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_SET);
    SysTick->VAL = 0;
    unsigned before = interrupts;
    while (!(SysTick->CTRL & SysTick_CTRL_COUNTFLAG_Msk)) {}
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_4, GPIO_PIN_RESET);
    check(interrupts == before);
    flags_seen = 1;
    SysTick->CTRL = 0;
    __disable_irq();
    for (;;) __WFI();
}
