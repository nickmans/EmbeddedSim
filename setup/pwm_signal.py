"""Passive discovery for the F407 PWM capture and PWM output profile."""
import csv
import statistics

PWM_PINS = ("PA6", "PA7", "PB0", "PB1")
SIGNALS = (*PWM_PINS, "PC0", "PC1", "PC2", "PC3", "PB3", "PB5", "TIM2_IRQn", "PA0", "PA2")
REGISTERS = {
    "RCC_CR": 0x40023800, "RCC_PLLCFGR": 0x40023804, "RCC_CFGR": 0x40023808,
    "RCC_AHB1ENR": 0x40023830, "RCC_APB1ENR": 0x40023840, "RCC_APB2ENR": 0x40023844,
    "PA_MODER": 0x40020000, "PA_OTYPER": 0x40020004, "PA_AFRL": 0x40020020, "PA_PUPDR": 0x4002000C,
    "PB_MODER": 0x40020400, "PB_OTYPER": 0x40020404, "PB_AFRL": 0x40020420, "PB_ODR": 0x40020414,
    "PC_MODER": 0x40020800, "PC_OTYPER": 0x40020804, "PC_ODR": 0x40020814,
    "PE_MODER": 0x40021000, "PE_AFRL": 0x40021020,
    "TIM2_CR1": 0x40000000, "TIM2_DIER": 0x4000000C, "TIM2_CCMR1": 0x40000018,
    "TIM2_CCMR2": 0x4000001C, "TIM2_CCER": 0x40000020, "TIM2_PSC": 0x40000028,
    "TIM2_ARR": 0x4000002C, "TIM3_CR1": 0x40000400, "TIM3_CCMR1": 0x40000418,
    "TIM3_CCMR2": 0x4000041C, "TIM3_CCER": 0x40000420, "TIM3_PSC": 0x40000428,
    "TIM3_ARR": 0x4000042C, "TIM3_CCR1": 0x40000434, "TIM3_CCR2": 0x40000438,
    "TIM3_CCR3": 0x4000043C, "TIM3_CCR4": 0x40000440,
    "TIM4_CR1": 0x40000800, "TIM9_CR1": 0x40014000, "TIM9_CCER": 0x40014020,
    "SYST_RVR": 0xE000E014, "NVIC_ISER0": 0xE000E100,
}
ROUTES = {
    "PA0": ("TIM2", 1, 1, "capture input"),
    "PA2": ("TIM2", 3, 1, "capture input"),
    **{pin: ("TIM3", channel, 2, "PWM output") for channel, pin in enumerate(PWM_PINS, 1)},
    **{f"PC{i}": (None, None, None, "direction output") for i in range(4)},
    "PB3": (None, None, None, "brake output"), "PB5": (None, None, None, "brake output"),
    "PE5": ("TIM9", 1, 3, "unqualified PWM output"),
    "PE6": ("TIM9", 2, 3, "unqualified PWM output"),
}


def clock_tree(state):
    cfgr, pll = state["RCC_CFGR"], state["RCC_PLLCFGR"]
    source = cfgr >> 2 & 3
    sysclk = (16_000_000, 8_000_000, None, None)[source]
    if source == 2 and pll & 63:
        pll_input = 8_000_000 if pll & (1 << 22) else 16_000_000
        sysclk = pll_input * ((pll >> 6) & 511) // ((pll & 63) * 2 * (((pll >> 16) & 3) + 1))
    ahb = (1, 1, 1, 1, 1, 1, 1, 1, 2, 4, 8, 16, 64, 128, 256, 512)[(cfgr >> 4) & 15]
    dividers = (1, 1, 1, 1, 2, 4, 8, 16)
    apb1, apb2 = dividers[(cfgr >> 10) & 7], dividers[(cfgr >> 13) & 7]
    hclk = sysclk // ahb if sysclk else None
    return {
        "source": ("HSI", "HSE", "PLL", "unknown")[source], "sysclk_hz": sysclk, "hclk_hz": hclk,
        "pclk1_hz": hclk // apb1 if hclk else None, "pclk2_hz": hclk // apb2 if hclk else None,
        "apb1_timer_hz": hclk // apb1 * (2 if apb1 > 1 else 1) if hclk else None,
    }


