#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <wayland-client.h>

#include "wlr-output-management-unstable-v1-client-protocol.h"

struct mode_info {
    struct zwlr_output_mode_v1 *obj;
    int32_t width;
    int32_t height;
    int32_t refresh;
    bool preferred;
    struct wl_list link;
};

struct head_info {
    struct zwlr_output_head_v1 *obj;
    char *name;
    bool enabled;
    struct mode_info *current;
    struct wl_list modes;
    struct wl_list link;
};

struct client_state {
    struct wl_display *display;
    struct wl_registry *registry;
    struct zwlr_output_manager_v1 *manager;
    uint32_t serial;
    bool done;
    struct wl_list heads;
};

struct restore_entry {
    char *name;
    int32_t width;
    int32_t height;
    int32_t refresh;
    struct wl_list link;
};

static void mode_handle_size(void *data, struct zwlr_output_mode_v1 *mode, int32_t width,
                             int32_t height) {
    struct mode_info *info = data;
    info->width = width;
    info->height = height;
}

static void mode_handle_refresh(void *data, struct zwlr_output_mode_v1 *mode,
                                int32_t refresh) {
    struct mode_info *info = data;
    info->refresh = refresh;
}

static void mode_handle_preferred(void *data, struct zwlr_output_mode_v1 *mode) {
    struct mode_info *info = data;
    info->preferred = true;
}

static void mode_handle_finished(void *data, struct zwlr_output_mode_v1 *mode) {
    (void)data;
    (void)mode;
}

static const struct zwlr_output_mode_v1_listener mode_listener = {
    .size = mode_handle_size,
    .refresh = mode_handle_refresh,
    .preferred = mode_handle_preferred,
    .finished = mode_handle_finished,
};

static void head_handle_name(void *data, struct zwlr_output_head_v1 *head,
                             const char *name) {
    struct head_info *info = data;
    free(info->name);
    info->name = strdup(name);
}

static void head_handle_enabled(void *data, struct zwlr_output_head_v1 *head,
                                int32_t enabled) {
    struct head_info *info = data;
    info->enabled = enabled != 0;
}

static void head_handle_mode(void *data, struct zwlr_output_head_v1 *head,
                             struct zwlr_output_mode_v1 *mode) {
    struct head_info *info = data;
    struct mode_info *mode_info = calloc(1, sizeof(*mode_info));
    if (!mode_info) {
        return;
    }
    mode_info->obj = mode;
    wl_list_insert(&info->modes, &mode_info->link);
    zwlr_output_mode_v1_add_listener(mode, &mode_listener, mode_info);
}

static void head_handle_current_mode(void *data, struct zwlr_output_head_v1 *head,
                                     struct zwlr_output_mode_v1 *mode) {
    struct head_info *info = data;
    struct mode_info *entry = NULL;
    wl_list_for_each(entry, &info->modes, link) {
        if (entry->obj == mode) {
            info->current = entry;
            break;
        }
    }
}

static void head_handle_finished(void *data, struct zwlr_output_head_v1 *head) {
    (void)data;
    (void)head;
}

static const struct zwlr_output_head_v1_listener head_listener = {
    .name = head_handle_name,
    .description = NULL,
    .physical_size = NULL,
    .mode = head_handle_mode,
    .enabled = head_handle_enabled,
    .current_mode = head_handle_current_mode,
    .position = NULL,
    .transform = NULL,
    .scale = NULL,
    .finished = head_handle_finished,
    .make = NULL,
    .model = NULL,
    .serial_number = NULL,
    .adaptive_sync = NULL,
};

static void manager_handle_head(void *data, struct zwlr_output_manager_v1 *manager,
                                struct zwlr_output_head_v1 *head) {
    struct client_state *state = data;
    struct head_info *info = calloc(1, sizeof(*info));
    if (!info) {
        return;
    }
    info->obj = head;
    wl_list_init(&info->modes);
    wl_list_insert(&state->heads, &info->link);
    zwlr_output_head_v1_add_listener(head, &head_listener, info);
}

