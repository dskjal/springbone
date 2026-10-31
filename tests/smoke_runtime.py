import math
import os
import sys

import bpy
from mathutils import Quaternion

ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS_DIR = os.path.dirname(ADDON_ROOT)
if ADDONS_DIR not in sys.path:
    sys.path.insert(0, ADDONS_DIR)

import springbone


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
    z = 1.0
    for name, length in (("J1", 0.7), ("J2", 0.8), ("J3", 0.9)):
        bone = edit_bones.new(name)
        bone.head = (0.0, 0.0, z)
        z += length
        bone.tail = (0.0, 0.0, z)
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
        chain = settings.chains.add()
        chain.name = "Test"

        for name in ("J1", "J2", "J3"):
            joint = chain.joints.add()
            joint.bone_name = name
            joint.stiffness = 0.5
            joint.drag_force = 0.3
            joint.gravity_power = 0.0

        arm_runtime = springbone.runtime.ArmatureRuntime(arm)
        arm_runtime.bind()

        if len(arm_runtime.chains) != 1:
            raise RuntimeError("Expected one chain")
        if len(arm_runtime.chains[0].segments) != 3:
            raise RuntimeError("Expected three segments")

        frame_before = bpy.context.scene.frame_current
        tip_before = arm_runtime.chains[0].segments[-1].cur_tail.copy()

        root = arm.pose.bones["Root"]
        root.rotation_mode = "QUATERNION"
        root.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), 0.6)

        for _ in range(120):
            arm_runtime.step(1.0 / 60.0, force_eval=True)

        tip_after = arm_runtime.chains[0].segments[-1].cur_tail
        if not all(math.isfinite(value) for value in tip_after):
            raise RuntimeError(f"Non-finite tip: {tuple(tip_after)}")
        if (tip_after - tip_before).length < 1e-4:
            raise RuntimeError("Tip did not move")
        if bpy.context.scene.frame_current != frame_before:
            raise RuntimeError("Timeline frame changed")

        last_angle = arm.pose.bones["J3"].matrix_basis.to_quaternion().angle
        if last_angle < 1e-6:
            raise RuntimeError("Last bone did not rotate")

        print(f"SMOKE OK last_angle={last_angle:.6f}")
    finally:
        springbone.unregister()


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"SMOKE FAILED: {ex}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
