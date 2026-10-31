import time

import bpy
from mathutils import Matrix, Quaternion, Vector


class ValidationError(Exception):
    pass


def _pose_from_basis(pb):
    if pb is None:
        return Matrix.Identity(4)
    if pb.parent is not None:
        parent_matrix = _pose_from_basis(pb.parent)
        return pb.bone.convert_local_to_pose(
            pb.matrix_basis,
            pb.bone.matrix_local,
            parent_matrix=parent_matrix,
            parent_matrix_local=pb.parent.bone.matrix_local,
        )
    return pb.bone.convert_local_to_pose(pb.matrix_basis, pb.bone.matrix_local)


class Segment:
    __slots__ = (
        "joint",
        "pb",
        "bone",
        "parent_bone",
        "R",
        "P",
        "axis",
        "length",
        "prev_tail",
        "cur_tail",
        "q",
        "bnew",
        "mparent",
        "drag",
        "stiffness",
        "gravity_power",
        "gravity_dir",
    )

    def __init__(self, joint, pb, bone, parent_bone, R, P, axis, length):
        self.joint = joint
        self.pb = pb
        self.bone = bone
        self.parent_bone = parent_bone
        self.R = R
        self.P = P
        self.axis = axis
        self.length = length
        self.prev_tail = Vector((0.0, 0.0, 0.0))
        self.cur_tail = Vector((0.0, 0.0, 0.0))
        self.q = Quaternion()
        self.bnew = Matrix.Identity(4)
        self.mparent = Matrix.Identity(4)
        self.drag = 0.4
        self.stiffness = 1.0
        self.gravity_power = 0.0
        self.gravity_dir = Vector((0.0, 0.0, -1.0))


