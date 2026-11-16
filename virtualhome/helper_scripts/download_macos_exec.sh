#!/usr/bin/env bash
# Restore the VirtualHome v2.3.0 macOS Unity simulator.
#
# Official source (README and http://virtual-home.org/documentation):
#   http://virtual-home.org/release/simulator/v2.0/v2.3.0/macos_exec.zip
#   290,600,883 bytes, last-modified 2022-03-28, unpacks to macos_exec.v2.3.0.app
#
# virtual-home.org (128.30.100.223) often does not accept connections.
# The identical file is archived here:
#   https://web.archive.org/web/20250629100406id_/http://virtual-home.org/release/simulator/v2.0/v2.3.0/macos_exec.zip
#
# A local copy at sysexec/vh_v2.3.0_macos.zip is used when its size matches,
# so reinstall is instant and does not hit the network.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEST="${ROOT}/virtualhome/simulation/unity_simulator"
APP="${DEST}/macos_exec.v2.3.0.app"
EXPECTED_BYTES=290600883

OFFICIAL_URL="http://virtual-home.org/release/simulator/v2.0/v2.3.0/macos_exec.zip"
WAYBACK_URL="https://web.archive.org/web/20250629100406id_/http://virtual-home.org/release/simulator/v2.0/v2.3.0/macos_exec.zip"

file_bytes() {
  stat -f%z "$1" 2>/dev/null || stat -c%s "$1"
}

if [[ -x "${APP}/Contents/MacOS/VirtualHome" ]]; then
  echo "Simulator already installed: ${APP}"
  exit 0
fi

mkdir -p "${DEST}"

pick_local_zip() {
  local candidate size
  for candidate in \
    "${ROOT}/sysexec/vh_v2.3.0_macos.zip" \
    "${ROOT}/sysexec/macos_exec.zip"
  do
    if [[ -f "${candidate}" ]]; then
      size="$(file_bytes "${candidate}")"
      if [[ "${size}" == "${EXPECTED_BYTES}" ]]; then
        echo "${candidate}"
        return 0
      fi
      echo "Ignoring ${candidate}: size ${size} != ${EXPECTED_BYTES}" >&2
    fi
  done
  return 1
}

install_zip() {
  local zip="$1"
  echo "Extracting ${zip}"
  ditto -x -k "${zip}" "${DEST}"
  xattr -dr com.apple.quarantine "${APP}" 2>/dev/null || true
  chmod +x "${APP}/Contents/MacOS/VirtualHome"
  if [[ ! -x "${APP}/Contents/MacOS/VirtualHome" ]]; then
    echo "Extract finished but ${APP} is missing the VirtualHome binary." >&2
    exit 1
  fi
  echo "Installed ${APP}"
}

if zip_path="$(pick_local_zip)"; then
  install_zip "${zip_path}"
  exit 0
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
zip_path="${tmpdir}/macos_exec.zip"

download() {
  local url="$1" size
  echo "Downloading ${url}"
  curl -fL --retry 3 --retry-delay 2 --connect-timeout 20 -o "${zip_path}" "${url}"
  size="$(file_bytes "${zip_path}")"
  if [[ "${size}" != "${EXPECTED_BYTES}" ]]; then
    echo "Download size ${size} != expected ${EXPECTED_BYTES}" >&2
    rm -f "${zip_path}"
    return 1
  fi
}

if ! download "${OFFICIAL_URL}"; then
  echo "Official host failed. Falling back to the Wayback Machine archive."
  download "${WAYBACK_URL}"
fi

install_zip "${zip_path}"