static void manager_handle_done(void *data, struct zwlr_output_manager_v1 *manager,
                                uint32_t serial) {
    struct client_state *state = data;
    state->serial = serial;
    state->done = true;
}

static void manager_handle_finished(void *data, struct zwlr_output_manager_v1 *manager) {
    struct client_state *state = data;
    state->done = true;
}

static const struct zwlr_output_manager_v1_listener manager_listener = {
    .head = manager_handle_head,
    .done = manager_handle_done,
    .finished = manager_handle_finished,
};

static void registry_handle_global(void *data, struct wl_registry *registry,
                                   uint32_t name, const char *interface,
                                   uint32_t version) {
    struct client_state *state = data;
    if (strcmp(interface, zwlr_output_manager_v1_interface.name) == 0) {
        uint32_t bind_version = version > 4 ? 4 : version;
        state->manager = wl_registry_bind(
            registry, name, &zwlr_output_manager_v1_interface, bind_version);
        zwlr_output_manager_v1_add_listener(state->manager, &manager_listener, state);
    }
}

static void registry_handle_global_remove(void *data, struct wl_registry *registry,
                                          uint32_t name) {
    (void)data;
    (void)registry;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_handle_global,
    .global_remove = registry_handle_global_remove,
};

static struct mode_info *select_fullscreen_mode(struct head_info *head) {
    struct mode_info *entry = NULL;
    struct mode_info *preferred = NULL;
    struct mode_info *largest = NULL;
    int64_t largest_area = -1;

    wl_list_for_each(entry, &head->modes, link) {
        if (entry->preferred) {
            preferred = entry;
        }
        int64_t area = (int64_t)entry->width * (int64_t)entry->height;
        if (area > largest_area) {
            largest_area = area;
            largest = entry;
        }
    }
    return preferred ? preferred : largest;
}

static int save_state(const char *path, struct client_state *state) {
    FILE *fp = fopen(path, "w");
    if (!fp) {
        fprintf(stderr, "Failed to open state file %s: %s\n", path, strerror(errno));
        return -1;
    }

    struct head_info *head = NULL;
    wl_list_for_each(head, &state->heads, link) {
        if (!head->name || !head->current) {
            continue;
        }
        fprintf(fp, "%s %d %d %d\n", head->name, head->current->width,
                head->current->height, head->current->refresh);
    }

    fclose(fp);
    return 0;
}

static struct wl_list load_state(const char *path) {
    struct wl_list entries;
    wl_list_init(&entries);

    FILE *fp = fopen(path, "r");
    if (!fp) {
        return entries;
    }

    char name[256];
    int width = 0;
    int height = 0;
    int refresh = 0;
    while (fscanf(fp, "%255s %d %d %d", name, &width, &height, &refresh) == 4) {
        struct restore_entry *entry = calloc(1, sizeof(*entry));
        if (!entry) {
            continue;
        }
        entry->name = strdup(name);
        entry->width = width;
        entry->height = height;
        entry->refresh = refresh;
        wl_list_insert(&entries, &entry->link);
    }

    fclose(fp);
    return entries;
}

static struct restore_entry *find_restore_entry(struct wl_list *entries,
                                                const char *name) {
    struct restore_entry *entry = NULL;
    wl_list_for_each(entry, entries, link) {
        if (strcmp(entry->name, name) == 0) {
            return entry;
        }
    }
    return NULL;
}

static struct mode_info *find_mode(struct head_info *head, int32_t width,
                                   int32_t height, int32_t refresh) {
    struct mode_info *entry = NULL;
    wl_list_for_each(entry, &head->modes, link) {
        if (entry->width == width && entry->height == height &&
            entry->refresh == refresh) {
            return entry;
        }
    }
    return NULL;
}

static void free_restore_entries(struct wl_list *entries) {
    struct restore_entry *entry = NULL;
    struct restore_entry *tmp = NULL;
    wl_list_for_each_safe(entry, tmp, entries, link) {
        wl_list_remove(&entry->link);
        free(entry->name);
        free(entry);
    }
}

