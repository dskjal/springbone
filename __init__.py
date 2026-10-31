bl_info = {
    "name": "SpringBone Preview",
    "author": "springbone",
    "version": (0, 1, 0),
    "blender": (5, 3, 0),
    "location": "View3D > Sidebar > SpringBone",
    "description": "Timeline-independent spring bone preview",
    "category": "Rigging",
}

if "props" in locals():
    import importlib

    importlib.reload(props)
    importlib.reload(runtime)
    importlib.reload(driver)
    importlib.reload(ops)
    importlib.reload(ui)
else:
    from . import driver, ops, props, runtime, ui


def register():
    props.register()
    ops.register()
    ui.register()
    driver.register_handlers()


def unregister():
    driver.stop_all(reset=False)
    driver.unregister_handlers()
    ui.unregister()
    ops.unregister()
    props.unregister()
