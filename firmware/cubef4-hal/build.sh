#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

sdk=${STM32CUBE_F4_ROOT:-/workspace/tools/embedded-st-cubef4-1.28.3}
gcc=${ARM_GCC:-/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc}
cube_commit=94cae6e83f00e276a11957e7833c01ac3d0bd7af
output=${1:-firmware/cubef4-hal/out/robot.elf}
entry_source=${2:-firmware/cubef4-hal/main.c}

if [[ ! -e "$sdk" ]]; then
  mkdir -p "$(dirname "$sdk")"
  git -c advice.detachedHead=false clone --depth 1 --filter=blob:none --sparse --branch v1.28.3 \
    https://github.com/STMicroelectronics/STM32CubeF4.git "$sdk"
fi
require_revision() {
  local directory=$1 expected=$2 actual
  actual=$(git -C "$directory" rev-parse HEAD)
  if [[ "$actual" != "$expected" ]] || ! git -C "$directory" diff --quiet HEAD --; then
    printf 'Use an unmodified checkout of %s at %s\n' "$directory" "$expected" >&2
    exit 1
  fi
}

require_revision "$sdk" "$cube_commit"
template=Projects/STM32F4-Discovery/Templates_LL/STM32CubeIDE
if [[ ! -f "$sdk/$template/STM32F407VGTX_FLASH.ld" || ! -f "$sdk/Drivers/CMSIS/Include/core_cm4.h" ]]; then
  git -C "$sdk" sparse-checkout add Drivers/CMSIS/Include "${template%/STM32CubeIDE}"
fi
hal=Drivers/STM32F4xx_HAL_Driver
device=Drivers/CMSIS/Device/ST/STM32F4xx
git -C "$sdk" submodule update --init --depth 1 "$hal" "$device"
require_revision "$sdk/$hal" b6f0ed3829f3829eb358a2e7417d80bba1a42db7
require_revision "$sdk/$device" 3c77349ce04c8af401454cc51f85ea9a50e34fc1

if [[ ! -x "$gcc" ]]; then
  printf 'Install the pinned xPack compiler with bash experiments/renode-smoke/bootstrap.sh\n' >&2
  exit 1
fi
mkdir -p "$(dirname "$output")"
src=firmware/cubef4-hal
drivers=()
for module in hal hal_cortex hal_gpio hal_rcc hal_tim hal_tim_ex; do
  drivers+=("$sdk/$hal/Src/stm32f4xx_$module.c")
done
"$gcc" --version | sed -n '1p'
"$gcc" -mcpu=cortex-m4 -mthumb -mfpu=fpv4-sp-d16 -mfloat-abi=hard \
  -O2 -g3 -std=gnu11 -ffunction-sections -fdata-sections \
  -DSTM32F407xx -DUSE_HAL_DRIVER -DUSER_VECT_TAB_ADDRESS \
  -I"$src" -I"$sdk/$hal/Inc" -I"$sdk/$device/Include" -I"$sdk/Drivers/CMSIS/Include" \
  "$entry_source" "$src/robot.c" "${drivers[@]}" \
  "$sdk/$device/Source/Templates/system_stm32f4xx.c" \
  "$sdk/$template/Example/Startup/startup_stm32f407vgtx.s" \
  "$sdk/$template/Example/User/syscalls.c" "$sdk/$template/Example/User/sysmem.c" \
  -T"$sdk/$template/STM32F407VGTX_FLASH.ld" --specs=nano.specs --specs=nosys.specs \
  -Wl,--gc-sections,--build-id=none,-Map,"${output%.elf}.map" -o "$output"
printf 'Built %s from the handwritten HAL fixture and pinned ST components\n' "$output"