static int apply_fullscreen(struct client_state *state, const char *state_file) {
    if (state_file) {
        save_state(state_file, state);
    }

    struct zwlr_output_configuration_v1 *config =
        zwlr_output_manager_v1_create_configuration(state->manager, state->serial);

    struct head_info *head = NULL;
    wl_list_for_each(head, &state->heads, link) {
        struct mode_info *mode = select_fullscreen_mode(head);
        if (!mode) {
            continue;
        }
        struct zwlr_output_configuration_head_v1 *config_head =
            zwlr_output_configuration_v1_enable_head(config, head->obj);
        zwlr_output_configuration_head_v1_set_mode(config_head, mode->obj);
    }

    zwlr_output_configuration_v1_apply(config);
    zwlr_output_configuration_v1_destroy(config);
    wl_display_roundtrip(state->display);
    return 0;
}

static int apply_restore(struct client_state *state, const char *state_file) {
    if (!state_file) {
        fprintf(stderr, "--restore requires --state-file\n");
        return 1;
    }

    struct wl_list entries = load_state(state_file);
    if (wl_list_empty(&entries)) {
        fprintf(stderr, "No state entries found in %s\n", state_file);
        return 1;
    }

    struct zwlr_output_configuration_v1 *config =
        zwlr_output_manager_v1_create_configuration(state->manager, state->serial);

    struct head_info *head = NULL;
    wl_list_for_each(head, &state->heads, link) {
        if (!head->name) {
            continue;
        }
        struct restore_entry *entry = find_restore_entry(&entries, head->name);
        if (!entry) {
            continue;
        }
        struct mode_info *mode = find_mode(head, entry->width, entry->height,
                                           entry->refresh);
        if (!mode) {
            continue;
        }
        struct zwlr_output_configuration_head_v1 *config_head =
            zwlr_output_configuration_v1_enable_head(config, head->obj);
        zwlr_output_configuration_head_v1_set_mode(config_head, mode->obj);
    }

    zwlr_output_configuration_v1_apply(config);
    zwlr_output_configuration_v1_destroy(config);
    wl_display_roundtrip(state->display);
    free_restore_entries(&entries);
    return 0;
}

static void print_usage(const char *argv0) {
    fprintf(stderr,
            "Usage: %s --fullscreen|--restore --state-file <path>\n"
            "Options:\n"
            "  --fullscreen         switch outputs to preferred/max modes\n"
            "  --restore            restore modes from --state-file\n"
            "  --state-file <path>  file used to save/restore modes\n",
            argv0);
}

int main(int argc, char **argv) {
    bool do_fullscreen = false;
    bool do_restore = false;
    const char *state_file = NULL;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--fullscreen") == 0) {
            do_fullscreen = true;
        } else if (strcmp(argv[i], "--restore") == 0) {
            do_restore = true;
        } else if (strcmp(argv[i], "--state-file") == 0) {
            if (i + 1 >= argc) {
                print_usage(argv[0]);
                return 1;
            }
            state_file = argv[++i];
        } else {
            print_usage(argv[0]);
            return 1;
        }
    }

    if (do_fullscreen == do_restore) {
        print_usage(argv[0]);
        return 1;
    }

    struct client_state state = {0};
    wl_list_init(&state.heads);

    state.display = wl_display_connect(NULL);
    if (!state.display) {
        fprintf(stderr, "Failed to connect to Wayland display.\n");
        return 1;
    }

    state.registry = wl_display_get_registry(state.display);
    wl_registry_add_listener(state.registry, &registry_listener, &state);
    wl_display_roundtrip(state.display);

    if (!state.manager) {
        fprintf(stderr, "zwlr_output_manager_v1 not advertised by compositor.\n");
        return 1;
    }

    while (!state.done) {
        if (wl_display_roundtrip(state.display) < 0) {
            fprintf(stderr, "Wayland roundtrip failed.\n");
            return 1;
        }
    }

    int result = 0;
    if (do_fullscreen) {
        result = apply_fullscreen(&state, state_file);
    } else if (do_restore) {
        result = apply_restore(&state, state_file);
    }

    wl_display_disconnect(state.display);
    return result;
}
