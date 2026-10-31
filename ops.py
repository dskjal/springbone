import bpy
from bpy.props import IntProperty
from mathutils import Matrix

from . import driver, runtime


def _get_arm(context):
    obj = context.active_object
    if obj is None or obj.type != "ARMATURE":
        return None
    return obj


class SPRINGBONE_OT_add_chain(bpy.types.Operator):
    bl_idname = "springbone.add_chain"
    bl_label = "Add Chain from Selected Bones"
    bl_description = "Create a spring chain from the selected bones"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = _get_arm(context)
        return arm is not None and context.mode in {"EDIT", "POSE"}

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        if context.mode == "EDIT":
            bones = list(context.selected_editable_bones or [])

            def depth(bone):
                value = 0
                parent = bone.parent
                while parent is not None:
                    value += 1
                    parent = parent.parent
                return value

            bones.sort(key=depth)
            for previous, current in zip(bones, bones[1:]):
                parent = current.parent
                if parent is None or parent.name != previous.name:
                    self.report(
                        {"ERROR"},
                        f"{current.name} is not a direct child of {previous.name}",
                    )
                    return {"CANCELLED"}
            names = [bone.name for bone in bones]
        else:
            bones = list(context.selected_pose_bones or [])
            bones.sort(key=lambda bone: len(bone.bone.parent_recursive))
            for previous, current in zip(bones, bones[1:]):
                parent = current.bone.parent
                if parent is None or parent.name != previous.bone.name:
                    self.report(
                        {"ERROR"},
                        f"{current.name} is not a direct child of {previous.name}",
                    )
                    return {"CANCELLED"}
            names = [bone.name for bone in bones]

        if not names:
            self.report({"ERROR"}, "Select at least one bone")
            return {"CANCELLED"}

        settings = arm.springbone_settings
        chain = settings.chains.add()
        chain.name = f"Chain {len(settings.chains)}"
        for name in names:
            joint = chain.joints.add()
            joint.bone_name = name

        settings.active_chain = len(settings.chains) - 1
        self.report({"INFO"}, f"Added {len(names)} joints")
        return {"FINISHED"}


class SPRINGBONE_OT_remove_chain(bpy.types.Operator):
    bl_idname = "springbone.remove_chain"
    bl_label = "Remove Chain"
    bl_description = "Remove the active spring chain"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        arm = _get_arm(context)
        return arm is not None and len(arm.springbone_settings.chains) > 0

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        settings = arm.springbone_settings
        if not settings.chains:
            return {"CANCELLED"}

        if driver.is_running(arm):
            driver.stop(arm, reset=False)

        index = min(max(settings.active_chain, 0), len(settings.chains) - 1)
        settings.chains.remove(index)
        settings.active_chain = min(index, max(0, len(settings.chains) - 1))
        return {"FINISHED"}


class SPRINGBONE_OT_start_preview(bpy.types.Operator):
    bl_idname = "springbone.start_preview"
    bl_label = "Start Preview"
    bl_description = "Run the spring simulation without playing the timeline"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        arm = _get_arm(context)
        return arm is not None and arm.mode != "EDIT"

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        try:
            driver.start(arm)
        except runtime.ValidationError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        arm.springbone_settings.enabled = True

        arm_runtime = driver.get_runtime(arm)
        if arm_runtime is not None:
            for warning in arm_runtime.warnings:
                self.report({"WARNING"}, warning)

        if context.area is not None:
            context.area.tag_redraw()

        return {"FINISHED"}


class SPRINGBONE_OT_stop_preview(bpy.types.Operator):
    bl_idname = "springbone.stop_preview"
    bl_label = "Stop Preview"
    bl_description = "Stop the spring simulation"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        arm = _get_arm(context)
        return arm is not None and driver.is_running(arm)

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        driver.stop(arm)
        arm.springbone_settings.enabled = False
        return {"FINISHED"}


