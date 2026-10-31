# SpringBone Viewport Runtime Investigation

Target: Blender 5.3 / `bpy` Python API

## Conclusion

The only practical way to move bones in the viewport without playing the timeline is to
**use `bpy.app.timers` as the simulation clock**.

1. Advance `dt` every frame in the timer callback.
2. Manually propagate pose matrices from parent to child with `Bone.convert_local_to_pose`.
3. Write only the final result back to `PoseBone.matrix_basis`.
4. Refresh the viewport with `ID.update_tag` + `Area.tag_redraw()`.
5. Never touch `scene.frame_current`.

`frame_change_pre/post`, Geometry Nodes Simulation Zones, and the standard physics systems
all assume that "the frame advances", so they cannot be used for this requirement.

## 1. Why a clock other than frames is needed

Blender's animation evaluation is handled by the depsgraph, and physics simulations
(Rigid Body / Cloth / Soft Body / GN Simulation Zone) step when the frame changes. Under the
condition that the timeline is neither played nor scrubbed, these callbacks are never
called.

Therefore the add-on must carry its own mechanism driven by a wall clock
(`time.perf_counter()`). `bpy.app.timers` runs on Blender's main loop, so it is called
periodically on the main thread even without UI events.

## 2. Comparison of approaches

| Approach | No playback needed | Always driven | Issues | Verdict |
|---|---|---|---|---|
| `bpy.app.timers` | Yes | Yes | No timing guarantee. `is_interface_locked` guard required | **Adopted** |
| Modal operator + `event_timer_add` | Yes | Partial | Stops during other modal operations. Window-dependent | Rejected |
| `depsgraph_update_post` | Partial | No | Only on changes. Recursion from own writes | Auxiliary only |
| `frame_change_pre/post` | No | No | Frame change required | Rejected |
| GN Simulation Zone | No | No | Advances only on frame evaluation | Rejected |
| Driver | No | No | Requires an evaluation trigger | Rejected |
| `SpaceView3D.draw_handler_add` | Yes | No | Draw only. Cannot modify data | Debugging only |
| Standard physics | No | No | Cache is frame-dependent | Rejected |

### Why modal operators are rejected

`WindowManager.event_timer_add` + `modal_handler_add` can receive TIMER events, but
Blender's modal handlers are limited to one per window. Transforms such as move, rotate,
and scale are also modal operators, so the preview stops the moment the user grabs a bone.
It is not suitable for continuous preview.

### Why `depsgraph_update_post` is rejected

It is called only when data changes. It does not fire while nothing is being operated, so it
cannot serve as a clock. In addition, rewriting the pose inside the callback updates the
depsgraph again, which risks recursion and infinite loops.

## 3. Adopted architecture

```
timer tick (main thread)
  ├─ wm.is_interface_locked / playing back / no targets → schedule next
  ├─ per runtime
  │    ├─ dt = clamp(perf_counter - last, 0, max_dt)
  │    ├─ fetch parent pose (evaluated or matrix_basis)
  │    ├─ fixed substeps: verlet → length constraint → (future: colliders)
  │    └─ write only the final result back to matrix_basis
  ├─ arm.update_tag(refresh={'OBJECT'})
  └─ Area.tag_redraw() for all VIEW_3D areas
```

- Do not read Blender data during substeps. Matrix math is self-contained.
- Do not call `view_layer.update()` per bone. Call it at most once per tick.
- Run the simulation in world space, so that inertia appears when the object moves.
- Compute bone matrices in armature space, and convert only the head position and rest
  direction to world space with `arm.matrix_world`.

## 4. Basis in the Blender 5.3 API

### Timers

https://docs.blender.org/api/5.3/bpy.app.timers.html

> Add a new function that will be called after the specified amount of seconds.
> The function gets no arguments and is expected to return either None or a float.
> If `None` is returned, the timer will be unregistered.
> A returned number specifies the delay until the function is called again.

```python
def tick():
    ...
    return 1.0 / 60.0

bpy.app.timers.register(tick, first_interval=0.0, persistent=True)
```

`persistent=True` keeps the timer alive across file loads. Use `is_registered(tick)` /
`unregister(tick)` to handle duplicate registration and removal. Because `persistent=True`
leaves stale object references after a load, unregister and clear in `load_post`.

### Interface lock

https://docs.blender.org/api/5.3/bpy.types.WindowManager.html#bpy.types.WindowManager.is_interface_locked

> If true, the interface is currently locked by a running job and data should not be
> modified from application timers. Otherwise, the running job might conflict with the
> handler causing unexpected results or even crashes.

Always check this at the start of a tick; if true, touch no data and only schedule the next
call.

### Manual pose matrix propagation

https://docs.blender.org/api/5.3/bpy.types.Bone.html#bpy.types.Bone.convert_local_to_pose

> This method enables conversions between Local and Pose space for bones in the middle of
> updating the armature without having to update dependencies after each change,
> by manually carrying updated matrices in a recursive walk.

