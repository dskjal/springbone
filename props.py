import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)


class SpringJoint(bpy.types.PropertyGroup):
    bone_name: StringProperty(name="Bone")
    hit_radius: FloatProperty(name="Hit Radius", default=0.02, min=0.0, unit="LENGTH")
    stiffness: FloatProperty(name="Stiffness", default=1.0, min=0.0)
    gravity_power: FloatProperty(name="Gravity Power", default=0.0)
    gravity_dir: FloatVectorProperty(
        name="Gravity Direction",
        default=(0.0, 0.0, -1.0),
        subtype="DIRECTION",
    )
    drag_force: FloatProperty(name="Drag Force", default=0.4, min=0.0, max=1.0)


class SpringChain(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", default="Chain")
    center_bone: StringProperty(name="Center Bone")
    joints: CollectionProperty(type=SpringJoint)


class SpringBoneSettings(bpy.types.PropertyGroup):
    enabled: BoolProperty(name="Enabled", default=False)
    update_hz: IntProperty(name="Update Hz", default=60, min=10, max=240)
    substeps: IntProperty(name="Substeps", default=1, min=1, max=8)
    max_dt: FloatProperty(name="Max dt", default=0.1, min=0.001, max=0.5)
    use_evaluated_parents: BoolProperty(name="Use Evaluated Parents", default=True)
    reset_on_stop: BoolProperty(name="Reset Pose on Stop", default=True)
    chains: CollectionProperty(type=SpringChain)
    active_chain: IntProperty(default=0)


classes = (SpringJoint, SpringChain, SpringBoneSettings)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.springbone_settings = PointerProperty(type=SpringBoneSettings)


def unregister():
    del bpy.types.Object.springbone_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