class SPRINGBONE_OT_bind(bpy.types.Operator):
    bl_idname = "springbone.bind"
    bl_label = "Rebind"
    bl_description = "Rebuild the rest data and simulation state"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        arm = _get_arm(context)
        return arm is not None and context.mode != "EDIT"

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        if not driver.is_running(arm):
            self.report({"INFO"}, "Preview is not running")
            return {"CANCELLED"}

        try:
            driver.rebind(arm)
        except runtime.ValidationError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}

        return {"FINISHED"}


class SPRINGBONE_OT_reset_pose(bpy.types.Operator):
    bl_idname = "springbone.reset_pose"
    bl_label = "Reset Pose"
    bl_description = "Restore the pose saved when the preview was bound"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _get_arm(context) is not None

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        if driver.is_running(arm):
            driver.reset_pose(arm)
        else:
            for chain in arm.springbone_settings.chains:
                for joint in chain.joints:
                    pose_bone = arm.pose.bones.get(joint.bone_name)
                    if pose_bone is not None:
                        pose_bone.matrix_basis = Matrix.Identity(4)
            arm.update_tag(refresh={"OBJECT"})

        return {"FINISHED"}


class SPRINGBONE_OT_bake_action(bpy.types.Operator):
    bl_idname = "springbone.bake_action"
    bl_label = "Bake Action"
    bl_description = "Bake the spring simulation to keyframes"
    bl_options = {"REGISTER", "UNDO"}

    frame_start: IntProperty(name="Start", default=-1)
    frame_end: IntProperty(name="End", default=-1)
    fps: IntProperty(name="FPS", default=0, min=0, max=240)

    @classmethod
    def poll(cls, context):
        arm = _get_arm(context)
        return arm is not None and arm.mode != "EDIT"

    def execute(self, context):
        arm = _get_arm(context)
        if arm is None:
            return {"CANCELLED"}

        scene = context.scene
        settings = arm.springbone_settings
        start = self.frame_start if self.frame_start >= 0 else scene.frame_start
        end = self.frame_end if self.frame_end >= 0 else scene.frame_end

        if end < start:
            self.report({"ERROR"}, "End frame is before start frame")
            return {"CANCELLED"}

        fps = self.fps
        if fps <= 0:
            base = scene.render.fps_base or 1.0
            fps = int(round(scene.render.fps / base))
        if fps <= 0:
            fps = 24

        if driver.is_running(arm):
            driver.stop(arm, reset=False)

        original_frame = scene.frame_current
        substeps = max(1, int(settings.substeps))

        try:
            scene.frame_set(start)
            arm_runtime = runtime.ArmatureRuntime(arm)
            arm_runtime.bind()

            for frame in range(start, end + 1):
                if frame != start:
                    scene.frame_set(frame)
                arm_runtime.step(1.0 / fps, substeps=substeps, force_eval=True)

                for chain in arm_runtime.chains:
                    for segment in chain.segments:
                        pose_bone = segment.pb
                        if pose_bone is None:
                            continue
                        if pose_bone.rotation_mode == "QUATERNION":
                            pose_bone.keyframe_insert(
                                "rotation_quaternion",
                                frame=frame,
                                group=pose_bone.name,
                            )
                        elif pose_bone.rotation_mode == "AXIS_ANGLE":
                            pose_bone.keyframe_insert(
                                "rotation_axis_angle",
                                frame=frame,
                                group=pose_bone.name,
                            )
                        else:
                            pose_bone.keyframe_insert(
                                "rotation_euler",
                                frame=frame,
                                group=pose_bone.name,
                            )
        except runtime.ValidationError as ex:
            self.report({"ERROR"}, str(ex))
            return {"CANCELLED"}
        finally:
            scene.frame_set(original_frame)
            settings.enabled = False

        self.report({"INFO"}, f"Baked frames {start} to {end}")
        return {"FINISHED"}


classes = (
    SPRINGBONE_OT_add_chain,
    SPRINGBONE_OT_remove_chain,
    SPRINGBONE_OT_start_preview,
    SPRINGBONE_OT_stop_preview,
    SPRINGBONE_OT_bind,
    SPRINGBONE_OT_reset_pose,
    SPRINGBONE_OT_bake_action,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