class ChainRuntime:
    def __init__(self, arm, chain):
        self.arm = arm
        self.chain = chain
        self.segments = []
        self.first_parent_name = None
        self.parent_has_constraints = False
        self.valid = False
        self.error = ""
        self.warnings = []
        self._parent = Matrix.Identity(4)
        self._build()

    def _build(self):
        self.segments = []
        self.valid = False
        self.error = ""
        self.warnings = []
        self.first_parent_name = None
        self.parent_has_constraints = False

        joints = list(self.chain.joints)
        if not joints:
            self.error = "At least one joint is required"
            return

        names = [joint.bone_name for joint in joints]
        if any(not name for name in names):
            self.error = "Every joint needs a bone name"
            return

        bones = []
        for name in names:
            bone = self.arm.data.bones.get(name)
            if bone is None:
                self.error = f"Bone not found: {name}"
                return
            bones.append(bone)

        for index in range(len(bones) - 1):
            parent = bones[index + 1].parent
            if parent is None or parent.name != bones[index].name:
                self.error = f"{names[index + 1]} is not a direct child of {names[index]}"
                return

        for index, bone in enumerate(bones):
            pose_bone = self.arm.pose.bones.get(bone.name)
            if pose_bone is None:
                self.error = f"Pose bone not found: {bone.name}"
                return

            rest = bone.matrix_local.copy()
            if bone.parent is not None:
                parent_rest = bone.parent.matrix_local.copy()
            else:
                parent_rest = Matrix.Identity(4)

            if index + 1 < len(bones):
                next_bone = bones[index + 1]
                offset = (rest.inverted() @ next_bone.matrix_local).to_translation()
            else:
                offset = rest.inverted() @ bone.tail_local

            length = offset.length
            if length < 1e-6:
                self.error = f"Zero length segment: {bone.name}"
                return

            self.segments.append(
                Segment(
                    joints[index],
                    pose_bone,
                    bone,
                    bone.parent,
                    rest,
                    parent_rest,
                    offset / length,
                    length,
                )
            )

        first_bone = bones[0]
        if first_bone.parent is not None:
            self.first_parent_name = first_bone.parent.name
            self.parent_has_constraints = self._ancestor_has_constraints(first_bone)

        if any(len(segment.pb.constraints) > 0 for segment in self.segments):
            self.warnings.append("Spring bones have constraints; the displayed pose may differ")

        scale = self.arm.matrix_world.to_scale()
        if max(scale) - min(scale) > 1e-4:
            self.warnings.append("Non-uniform armature scale distorts the spring length")

        self.valid = True

    def _ancestor_has_constraints(self, bone):
        current = bone.parent
        while current is not None:
            pose_bone = self.arm.pose.bones.get(current.name)
            if pose_bone is not None and len(pose_bone.constraints) > 0:
                return True
            current = current.parent
        return False

    def _get_parent_matrix(self, force_eval):
        if self.first_parent_name is None:
            return Matrix.Identity(4)

        use_eval = force_eval
        if not use_eval:
            try:
                use_eval = self.arm.springbone_settings.use_evaluated_parents and (
                    self.arm.animation_data is not None or self.parent_has_constraints
                )
            except Exception:
                use_eval = False

        if use_eval:
            try:
                depsgraph = bpy.context.evaluated_depsgraph_get()
                eval_arm = self.arm.evaluated_get(depsgraph)
                pose_bone = eval_arm.pose.bones.get(self.first_parent_name)
                if pose_bone is not None:
                    return pose_bone.matrix.copy()
            except Exception:
                pass

        pose_bone = self.arm.pose.bones.get(self.first_parent_name)
        if pose_bone is None:
            return Matrix.Identity(4)
        return _pose_from_basis(pose_bone)

    def bind(self):
        arm_world = self.arm.matrix_world.copy()
        parent_matrix = self._get_parent_matrix(force_eval=True)

        for segment in self.segments:
            if segment.parent_bone is not None:
                base = segment.bone.convert_local_to_pose(
                    Matrix.Identity(4),
                    segment.R,
                    parent_matrix=parent_matrix,
                    parent_matrix_local=segment.P,
                )
            else:
                base = segment.bone.convert_local_to_pose(Matrix.Identity(4), segment.R)

            world = arm_world @ base
            head = world.to_translation()
            rotation = world.to_3x3()
            rest_dir = (rotation @ segment.axis).normalized()
            world_length = (rotation @ (segment.axis * segment.length)).length

            tail = head + rest_dir * world_length
            segment.prev_tail = tail.copy()
            segment.cur_tail = tail.copy()
            segment.q = Quaternion()
            segment.bnew = base
            segment.mparent = parent_matrix
            parent_matrix = base

    def prepare(self, force_eval):
        self._parent = self._get_parent_matrix(force_eval)

    def cache_params(self):
        for segment in self.segments:
            joint = segment.joint
            segment.drag = float(joint.drag_force)
            segment.stiffness = float(joint.stiffness)
            segment.gravity_power = float(joint.gravity_power)
            segment.gravity_dir = Vector(joint.gravity_dir)

    def substep(self, dt, arm_world):
        parent_matrix = self._parent
        a3_inv = arm_world.to_3x3().inverted()

        for segment in self.segments:
            if segment.parent_bone is not None:
                base = segment.bone.convert_local_to_pose(
                    Matrix.Identity(4),
                    segment.R,
                    parent_matrix=parent_matrix,
                    parent_matrix_local=segment.P,
                )
            else:
                base = segment.bone.convert_local_to_pose(Matrix.Identity(4), segment.R)

            world = arm_world @ base
            head = world.to_translation()
            rotation = world.to_3x3()

            rest_dir = rotation @ segment.axis
            if rest_dir.length_squared > 0.0:
                rest_dir.normalize()

            world_length = (rotation @ (segment.axis * segment.length)).length

            current = segment.cur_tail
            previous = segment.prev_tail
            inertia = (current - previous) * (1.0 - segment.drag)
            stiffness = rest_dir * (segment.stiffness * dt)
            external = segment.gravity_dir * (segment.gravity_power * dt)

            next_tail = current + inertia + stiffness + external
            delta = next_tail - head
            if delta.length_squared < 1e-12:
                next_tail = head + rest_dir * world_length
            else:
                next_tail = head + delta.normalized() * world_length

            segment.prev_tail = current
            segment.cur_tail = next_tail

            direction = next_tail - head
            if direction.length_squared < 1e-12:
                direction = rest_dir
            else:
                direction.normalize()

            local = rotation.inverted() @ (a3_inv @ direction)
            if local.length_squared < 1e-12:
                local = segment.axis
            else:
                local.normalize()

            q = segment.axis.rotation_difference(local)
            if segment.parent_bone is not None:
                new_pose = segment.bone.convert_local_to_pose(
                    q.to_matrix().to_4x4(),
                    segment.R,
                    parent_matrix=parent_matrix,
                    parent_matrix_local=segment.P,
                )
            else:
                new_pose = segment.bone.convert_local_to_pose(
                    q.to_matrix().to_4x4(),
                    segment.R,
                )

            segment.q = q
            segment.bnew = new_pose
            segment.mparent = parent_matrix
            parent_matrix = new_pose

    def apply(self):
        for segment in self.segments:
            if segment.pb is None:
                continue
            segment.pb.matrix_basis = segment.q.to_matrix().to_4x4()