Pass `parent_matrix` / `parent_matrix_local`, and convert back to local with `invert=True`.
This avoids calling `bpy.context.view_layer.update()` for each bone.

### Pose data

- `PoseBone.matrix_basis`:
  > Alternative access to location/scale/rotation relative to the parent and own rest bone
- `PoseBone.matrix`:
  > Final 4×4 matrix after constraints and drivers are applied, in the armature object space
- `Bone.matrix_local`:
  > 4×4 bone matrix relative to armature

`matrix_basis` is the simulation's write target. `matrix` is for reading evaluated results.

### Display refresh

- `ID.update_tag(*, refresh=set())`:
  > Tag the ID to update its display data, e.g. when calling `ViewLayer.update`
- `ViewLayer.update()`:
  > Update data tagged to be updated from previous access to data or operators
- `Area.tag_redraw()`:
  https://docs.blender.org/api/5.3/bpy.types.Area.html#bpy.types.Area.tag_redraw

After rewriting `matrix_basis`, call `arm.update_tag(refresh={'OBJECT'})` and
`tag_redraw()` on every `VIEW_3D` area.

### Evaluated pose

https://docs.blender.org/api/5.3/bpy.types.Depsgraph.html

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
arm_eval = arm.evaluated_get(depsgraph)
parent_matrix = arm_eval.pose.bones[parent_name].matrix.copy()
```

When the parent bone has animation or constraints, use the evaluated matrix.
`ID.evaluated_get()` "only returns the last evaluated result and does not guarantee
evaluation", so always pair it with `evaluated_depsgraph_get()`.

### Playback handlers

- `bpy.app.handlers.animation_playback_pre`
- `bpy.app.handlers.animation_playback_post`

Stop live updates when playback starts, and reset the clock when it ends. `frame_change_*`
is called from another thread during rendering and can crash when data is modified
(the official docs' Note on Altering Data). Do not use it for preview.

### Modal APIs (for comparison)

- `WindowManager.event_timer_add(time_step, *, window=None)`
- `WindowManager.modal_handler_add(operator)`

Template: `5.3/scripts/templates_py/Operator/modal_timer.py`

### Debugging

`SpaceView3D.draw_handler_add(callback, args, 'WINDOW', 'POST_VIEW')` is for drawing only.
It can visualize chain lines and collider spheres, but it does not become the simulation
clock.

## 5. Mapping SpringBone to Blender

### Precomputation

Segment j (head of joint j → head of the next joint):

```
R_j  = bone_j.matrix_local                       # armature rest
P_j  = parent(bone_j).matrix_local or Identity
v_j  = (R_j^-1 @ bone_{j+1}.matrix_local).translation
axis_j = v_j.normalized()
len_j  = v_j.length
```

The tail bone (j = N-1, which has no next joint) uses its own tail as the endpoint:

```
v_j = R_j^-1 @ bone_j.tail_local
```

This produces N segments for an N-bone chain, and the tail bone also rotates. `len_j` is
always computed from the actual bone length, so it works with bones of any length. In the
VRMC spec the tail joint is tail-only, but Blender bones have their own tail, so it is
treated as a sentinel. The tail joint's `stiffness` / `drag` / `gravity` are also active.

`axis_j` is the direction, in the bone-local space of joint j, pointing at the next joint's
head (or at its own tail). For a direct parent-child with `use_connect=True`, this becomes
`(0, 1, 0)` and the bone length.

### Per step

```
A     = arm.matrix_world
Mpar  = actual parent bone pose matrix (armature space)
B     = bone_j.convert_local_to_pose(Identity, R_j,
            parent_matrix=Mpar, parent_matrix_local=P_j)
W     = A @ B
head  = W.translation
d0    = normalize(W.to_3x3() @ axis_j)
l     = |W.to_3x3() @ (axis_j * len_j)|

inertia = (cur - prev) * (1 - drag)
stiff   = d0 * (stiffness * dt)
ext     = gravity_world * (gravity_power * dt)
nxt     = cur + inertia + stiff + ext
nxt     = head + (nxt - head).normalized() * l

# future: push with sphere/capsule colliders → length constraint again

prev = cur; cur = nxt

dw   = normalize(nxt - head)
loc  = normalize(W.to_3x3().inverted() @ (A.to_3x3().inverted() @ dw))
q    = axis_j.rotation_difference(loc)
Bnew = bone_j.convert_local_to_pose(q.to_matrix().to_4x4(), R_j,
           parent_matrix=Mpar, parent_matrix_local=P_j)
