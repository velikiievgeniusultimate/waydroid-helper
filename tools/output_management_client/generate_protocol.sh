#!/usr/bin/env sh
set -eu

PROTO_URL="https://gitlab.freedesktop.org/wlroots/wlr-protocols/-/raw/master/unstable/wlr-output-management-unstable-v1.xml"
PROTO_XML="wlr-output-management-unstable-v1.xml"
PROTO_HEADER="wlr-output-management-unstable-v1-client-protocol.h"
PROTO_CODE="wlr-output-management-unstable-v1-protocol.c"

if ! command -v wayland-scanner >/dev/null 2>&1; then
  echo "wayland-scanner not found in PATH." >&2
  echo "Install wayland-scanner (usually from wayland-protocols or wayland dev packages)." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to download ${PROTO_URL}." >&2
  exit 1
fi

echo "Downloading ${PROTO_URL}..."
curl -fsSL "${PROTO_URL}" -o "${PROTO_XML}"

echo "Generating protocol stubs..."
wayland-scanner client-header "${PROTO_XML}" "${PROTO_HEADER}"
wayland-scanner private-code "${PROTO_XML}" "${PROTO_CODE}"

echo "Done."
