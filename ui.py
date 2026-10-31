import bpy

from . import driver


class SPRINGBONE_UL_chains(bpy.types.UIList):
    def draw_item(
        self,
        context,
        layout,
        data,
        item,
        icon,
        active_data,
        active_propname,
        index,
    ):
        row = layout.row(align=True)
        row.prop(item, "name", text="", emboss=False, icon="BONE_DATA")
        row.label(text=f"{len(item.joints)}")


class SPRINGBONE_PT_main(bpy.types.Panel):
    bl_label = "SpringBone Preview"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "SpringBone"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "ARMATURE"

    def draw(self, context):
        layout = self.layout
        arm = context.active_object
        settings = arm.springbone_settings
        running = driver.is_running(arm)

        box = layout.box()
        row = box.row()
        row.label(
            text="Running" if running else "Stopped",
            icon="PLAY" if running else "PAUSE",
        )
        row.label(text=f"Frame {context.scene.frame_current}")

        row = box.row(align=True)
        row.operator("springbone.start_preview", text="Start", icon="PLAY")
        row.operator("springbone.stop_preview", text="Stop", icon="PAUSE")

        row = box.row(align=True)
        row.operator("springbone.add_chain", text="Add Selected Chain", icon="ADD")
        row.operator("springbone.bind", text="Rebind", icon="FILE_REFRESH")
        row.operator("springbone.reset_pose", text="Reset Pose", icon="LOOP_BACK")

        box.operator("springbone.bake_action", text="Bake Action", icon="REC")
        box.prop(settings, "update_hz")
        box.prop(settings, "substeps")
        box.prop(settings, "use_evaluated_parents")
        box.prop(settings, "reset_on_stop")

        layout.label(text=f"Chains: {len(settings.chains)}")
        row = layout.row()
        row.template_list(
            "SPRINGBONE_UL_chains",
            "",
            settings,
            "chains",
            settings,
            "active_chain",
            rows=3,
        )
        column = row.column(align=True)
        column.operator("springbone.add_chain", text="", icon="ADD")
        column.operator("springbone.remove_chain", text="", icon="REMOVE")

        if settings.chains:
            index = min(max(settings.active_chain, 0), len(settings.chains) - 1)
            chain = settings.chains[index]
            box = layout.box()
            box.prop(chain, "name")
            box.prop(chain, "center_bone")

            for joint_index, joint in enumerate(chain.joints):
                sub = box.box()
                sub.label(text=f"{joint_index + 1}. {joint.bone_name or '<none>'}")
                sub.prop(joint, "stiffness")
                sub.prop(joint, "drag_force")
                sub.prop(joint, "gravity_power")
                sub.prop(joint, "gravity_dir")
                sub.prop(joint, "hit_radius")


classes = (SPRINGBONE_UL_chains, SPRINGBONE_PT_main)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
