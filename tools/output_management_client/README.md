# Minimal wlr-output-management client

This folder contains a minimal Wayland client that uses the
`wlr-output-management-unstable-v1` protocol to:

1) connect to a CAGE Wayland socket
2) enumerate outputs (heads + modes)
3) switch to a “fullscreen” mode (preferred or highest resolution)
4) restore the previous mode from a saved state file

The client is intentionally small and **does not depend on the Waydroid
codebase**. It is designed to be called from scripts or from the GUI later.

## Files

- `output_management_client.c`: the client implementation
- `generate_protocol.sh`: downloads the XML and generates protocol stubs
- `Makefile`: builds the client using the generated protocol code

## Build prerequisites

You need:

- `wayland-client` development headers
- `wayland-scanner`
- a copy of `wlr-output-management-unstable-v1.xml`

The helper script will download the XML and generate protocol stubs:

```bash
./generate_protocol.sh
```

Then build:

```bash
make
```

This produces `output-management-client`.

## Usage

```bash
# Switch to preferred/max modes and save current modes to a state file
WAYLAND_DISPLAY=cage-0 \
  ./output-management-client --fullscreen --state-file /tmp/cage-output.state

# Restore previous modes from the state file
WAYLAND_DISPLAY=cage-0 \
  ./output-management-client --restore --state-file /tmp/cage-output.state
```

Notes:

- `--fullscreen` selects the preferred mode if available; otherwise it picks
  the mode with the largest resolution area.
- `--restore` re-applies the per-head mode saved in the state file.
- If multiple heads are present, each head is configured independently.
