"""Decode bounded register snapshots and independently measured pin activity."""
from config import PINS

MODES = ("input", "output", "alternate function", "analog")


def decode_snapshots(path):
    snapshots = []
    for row in path.read_text().splitlines():
        values = row.split("\t")
        time = float(values[0])
        cfgr, ahb, apb = map(int, values[1:4])
        gpio = [tuple(map(int, values[i:i + 3])) for i in (4, 7)]
        timers = [list(map(int, values[i:i + 8])) for i in (10, 18, 26)]
        clock = (cfgr & 0xFCFC) == 0x8000  # SWS HSI, AHB /1, APB1 /1, APB2 /2
        pins = {}
        for name, (kind, peripheral, wanted_af) in PINS.items():
            port = "AB".index(name[1])
            pin = int(name[2:])
            moder, otype, afr = gpio[port]
            mode = MODES[(moder >> (pin * 2)) & 3]
            af = (afr >> (pin * 4)) & 15 if mode == MODES[2] else None
            enabled = bool(ahb & (1 << port))
            pin_info = dict(mode=mode, af=af, peripheral=peripheral if af == wanted_af else None,
                            qualified_route=peripheral or "GPIO direction", role=None,
                            configuration="Unconfirmed or unmapped", timer=None, activity=None)
            pins[name] = pin_info
            qualifies = False
            if kind == "direction" and mode == "output":
                pin_info["role"] = "output"
                qualifies = enabled and not (otype >> pin & 1)
                pin_info["configuration"] = "Qualified push-pull GPIO" if qualifies else "Unsupported GPIO settings"
            if peripheral and mode == MODES[2] and af == wanted_af:
                timer = int(peripheral[3]) - 2
                channel = int(peripheral[-1])
                cr1, smcr, ccmr, ccer, psc, arr, ccr1, ccr2 = timers[timer]
                ch_mode = ccmr >> (8 * (channel - 1)) & 255
                ch_enable = ccer >> (4 * (channel - 1)) & 15
                is_pwm = ch_mode & 3 == 0 and (ch_mode >> 4 & 7) in (6, 7)
                settings = dict(enabled=bool(cr1 & 1), clock_enabled=bool(apb & (1 << timer)),
                                channel_enabled=bool(ch_enable & 1), psc=psc, arr=arr, sms=smcr & 7,
                                channel_mode=ch_mode, channel_flags=ch_enable,
                                ccr=(ccr1, ccr2)[channel - 1] if ch_mode & 3 == 0 else None)
                pin_info["timer"] = settings
                available = enabled and clock and settings["clock_enabled"]
                if kind == "pwm" and is_pwm:
                    pin_info["role"] = "output"
                    qualifies = (available and (ch_mode >> 4 & 7) == 6 and ch_enable == 1 and
                                 not (cr1 & 0x78) and smcr & 7 == 0 and psc == 15 and arr == 999
                                 and not (otype >> pin & 1))
                    pin_info["configuration"] = "Qualified PWM1 · 1 kHz" if qualifies else "PWM mode · outside qualified settings"
                elif kind.startswith("encoder") and ch_mode & 3:
                    pin_info["role"] = "input"
                    qualifies = available and (smcr & 7) == 3 and ch_mode == 1 and ch_enable == 1 and arr == 65535 and psc == 0
                    pin_info["configuration"] = "Qualified encoder A/B" if qualifies else "Timer input · outside qualified settings"
            if name in ("PA0", "PA1", "PA4", "PA5"):
                index = 34 + ("PA0", "PA1", "PA4", "PA5").index(name) * 5
                level, edges, age, period, duty = values[index:index + 5]
                if qualifies and (kind == "direction" or pin_info["timer"]["enabled"]):
                    observation = dict(level="high" if level == "1" else "low", edges=int(edges))
                    if kind == "pwm":
                        if period:
                            observation.update(kind="periodic", period_s=float(period), duty=float(duty))
                        elif time >= 0.002 and float(age) >= 0.002:
                            observation.update(kind="constant", duty=float(level), period_s=None)
                        else:
                            observation.update(kind="insufficient observation", duty=None, period_s=None)
                    pin_info["activity"] = observation
            pin_info["qualified"] = qualifies
        snapshots.append(dict(time_s=time, clock_profile_matches=clock, pins=pins))
    return snapshots
