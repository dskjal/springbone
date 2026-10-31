# SpringBone Preview

A Blender 5.3 add-on that simulates spring bones (secondary motion) in the viewport
**without playing the timeline**.

[Japanese Language](./README_ja.md).

The simulation is driven by `bpy.app.timers` on the main thread, so bones react while you
pose or move the armature, and `scene.frame_current` never changes. When you are happy with
the result, bake it to keyframes.

- Blender: 5.3
- Category: Rigging
- Location: `View3D > Sidebar > SpringBone`
- Algorithm and design notes: [`docs/springbone_runtime_en.md`](docs/springbone_runtime_en.md)
  (Japanese: [`docs/springbone_runtime_ja.md`](docs/springbone_runtime_ja.md))

## Installation

The repository root is the add-on package itself: the `springbone` folder containing
`__init__.py`.

### Option 1: Copy the folder

1. Copy the whole `springbone` folder into one of Blender's add-on directories, for example:
   - `%APPDATA%\Blender Foundation\Blender\5.3\scripts\addons\` (Windows)
   - `~/.config/blender/5.3/scripts/addons/` (Linux)
   - `~/Library/Application Support/Blender/5.3/scripts/addons/` (macOS)
   - or any path listed in `Preferences > File Paths > Scripts`.
2. Keep the folder name `springbone`; the package must resolve to `springbone/__init__.py`.
3. Restart Blender, or use `Preferences > Add-ons > Refresh`.
4. Open `Preferences > Add-ons`, search for **SpringBone Preview**, and enable the checkbox.

### Option 2: Install from a ZIP

1. Zip the `springbone` folder so that `springbone/__init__.py` sits at the archive root.
2. In Blender, open `Preferences > Add-ons > Install...`, pick the ZIP, and enable
   **SpringBone Preview** in the list.

## Usage

### 1. Build a chain

1. Select an armature object and enter **Pose** mode (or **Edit** mode).
2. Select the bones of the chain, from the root towards the tip.
   - One bone is enough.
   - The selected bones must be a **direct parent-child** sequence. Skipped or branched
     bones are rejected with an error.
   - Selection order does not matter; bones are sorted by hierarchy depth.
3. In the 3D Viewport sidebar, open the **SpringBone** tab and click
   **Add Selected Chain**.

Each selected bone becomes a joint. The chain is stored on the armature object, so it is
saved with the .blend file.

### 2. Run the preview

1. Click **Start**.
2. Move the parent bone, or move/rotate the armature object. The chain follows with spring
   motion.
3. Do **not** play the timeline. Playback pauses the live preview automatically and resumes
   the clock when it stops.

The panel header shows `Running` / `Stopped` and the current frame, which stays constant
while the preview runs.

### 3. Tune the motion

Armature-wide settings (top of the panel):

| Setting | Default | Description |
|---|---|---|
| `Update Hz` | 60 | Timer frequency for the simulation. Lower it for heavy scenes. |
| `Substeps` | 1 | Fixed substeps per tick. Raise it for stiffer/faster motion. |
| `Use Evaluated Parents` | On | Read parent pose from the evaluated depsgraph, so animation and constraints on parent bones are respected. Turn off to avoid depsgraph evaluation. |
| `Reset Pose on Stop` | On | Restore the pose captured at bind time when the preview stops. |

Per-joint settings (expand a joint in the chain list):

| Setting | Default | Description |
|---|---|---|
| `Stiffness` | 1.0 | Pull back towards the rest direction. |
| `Drag Force` | 0.4 | Velocity damping (0 = none, 1 = fully damped). |
| `Gravity Power` | 0.0 | Strength of the constant external force. |
| `Gravity Direction` | (0, 0, -1) | Direction of that force, in world space. |
| `Hit Radius` | 0.02 | Reserved for collider support. |

Chain-level fields: `Name` and `Center Bone` (the latter is reserved for future center-space
support and currently unused).

### 4. Bake to keyframes

1. Set the scene frame range to the range you want to bake.
2. Click **Bake Action**.

The add-on stops the live preview, re-binds a fresh simulation, steps it once per frame over
the scene range at the scene frame rate, and inserts rotation keys on every chain bone
(`rotation_quaternion`, `rotation_axis_angle`, or `rotation_euler`, matching each bone's
rotation mode). The original frame is restored afterwards.

Because the bake writes keys, remove any existing keys on the chain bones first, otherwise
depsgraph evaluation will overwrite the simulation.

### 5. Stop and clean up

- **Stop** ends the preview and, with `Reset Pose on Stop` enabled, restores the pose from
  before binding.
- **Reset Pose** restores the bind-time pose at any moment, even when stopped (it then
  clears `matrix_basis` on the chain bones).
- **Rebind** rebuilds rest data and simulation state from the current pose. Use it after
  editing bone rest positions or changing the chain.

The add-on writes pose data from a timer, outside any operator. Stop the preview (or run
**Reset Pose**) before saving the file.

## Panel and operator reference

| Control | Operator | Notes |
|---|---|---|
| `Start` | `springbone.start_preview` | Fails with an error if the chain is invalid. |
| `Stop` | `springbone.stop_preview` | Only available while running. |
| `Add Selected Chain` | `springbone.add_chain` | Pose or Edit mode, direct parent-child bones. |
| `Rebind` | `springbone.bind` | Only available while running. |
| `Reset Pose` | `springbone.reset_pose` | Restores the bind-time pose. |
| `Bake Action` | `springbone.bake_action` | Bakes over the scene frame range. |

## Behavior notes

- The timeline is never modified; the preview clock is wall-clock based.
- Live preview pauses during playback and while the interface is locked (rendering or a
  running job).
- The preview stops automatically on file load and on Undo/Redo, because runtime references
  become stale. Press **Start** again after those operations.
- Rendering does not run timers, so bake before rendering.
- Constraints on the spring bones themselves are not supported; constraints and animation on
  parent bones are handled through `Use Evaluated Parents`.
- Non-uniform object scale distorts the length constraint.

See [`docs/springbone_runtime_en.md`](docs/springbone_runtime_en.md) for the full design,
API references, and known limitations.

## Verification scripts

Headless checks:

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_runtime.py"

& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_driver.py"
```

GUI check (opens Blender and exercises the real timer):

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_gui.py"
```
