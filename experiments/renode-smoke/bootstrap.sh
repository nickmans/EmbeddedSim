#!/usr/bin/env bash
set -euo pipefail
mkdir -p /workspace/tools /workspace/research/downloads /workspace/.runtime-config
cd /workspace/research/downloads
renode_archive=renode-1.17.0.linux-portable.tar.gz
arm_archive=xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz
if [ ! -f "$renode_archive" ]; then
  curl -fL --retry 2 "https://github.com/renode/renode/releases/download/v1.17.0/$renode_archive" -o "$renode_archive"
fi
if [ ! -f "$arm_archive" ]; then
  curl -fL --retry 2 "https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v15.2.1-1.1/$arm_archive" -o "$arm_archive"
fi
# Renode: hash recorded from this investigation's official HTTPS release download.
# xPack: hash checked against the release publisher's .sha file.
sha256sum -c <<'CHECKSUMS'
4ba7c68b59e2447f188ef4b4b112fcccd2802582c460beedceb63b84e5605a5f  renode-1.17.0.linux-portable.tar.gz
da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6  xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz
CHECKSUMS
if [ ! -d /workspace/tools/renode_1.17.0-portable ]; then
  tar -xzf "$renode_archive" -C /workspace/tools
fi
if [ ! -d /workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1 ]; then
  tar -xzf "$arm_archive" -C /workspace/tools
fi
XDG_CONFIG_HOME=/workspace/.runtime-config /workspace/tools/renode_1.17.0-portable/renode --version
/workspace/tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc --version
