CC ?= cc
CFLAGS ?= -O2 -g -Wall -Wextra -std=c11

WAYLAND_CFLAGS := $(shell pkg-config --cflags wayland-client)
WAYLAND_LIBS := $(shell pkg-config --libs wayland-client)

TARGET := output-management-client
SOURCES := output_management_client.c wlr-output-management-unstable-v1-protocol.c

all: $(TARGET)

$(TARGET): $(SOURCES)
	$(CC) $(CFLAGS) $(WAYLAND_CFLAGS) -o $@ $(SOURCES) $(WAYLAND_LIBS)

clean:
	rm -f $(TARGET)
