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

arm = None
before = None
checks = 0


def build_armature():
    scene = bpy.context.scene
    for existing in list(bpy.data.objects):
        bpy.data.objects.remove(existing, do_unlink=True)
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


def check():
    global checks
    checks += 1
    scene = bpy.context.scene
    arm_runtime = driver.get_runtime(arm)

    if arm_runtime is None:
        print("GUI FAILED: runtime missing")
        bpy.ops.wm.quit_blender()
        return None

    if checks < 20:
        return 0.1

    tip = arm_runtime.chains[0].segments[-1].cur_tail
    moved = (tip - before).length
    pose_angle = arm.pose.bones["J1"].matrix_basis.to_quaternion().angle
    last_angle = arm.pose.bones["J4"].matrix_basis.to_quaternion().angle

    if scene.frame_current != 1:
        print(f"GUI FAILED: frame moved to {scene.frame_current}")
    elif moved < 1e-4:
        print(f"GUI FAILED: tip did not move ({moved:.8f})")
    elif pose_angle < 1e-4:
        print(f"GUI FAILED: pose was not written ({pose_angle:.8f})")
    elif last_angle < 1e-6:
        print(f"GUI FAILED: last bone was not written ({last_angle:.8f})")
    else:
        print(
            f"GUI OK frame={scene.frame_current} moved={moved:.6f} "
            f"pose={pose_angle:.6f} last={last_angle:.6f}"
        )

    bpy.ops.wm.quit_blender()
    return None


def main():
    global arm, before

    arm = build_armature()
    springbone.register()

    settings = arm.springbone_settings
    chain = settings.chains.add()
    chain.name = "Test"

    for name in ("J1", "J2", "J3", "J4"):
        joint = chain.joints.add()
        joint.bone_name = name
        joint.stiffness = 0.5
        joint.drag_force = 0.3
        joint.gravity_power = 0.0

    driver.start(arm)
    arm_runtime = driver.get_runtime(arm)
    before = arm_runtime.chains[0].segments[-1].cur_tail.copy()

    root = arm.pose.bones["Root"]
    root.rotation_mode = "QUATERNION"
    root.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), 0.6)

    bpy.app.timers.register(check, first_interval=0.1, persistent=True)


try:
    main()
except Exception as ex:
    print(f"GUI SETUP FAILED: {ex}")
    import traceback

    traceback.print_exc()
    try:
        bpy.ops.wm.quit_blender()
    except Exception:
        os._exit(1)
