import asyncio

import pytest

gi = pytest.importorskip("gi")

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk

from waydroid_helper.controller.app import window as window_module
from waydroid_helper.controller.widgets.components.skill_casting import SkillCasting


class DummyTask:
    def done(self) -> bool:
        return True

    def cancel(self) -> None:
        return None


class DummyServer:
    def __init__(self, host, port, event_bus):
        self.port = port
        self.server = None

    async def wait_started(self) -> None:
        return None

    async def close(self) -> None:
        return None


class DummyAdbHelper:
    async def connect(self) -> bool:
        return False

    async def get_screen_resolution(self):
        return None

    async def push_scrcpy_server(self) -> bool:
        return False

    async def generate_scid(self):
        return ("", "")

    async def reverse_tunnel(self, socket_name, port) -> bool:
        return False

    async def start_scrcpy_server(self, scid) -> bool:
        return False

    async def remove_reverse_tunnel(self) -> None:
        return None


@pytest.mark.skipif(Gdk.Display.get_default() is None, reason="No display available for GTK test")
def test_settings_window_keeps_edit_mode(monkeypatch):
    display = Gdk.Display.get_default()
    app = Gtk.Application(application_id="waydroid.helper.test")
    app.register(None)

    def dummy_create_task(coro):
        coro.close()
        return DummyTask()

    monkeypatch.setattr(window_module, "Server", DummyServer)
    monkeypatch.setattr(window_module, "AdbHelper", DummyAdbHelper)
    monkeypatch.setattr(window_module.asyncio, "create_task", dummy_create_task)

    async def noop_setup_scrcpy(self):
        return None

    monkeypatch.setattr(window_module.TransparentWindow, "setup_scrcpy", noop_setup_scrcpy)

    window = window_module.TransparentWindow(app, display.get_name())
    widget = SkillCasting(
        event_bus=window.event_bus,
        pointer_id_manager=window.pointer_id_manager,
        key_registry=window.key_registry,
    )
    window.create_widget_at_position(widget, 10, 10)

    assert window.current_mode == window.EDIT_MODE

    window.event_bus.emit(
        window_module.Event(
            window_module.EventType.SETTINGS_WIDGET,
            widget,
            False,
        )
    )

    assert window.active_settings_window is not None
    assert window.current_mode == window.EDIT_MODE

    assert window.switch_mode(window.MAPPING_MODE)
    assert window.current_mode == window.MAPPING_MODE

    window.close()