```

`q` is a bone-local rotation, so it can be written back directly with
`pose_bone.matrix_basis = q.to_matrix().to_4x4()`. The next segment's `Mpar` is `Bnew`.

### Initialization

Compute `prev = cur = head + rest_dir * l` from the current pose at bind time.
`q` is the identity quaternion. The tail bone also rotates using its own tail as the
endpoint.

## 6. Implementation

| File | Role |
|---|---|
| `__init__.py` | `bl_info`, module reload, register/unregister |
| `props.py` | `SpringBoneSettings` (attached to Object), `SpringChain`, `SpringJoint` |
| `runtime.py` | `ArmatureRuntime`, `ChainRuntime`, `Segment`. bind/step/apply/reset |
| `driver.py` | `bpy.app.timers`, tick, redraw, playback/load/undo handlers |
| `ops.py` | Add/remove chain, Start/Stop, Rebind, Reset Pose, Bake |
| `ui.py` | View3D sidebar `SpringBone` panel |
| `tests/` | Headless / GUI verification scripts |

### Data model

- `SpringBoneSettings` (per armature object)
  - `update_hz`, `substeps`, `max_dt`, `use_evaluated_parents`, `reset_on_stop`
  - `chains`
- `SpringChain`
  - `name`, `center_bone` (for future use), `joints`
- `SpringJoint`
  - `bone_name`, `hit_radius`, `stiffness`, `gravity_power`, `gravity_dir`, `drag_force`

### Fetching the parent pose

- When `use_evaluated_parents=True` and there is animation/constraints:
  `evaluated_depsgraph_get()` → `arm.evaluated_get(dg).pose.bones[name].matrix`
- Otherwise:
  recursively compute from the parent's `matrix_basis` with `Bone.convert_local_to_pose`
  (this avoids depsgraph evaluation)

## 7. Installation and usage

The root of this repository (the `springbone` folder containing `__init__.py`) is the
add-on package itself. Place it in Blender's add-on directory (an add-on search path
matching your environment, such as `scripts/addons`), and enable `SpringBone Preview`
under `Preferences > Add-ons`. It uses the Blender 5.3 legacy `bl_info` format.

1. Prepare an armature.
2. In Pose mode, select the bones to form a chain (one bone is enough; they must be direct
   parent-child).
3. `Add Selected Chain` under `View3D > Sidebar > SpringBone`.
4. `Start`.
5. Move the parent bone or the object. Do not play the timeline.
6. If needed, use `Bake Action` to turn the result into keyframes.
7. `Stop` returns to the pose from before binding.

## 8. Known limitations

- **Auto-stop during playback**: `animation_playback_pre/post` stops live updates.
  Rendering does not run timers, so Bake beforehand.
- **F-Curves on spring bones**: depsgraph evaluation overwrites them with the animation.
  Do not place keys on chain target bones. Create keys only when baking.
- **Constraints**: the evaluated pose and `matrix_basis` diverge. v1 handles only the
  parent side via `use_evaluated_parents`. Constraints on the spring bones themselves are
  not supported.
- **Undo/Redo**: runtime references become stale, so v1 stops the preview.
- **`is_interface_locked`**: skip without touching data during rendering/jobs.
- **Non-uniform scale**: the length constraint becomes distorted. Warning only.
- **Non-direct parent-child (skips/branches)**: not supported in v1. Errors on
  `Add Chain`.
- **`matrix_basis` location/scale**: only rotation is written back.
- **Undo buffer**: direct RNA writes from a timer occur outside operators. The
  recommended practice is to Stop/Reset before saving.
- **Performance**: 60Hz × number of joints. `use_evaluated_parents` involves depsgraph
  evaluation, so lower `update_hz` / `substeps` in heavy scenes.

## 9. Verification

### Headless (math, bind, step)

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_runtime.py"
```

Result: `SMOKE OK last_angle=0.482668`

- 3 bones (Root → J1..J3, lengths 0.7 / 0.8 / 0.9) produce 3 segments.
- Rotate Root and step 120 times.
- The tip moves, there are no NaNs, and `scene.frame_current` stays at 1.
- The tail bone J3 also rotates (`matrix_basis` angle > 0).

### Headless (timer registration, Bake)

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_driver.py"
```

Result: `DRIVER OK`

- `driver.start` registers the timer, and `_tick()` steps it.
- `driver.stop` unregisters the timer.
- `Bake Action` creates an action and restores the original frame.

### GUI (actual timer period)

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_gui.py"
```

Result (example): `GUI OK frame=1 moved=1.317948 pose=0.029949`
(the movement and angle depend on the timer period, so they vary between runs)

- The timer ran periodically in a real UI session.
- The chain moved and `scene.frame_current` stayed at 1.
- Writing back to `matrix_basis` was also confirmed (non-zero rotation on J1).

## 10. Follow-up work

- Sphere / Capsule colliders (`VRMC_springBone.colliders`)
- center space (`VRMC_springBone.springs[*].center`)
- Skip/branch chains
- Per-chain display colors, statistics, FPS display
- Automatic resume on file load, running multiple scenes simultaneously
- Debug overlay via `draw_handler` (chain lines, collider spheres)