class ArmatureRuntime:
    def __init__(self, arm):
        self.arm = arm
        self.settings = arm.springbone_settings
        self.arm_uid = arm.session_uid
        self.chains = []
        self.bind_basis = []
        self.warnings = []
        self.bound = False
        self.last_time = time.perf_counter()
        self.accumulator = 0.0
        self._was_edit = False

    def bind(self):
        chains = []
        seen = set()

        for chain in self.settings.chains:
            chain_runtime = ChainRuntime(self.arm, chain)
            if not chain_runtime.valid:
                raise ValidationError(f"{chain.name}: {chain_runtime.error}")
            for joint in chain.joints:
                if joint.bone_name in seen:
                    raise ValidationError(f"Duplicate joint bone: {joint.bone_name}")
                seen.add(joint.bone_name)
            chains.append(chain_runtime)

        if not chains:
            raise ValidationError("No spring chains")

        self.chains = chains
        self.warnings = [
            f"{chain_runtime.chain.name}: {warning}"
            for chain_runtime in chains
            for warning in chain_runtime.warnings
        ]

        self.bind_basis = []
        for name in seen:
            pose_bone = self.arm.pose.bones.get(name)
            if pose_bone is not None:
                self.bind_basis.append((name, pose_bone.matrix_basis.copy()))

        for chain_runtime in self.chains:
            chain_runtime.bind()

        self.bound = True
        self.last_time = time.perf_counter()
        self.accumulator = 0.0
        self._was_edit = False

    def _cache_params(self):
        for chain_runtime in self.chains:
            chain_runtime.cache_params()

    def _prepare(self, force_eval):
        for chain_runtime in self.chains:
            chain_runtime.prepare(force_eval)

    def _apply(self):
        for chain_runtime in self.chains:
            chain_runtime.apply()
        self.arm.update_tag(refresh={"OBJECT"})

    def step(self, dt, substeps=None, force_eval=False):
        if not self.bound:
            self.bind()

        count = max(1, int(self.settings.substeps if substeps is None else substeps))
        dt = max(0.0, float(dt))
        if dt <= 0.0:
            return

        h = dt / count
        if h <= 0.0:
            return

        self._cache_params()
        arm_world = self.arm.matrix_world.copy()
        self._prepare(force_eval)

        for _ in range(count):
            for chain_runtime in self.chains:
                chain_runtime.substep(h, arm_world)

        self._apply()

    def tick(self, now, force_eval=False):
        if not self.bound:
            self.bind()

        if self.arm.mode == "EDIT":
            self._was_edit = True
            self.last_time = now
            return False

        if self._was_edit:
            self._was_edit = False
            self.bind()

        dt = now - self.last_time
        self.last_time = now
        if dt <= 0.0:
            return False

        dt = min(dt, self.settings.max_dt)
        self.accumulator += dt

        hz = max(10, int(self.settings.update_hz))
        substeps = max(1, int(self.settings.substeps))
        h = 1.0 / (hz * substeps)
        max_steps = substeps * 4

        self._cache_params()
        arm_world = self.arm.matrix_world.copy()
        self._prepare(force_eval)

        steps = 0
        while self.accumulator >= h and steps < max_steps:
            self.accumulator -= h
            steps += 1
            for chain_runtime in self.chains:
                chain_runtime.substep(h, arm_world)

        if steps >= max_steps:
            self.accumulator = 0.0

        if steps == 0:
            return False

        self._apply()
        return True

    def reset_pose(self):
        for name, basis in self.bind_basis:
            pose_bone = self.arm.pose.bones.get(name)
            if pose_bone is not None:
                pose_bone.matrix_basis = basis

        self.arm.update_tag(refresh={"OBJECT"})

        if self.bound:
            for chain_runtime in self.chains:
                chain_runtime.bind()

        self.last_time = time.perf_counter()
        self.accumulator = 0.0

    def is_alive(self):
        try:
            if self.arm.name not in bpy.data.objects:
                return False
            if self.arm.session_uid != self.arm_uid:
                return False
            return True
        except Exception:
            return False
