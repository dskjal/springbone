import time
import traceback

import bpy
from bpy.app.handlers import persistent

from . import runtime

_ACTIVE = {}
_PLAYBACK_ACTIVE = False


def is_running(arm):
    try:
        return arm.session_uid in _ACTIVE
    except Exception:
        return False


def get_runtime(arm):
    try:
        return _ACTIVE.get(arm.session_uid)
    except Exception:
        return None


def start(arm):
    if is_running(arm):
        return
    arm_runtime = runtime.ArmatureRuntime(arm)
    arm_runtime.bind()
    _ACTIVE[arm_runtime.arm_uid] = arm_runtime
    _ensure_timer()


def stop(arm, reset=None):
    try:
        key = arm.session_uid
    except Exception:
        return

    arm_runtime = _ACTIVE.pop(key, None)
    if arm_runtime is None:
        return

    if reset is None:
        try:
            reset = arm_runtime.settings.reset_on_stop
        except Exception:
            reset = False

    if reset:
        try:
            arm_runtime.reset_pose()
        except Exception:
            traceback.print_exc()

    if not _ACTIVE:
        _stop_timer()


def stop_all(reset=False):
    if reset:
        for arm_runtime in list(_ACTIVE.values()):
            try:
                arm_runtime.reset_pose()
            except Exception:
                traceback.print_exc()
    _ACTIVE.clear()
    _stop_timer()


def reset_pose(arm):
    arm_runtime = get_runtime(arm)
    if arm_runtime is not None:
        arm_runtime.reset_pose()


def rebind(arm):
    arm_runtime = get_runtime(arm)
    if arm_runtime is None:
        raise runtime.ValidationError("Preview is not running")
    arm_runtime.bind()


def active_count():
    return len(_ACTIVE)


def _interval():
    hz = 60
    if _ACTIVE:
        try:
            hz = max(10, max(int(arm_runtime.settings.update_hz) for arm_runtime in _ACTIVE.values()))
        except Exception:
            hz = 60
    return max(1.0 / 240.0, 1.0 / hz)


def _ensure_timer():
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.0, persistent=True)


def _stop_timer():
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)


def _redraw_view3d(window_manager):
    for window in window_manager.windows:
        screen = window.screen
        if screen is None:
            continue
        for area in screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _tick():
    if not _ACTIVE:
        return None

    try:
        window_manager = bpy.context.window_manager
        if window_manager is None or getattr(window_manager, "is_interface_locked", False):
            return _interval()
        if _PLAYBACK_ACTIVE:
            return _interval()

        now = time.perf_counter()
        updated = False
        stale = []

        for key, arm_runtime in list(_ACTIVE.items()):
            try:
                if not arm_runtime.is_alive():
                    stale.append(key)
                    continue
                if arm_runtime.tick(now):
                    updated = True
            except Exception:
                traceback.print_exc()
                stale.append(key)

        for key in stale:
            _ACTIVE.pop(key, None)

        if not _ACTIVE:
            return None

        if updated:
            _redraw_view3d(window_manager)

        return _interval()
    except Exception:
        traceback.print_exc()
        return _interval() if _ACTIVE else None


@persistent
def _on_playback_pre(scene, depsgraph=None):
    global _PLAYBACK_ACTIVE
    _PLAYBACK_ACTIVE = True


@persistent
def _on_playback_post(scene, depsgraph=None):
    global _PLAYBACK_ACTIVE
    _PLAYBACK_ACTIVE = False
    now = time.perf_counter()
    for arm_runtime in _ACTIVE.values():
        arm_runtime.last_time = now
        arm_runtime.accumulator = 0.0


@persistent
def _on_load_post(filepath):
    stop_all(reset=False)


@persistent
def _on_undo_post(scene):
    stop_all(reset=False)


@persistent
def _on_redo_post(scene):
    stop_all(reset=False)


_HANDLERS = (
    ("animation_playback_pre", _on_playback_pre),
    ("animation_playback_post", _on_playback_post),
    ("load_post", _on_load_post),
    ("undo_post", _on_undo_post),
    ("redo_post", _on_redo_post),
)


def register_handlers():
    for name, handler in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if handler not in handlers:
            handlers.append(handler)


def unregister_handlers():
    for name, handler in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if handler in handlers:
            handlers.remove(handler)
