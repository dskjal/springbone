import os
import sys
import time

import bpy
from mathutils import Quaternion

ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS_DIR = os.path.dirname(ADDON_ROOT)
if ADDONS_DIR not in sys.path:
    sys.path.insert(0, ADDONS_DIR)

import springbone
from springbone import driver


def build_armature():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    armature = bpy.data.armatures.new("TestArmature")
    obj = bpy.data.objects.new("TestArmature", armature)
    scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = armature.edit_bones

    root = edit_bones.new("Root")
    root.head = (0.0, 0.0, 0.0)
    root.tail = (0.0, 0.0, 1.0)

    previous = root
    for name, z in (("J1", 1.0), ("J2", 2.0), ("J3", 3.0), ("J4", 4.0)):
        bone = edit_bones.new(name)
        bone.head = (0.0, 0.0, z)
        bone.tail = (0.0, 0.0, z + 1.0)
        bone.parent = previous
        bone.use_connect = True
        previous = bone

    bpy.ops.object.mode_set(mode="POSE")
    return obj


def main():
    arm = build_armature()
    springbone.register()
    try:
        settings = arm.springbone_settings

        for name in ("J1", "J2", "J3", "J4"):
            arm.pose.bones[name].select = True
        bpy.context.view_layer.update()

        result = bpy.ops.springbone.add_chain()
        if result != {"FINISHED"}:
            raise RuntimeError(f"add_chain returned {result!r}")
        if len(settings.chains) != 1:
            raise RuntimeError("add_chain did not create a chain")

        chain = settings.chains[0]
        if len(chain.joints) != 4:
            raise RuntimeError("add_chain did not add four joints")

        for joint in chain.joints:
            joint.stiffness = 0.5
            joint.drag_force = 0.3
            joint.gravity_power = 0.0

        driver.start(arm)
        if not driver.is_running(arm):
            raise RuntimeError("driver did not start")
        if not bpy.app.timers.is_registered(driver._tick):
            raise RuntimeError("timer was not registered")

        arm_runtime = driver.get_runtime(arm)
        root = arm.pose.bones["Root"]
        root.rotation_mode = "QUATERNION"
        root.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), 0.6)

        before = arm_runtime.chains[0].segments[-1].cur_tail.copy()
        arm_runtime.last_time = time.perf_counter() - 0.1
        result = driver._tick()
        after = arm_runtime.chains[0].segments[-1].cur_tail

        if not isinstance(result, float):
            raise RuntimeError(f"tick returned {result!r}")
        if (after - before).length < 1e-6:
            raise RuntimeError("tick did not step the simulation")

        last_angle = arm.pose.bones["J4"].matrix_basis.to_quaternion().angle
        if last_angle < 1e-6:
            raise RuntimeError("last bone did not rotate")

        driver.stop(arm, reset=False)
        if driver.is_running(arm):
            raise RuntimeError("driver did not stop")
        if bpy.app.timers.is_registered(driver._tick):
            raise RuntimeError("timer was not unregistered")

        scene = bpy.context.scene
        original_frame = scene.frame_current
        result = bpy.ops.springbone.bake_action(frame_start=1, frame_end=3, fps=24)
        if result != {"FINISHED"}:
            raise RuntimeError(f"bake returned {result!r}")
        if arm.animation_data is None or arm.animation_data.action is None:
            raise RuntimeError("bake did not create an action")
        if scene.frame_current != original_frame:
            raise RuntimeError("bake did not restore the original frame")

        print("DRIVER OK")
    finally:
        springbone.unregister()


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"DRIVER FAILED: {ex}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
