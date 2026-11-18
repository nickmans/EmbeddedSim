#!/usr/bin/env bash
set -euo pipefail
cache=${EMBEDDEDSIM_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/embeddedsim}
tools=${EMBEDDEDSIM_TOOLS_DIR:-$cache/tools}
downloads=${EMBEDDEDSIM_DOWNLOADS_DIR:-$cache/downloads}
mkdir -p "$tools" "$downloads" "$cache/runtime"
cache=$(realpath "$cache")
tools=$(realpath "$tools")
downloads=$(realpath "$downloads")
cd "$downloads"
renode_archive=renode-1.17.0.linux-portable.tar.gz
arm_archive=xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz

download() {
  local archive=$1 url=$2
  if [[ ! -f "$archive" ]]; then
    if [[ ${EMBEDDEDSIM_OFFLINE:-0} == 1 ]]; then
      printf 'Offline setup needs %s in %s\n' "$archive" "$downloads" >&2
      exit 1
    fi
    local partial
    partial=$(mktemp "$archive.XXXXXX")
    if ! curl -fL --retry 2 "$url/$archive" -o "$partial"; then
      rm -f "$partial"
      return 1
    fi
    mv "$partial" "$archive"
  fi
}

download "$renode_archive" https://github.com/renode/renode/releases/download/v1.17.0
download "$arm_archive" https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v15.2.1-1.1
# Renode's hash was recorded from the official release. The xPack hash
# was also checked against the publisher's checksum.
sha256sum -c <<'CHECKSUMS'
4ba7c68b59e2447f188ef4b4b112fcccd2802582c460beedceb63b84e5605a5f  renode-1.17.0.linux-portable.tar.gz
da6a49ad4003944b823c6c93702a8787c922ab34bd7e918ec0eaf6933a9b1ff6  xpack-arm-none-eabi-gcc-15.2.1-1.1-linux-x64.tar.gz
CHECKSUMS
install_tool() (
  local archive=$1 package=$2 executable=$3 staging
  if [[ -x "$tools/$package/$executable" ]]; then
    return
  fi
  staging=$(mktemp -d "$tools/.extract.XXXXXX")
  trap 'rm -rf -- "$staging"' EXIT
  tar -xzf "$archive" -C "$staging"
  test -x "$staging/$package/$executable"
  if ! mv -T "$staging/$package" "$tools/$package"; then
    test -x "$tools/$package/$executable"
  fi
)
install_tool "$renode_archive" renode_1.17.0-portable renode
install_tool "$arm_archive" xpack-arm-none-eabi-gcc-15.2.1-1.1 bin/arm-none-eabi-gcc
XDG_CONFIG_HOME="$cache/runtime" "$tools/renode_1.17.0-portable/renode" --version
"$tools/xpack-arm-none-eabi-gcc-15.2.1-1.1/bin/arm-none-eabi-gcc" --version