def decode(capture, edge_file):
    edges = {pin: [] for pin in SIGNALS}
    with edge_file.open() as stream:
        for row in csv.DictReader(stream):
            edges[SIGNALS[int(row["signal"])]].append((int(row["virtual_ns"]), int(row["level"])))
    snapshots = []
    with capture.open() as stream:
        for _, timestamp, *values in csv.reader(stream):
            now = int(timestamp)
            state = dict(zip(REGISTERS, (int(value, 16) for value in values), strict=True))
            clocks = clock_tree(state)
            profile = (clocks["source"] == "PLL" and state["RCC_CR"] & (1 << 25)
                       and not state["RCC_PLLCFGR"] & (1 << 22)
                       and (clocks["sysclk_hz"], clocks["hclk_hz"], clocks["pclk1_hz"], clocks["pclk2_hz"])
                       == (168_000_000, 168_000_000, 42_000_000, 84_000_000))
            pins = {}
            for pin, (timer, channel, af, role) in ROUTES.items():
                port, index = pin[:2], int(pin[2:])
                mode = state[f"{port}_MODER"] >> (2 * index) & 3
                mux = state[f"{port}_AFRL"] >> (4 * index) & 15 if mode == 2 else None
                gpio_output = timer is None and mode == 1 and not (state[f"{port}_OTYPER"] >> index & 1)
                routed = timer is not None and mode == 2 and mux == af
                configured, running, expected, timer_settings = False, False, None, None
                if routed:
                    flags = state[f"{timer}_CCER"] >> (4 * (channel - 1)) & 15
                    clock_enabled = (state["RCC_APB2ENR"] & (1 << 16) if timer == "TIM9"
                                     else state["RCC_APB1ENR"] & (1 << (int(timer[-1]) - 2)))
                    running = bool(state[f"{timer}_CR1"] & 1 and flags & 1 and clock_enabled)
                    if timer in ("TIM2", "TIM3"):
                        prescaler, arr = (state[f"{timer}_{reg}"] for reg in ("PSC", "ARR"))
                        timer_settings = {"psc": prescaler, "arr": arr,
                                          "counter_hz": clocks["apb1_timer_hz"] / (prescaler + 1)
                                          if clock_enabled and clocks["apb1_timer_hz"] else None}
                        slot = (channel - 1) % 2
                        cc = state[f"{timer}_CCMR{(channel - 1) // 2 + 1}"] >> (8 * slot) & 255
                        if timer == "TIM2":
                            configured = cc == 1 and flags in (1, 3)
                            timer_settings.update(edge="falling" if flags & 2 else "rising",
                                                  capture_interrupt=bool(state["TIM2_DIER"] & (1 << channel)))
                        else:
                            configured = cc & 0x73 == 0x60 and flags == 1
                            if running and clocks["apb1_timer_hz"]:
                                expected = (arr + 1) / timer_settings["counter_hz"]
                prior = [(t, v) for t, v in edges.get(pin, ()) if t < now]
                recent = [(t, v) for t, v in prior if t >= now - 4_000_000]
                rises = [t for t, v in recent if v]
                period = statistics.median(b - a for a, b in zip(rises, rises[1:])) * 1e-9 if len(rises) > 1 else None
                observed = {
                    "level": prior[-1][1] if prior else 0,
                    "period_s": period,
                    "activity": ("periodic" if period else
                                 "constant in observation window" if now >= 4_000_000 and not recent else
                                 "insufficient observation"),
                } if gpio_output or (routed and role == "PWM output" and running) else None
                if observed and period:
                    highs = [b[0] - a[0] for a, b in zip(recent, recent[1:]) if a[1] and not b[1]]
                    observed["duty"] = statistics.median(highs) * 1e-9 / period if highs else None
                pins[pin] = {
                    "mode": ("input", "output", "alternate function", "analog")[mode], "af": mux,
                    "peripheral": f"{timer}_CH{channel}" if routed else None,
                    "role": role, "qualified": bool(profile and (gpio_output or configured and running)),
                    "timer_running": running if timer else None, "timer": timer_settings,
                    "expected_period_s": expected, "observed": observed,
                }
            snapshots.append({"time_s": now * 1e-9, "clock_profile_matches": bool(profile),
                              "clocks": clocks, "pins": pins})
    return snapshots
