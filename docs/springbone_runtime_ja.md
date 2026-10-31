# SpringBone ビューポートランタイム調査

対象: Blender 5.3 / `bpy` Python API

## 結論

タイムラインを再生せずにビューポートでボーンを動かすには、**`bpy.app.timers` を
シミュレーションの時計にする**のが唯一実用的な方法。

1. タイマーコールバックで毎フレーム `dt` を進める。
2. `Bone.convert_local_to_pose` で親から子へポーズ行列を手動伝播する。
3. 最終結果だけ `PoseBone.matrix_basis` に書き戻す。
4. `ID.update_tag` + `Area.tag_redraw()` でビューポートを更新する。
5. `scene.frame_current` には一切触れない。

`frame_change_pre/post`、Geometry Nodes の Simulation Zone、標準物理はすべて
「フレームが進むこと」が前提なので、この要件には使えない。

## 1. なぜフレーム以外の時計が必要か

Blender のアニメーション評価は depsgraph が担い、物理シミュレーション
（Rigid Body / Cloth / Soft Body / GN Simulation Zone）はフレーム変更を
トリガーにステップする。タイムラインを再生しない、スクラブしないという条件では
これらのコールバックは呼ばれない。

したがって、壁時計（`time.perf_counter()`）で駆動する仕組みをアドオン側で持つ。
`bpy.app.timers` は Blender のメインループに乗るため、UI イベントがなくても
メインスレッドで定期的に呼ばれる。

## 2. 方式比較

| 方式 | 再生不要 | 常時駆動 | 問題点 | 判定 |
|---|---|---|---|---|
| `bpy.app.timers` | ○ | ○ | 精度保証なし。`is_interface_locked` ガード必須 | **採用** |
| モーダルオペレータ + `event_timer_add` | ○ | △ | 他のモーダル操作で止まる。ウィンドウ依存 | 不採用 |
| `depsgraph_update_post` | △ | × | 変更時のみ。自分の書き込みで再帰 | 補助のみ |
| `frame_change_pre/post` | × | × | フレーム変更が必須 | 不採用 |
| GN Simulation Zone | × | × | フレーム評価でのみ進む | 不採用 |
| Driver | × | × | 評価トリガが必要 | 不採用 |
| `SpaceView3D.draw_handler_add` | ○ | × | 描画のみ。データ変更不可 | デバッグ用 |
| 標準物理 | × | × | キャッシュがフレーム依存 | 不採用 |

### モーダルオペレータが不採用の理由

`WindowManager.event_timer_add` + `modal_handler_add` でも TIMER イベントは
受け取れるが、Blender のモーダルハンドラはウィンドウごとに 1 つという制約がある。
移動・回転・スケールなどのトランスフォームもモーダルオペレータなので、
ユーザーがボーンを掴んだ瞬間にプレビューが止まる。常時プレビューには向かない。

### `depsgraph_update_post` が不採用の理由

データが変更されたときだけ呼ばれる。何も操作していない間は発火しないので
時計にならない。また、コールバック内でポーズを書き換えると depsgraph が
再び更新され、再帰・無限ループの危険がある。

## 3. 採用アーキテクチャ

```
timer tick (main thread)
  ├─ wm.is_interface_locked / playback中 / 対象なし → 次回予約
  ├─ runtime ごと
  │    ├─ dt = clamp(perf_counter - last, 0, max_dt)
  │    ├─ 親ポーズ取得（evaluated or matrix_basis）
  │    ├─ 固定サブステップ: verlet → 長さ拘束 →（将来: コライダー）
  │    └─ 最終結果だけ matrix_basis に書き戻す
  ├─ arm.update_tag(refresh={'OBJECT'})
  └─ 全 VIEW_3D の Area.tag_redraw()
```

- サブステップ中は Blender のデータを読まない。行列計算は自前で完結させる。
- `view_layer.update()` をボーンごとに呼ばない。呼ぶのは 1 ティックに 1 回まで。
- シミュレーションはワールド空間で行う。オブジェクト移動時の慣性を出すため。
- ボーン行列の計算は armature 空間で行い、頭位置と rest 方向だけ
  `arm.matrix_world` でワールド化する。

## 4. Blender 5.3 API の根拠

### タイマー

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

`persistent=True` はファイル読込をまたいでタイマーを残す。
`is_registered(tick)` / `unregister(tick)` で多重登録と解除を行う。
`persistent=True` のままだと読込後に古いオブジェクト参照が残るため、
`load_post` で解除・クリアする。

### インターフェースロック

https://docs.blender.org/api/5.3/bpy.types.WindowManager.html#bpy.types.WindowManager.is_interface_locked

> If true, the interface is currently locked by a running job and data should not be
> modified from application timers. Otherwise, the running job might conflict with the
> handler causing unexpected results or even crashes.

ティックの先頭で必ず確認し、true ならデータを触らずに次回予約だけ行う。

### ポーズ行列の手動伝播

https://docs.blender.org/api/5.3/bpy.types.Bone.html#bpy.types.Bone.convert_local_to_pose

> This method enables conversions between Local and Pose space for bones in the middle of
> updating the armature without having to update dependencies after each change,
> by manually carrying updated matrices in a recursive walk.

`parent_matrix` / `parent_matrix_local` を渡し、`invert=True` で local に戻せる。
これにより、各ボーンごとに `bpy.context.view_layer.update()` を呼ばずに済む。

### ポーズデータ

- `PoseBone.matrix_basis`:
  > Alternative access to location/scale/rotation relative to the parent and own rest bone
- `PoseBone.matrix`:
  > Final 4×4 matrix after constraints and drivers are applied, in the armature object space
- `Bone.matrix_local`:
  > 4×4 bone matrix relative to armature

`matrix_basis` がシミュレーションの書き込み先。`matrix` は評価後の読み取り用。

### 表示更新

- `ID.update_tag(*, refresh=set())`:
  > Tag the ID to update its display data, e.g. when calling `ViewLayer.update`
- `ViewLayer.update()`:
  > Update data tagged to be updated from previous access to data or operators
- `Area.tag_redraw()`:
  https://docs.blender.org/api/5.3/bpy.types.Area.html#bpy.types.Area.tag_redraw

`matrix_basis` を書き換えた後、`arm.update_tag(refresh={'OBJECT'})` と
全 `VIEW_3D` エリアの `tag_redraw()` を行う。

### 評価済みポーズ

https://docs.blender.org/api/5.3/bpy.types.Depsgraph.html

```python
depsgraph = bpy.context.evaluated_depsgraph_get()
arm_eval = arm.evaluated_get(depsgraph)
parent_matrix = arm_eval.pose.bones[parent_name].matrix.copy()
```

親ボーンにアニメーションや Constraint がある場合は評価済みの行列を使う。
`ID.evaluated_get()` は「最後に評価された結果を返すだけで、評価を保証しない」
ので、必ず `evaluated_depsgraph_get()` と組み合わせる。

### 再生ハンドラ

- `bpy.app.handlers.animation_playback_pre`
- `bpy.app.handlers.animation_playback_post`

再生開始でライブ更新を止め、終了で時計をリセットする。
`frame_change_*` はレンダー時に別スレッドから呼ばれ、データ変更でクラッシュし得る
（公式ドキュメントの Note on Altering Data）。プレビューでは使わない。

### モーダル用 API（比較用）

- `WindowManager.event_timer_add(time_step, *, window=None)`
- `WindowManager.modal_handler_add(operator)`

テンプレート: `5.3/scripts/templates_py/Operator/modal_timer.py`

### デバッグ用

`SpaceView3D.draw_handler_add(callback, args, 'WINDOW', 'POST_VIEW')` は
描画専用。チェーン線やコライダー球の可視化には使えるが、シミュレーションの
時計にはならない。

## 5. SpringBone と Blender の対応

### 事前計算

セグメント j（joint j の head → 次の joint の head）:

```
R_j  = bone_j.matrix_local                       # armature rest
P_j  = parent(bone_j).matrix_local or Identity
v_j  = (R_j^-1 @ bone_{j+1}.matrix_local).translation
axis_j = v_j.normalized()
len_j  = v_j.length
```

末尾ボーン（次の joint がない j = N-1）は、自身の tail を終端として使う:

```
v_j = R_j^-1 @ bone_j.tail_local
```

これにより N 本のチェーンに対して N セグメントができ、末尾ボーンも回転する。
`len_j` は常に実際のボーン長から計算するため、任意の長さのボーンで動作する。
VRMC 仕様では末尾 joint は tail 専用だが、Blender のボーンは自身の tail を持つため、
それを sentinel として扱う。末尾 joint の `stiffness` / `drag` / `gravity` も有効。

`axis_j` は joint j のボーンローカル空間で次の joint の頭（または自身の tail）を
指す方向。直接の親子で `use_connect=True` なら `(0, 1, 0)` とボーン長になる。

### 毎ステップ

```
A     = arm.matrix_world
Mpar  = 実際の親ボーンの pose 行列（armature 空間）
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

# 将来: sphere/capsule コライダーで push → 再度長さ拘束

prev = cur; cur = nxt

dw   = normalize(nxt - head)
loc  = normalize(W.to_3x3().inverted() @ (A.to_3x3().inverted() @ dw))
q    = axis_j.rotation_difference(loc)
Bnew = bone_j.convert_local_to_pose(q.to_matrix().to_4x4(), R_j,
           parent_matrix=Mpar, parent_matrix_local=P_j)
```

`q` はボーンローカルの回転なので、そのまま
`pose_bone.matrix_basis = q.to_matrix().to_4x4()` で書き戻せる。
次のセグメントの `Mpar` は `Bnew`。

### 初期化

`prev = cur = head + rest_dir * l` をバインド時の現在ポーズから計算する。
`q` は単位クォータニオン。末尾ボーンも自身の tail を終端として回転する。

## 6. 実装

| ファイル | 役割 |
|---|---|
| `__init__.py` | `bl_info`、モジュール reload、register/unregister |
| `props.py` | `SpringBoneSettings`（Object に付与）、`SpringChain`、`SpringJoint` |
| `runtime.py` | `ArmatureRuntime`、`ChainRuntime`、`Segment`。bind/step/apply/reset |
| `driver.py` | `bpy.app.timers`、tick、redraw、playback/load/undo ハンドラ |
| `ops.py` | チェーン追加/削除、Start/Stop、Rebind、Reset Pose、Bake |
| `ui.py` | View3D サイドバー `SpringBone` パネル |
| `tests/` | ヘッドレス / GUI の検証スクリプト |

### データモデル

- `SpringBoneSettings`（armature オブジェクトごと）
  - `update_hz`, `substeps`, `max_dt`, `use_evaluated_parents`, `reset_on_stop`
  - `chains`
- `SpringChain`
  - `name`, `center_bone`（将来用）, `joints`
- `SpringJoint`
  - `bone_name`, `hit_radius`, `stiffness`, `gravity_power`, `gravity_dir`, `drag_force`

### 親ポーズの取得

- `use_evaluated_parents=True` かつアニメーション/Constraint がある場合:
  `evaluated_depsgraph_get()` → `arm.evaluated_get(dg).pose.bones[name].matrix`
- それ以外:
  親の `matrix_basis` から `Bone.convert_local_to_pose` で再帰計算
  （depsgraph 評価を避けられる）

## 7. インストールと使い方

このリポジトリのルート（`__init__.py` がある `springbone` フォルダ）が
アドオンパッケージ本体。Blender のアドオンディレクトリ
（`scripts/addons` など、環境に合わせたアドオン検索パス）に置き、
`Preferences > Add-ons` で `SpringBone Preview` を有効化する。
Blender 5.3 のレガシー `bl_info` 形式。

1. Armature を用意する。
2. Pose モードでチェーンにするボーンを選択（1 本から可。直接の親子であること）。
3. `View3D > Sidebar > SpringBone` の `Add Selected Chain`。
4. `Start`。
5. 親ボーンやオブジェクトを動かす。タイムラインは再生しない。
6. 必要なら `Bake Action` でキーフレーム化する。
7. `Stop` でバインド前のポーズに戻る。

## 8. 既知の制約

- **再生中は自動停止**: `animation_playback_pre/post` でライブ更新を止める。
  レンダーはタイマーが動かないため、事前に Bake が必要。
- **スプリングボーンの F-Curve**: depsgraph 評価でアニメーションに上書きされる。
  チェーン対象ボーンにはキーを置かない。Bake 時のみキーを作る。
- **Constraint**: 評価後ポーズと `matrix_basis` がずれる。v1 は親側だけ
  `use_evaluated_parents` で対応。スプリングボーン自身への Constraint は非対応。
- **Undo/Redo**: ランタイムの参照が古くなるため v1 はプレビュー停止。
- **`is_interface_locked`**: レンダー/ジョブ中はデータを触らずスキップ。
- **非一様スケール**: 長さ拘束が歪む。警告のみ。
- **直接の親子以外（スキップ/分岐）**: v1 は非対応。`Add Chain` 時にエラー。
- **`matrix_basis` の location/scale**: 回転のみを書き戻す。
- **Undo バッファ**: タイマーからの直接 RNA 書き込みはオペレータ外。
  保存前に Stop/Reset する運用を推奨。
- **性能**: 60Hz × ジョイント数。`use_evaluated_parents` は depsgraph 評価を
  伴うため、重いシーンでは `update_hz` / `substeps` を下げる。

## 9. 検証

### ヘッドレス（数式・bind・step）

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_runtime.py"
```

結果: `SMOKE OK last_angle=0.482668`

- 3 ボーン（Root → J1..J3、長さ 0.7 / 0.8 / 0.9）で 3 セグメント。
- Root を回転して 120 ステップ。
- 先端が移動し、NaN なし、`scene.frame_current` は 1 のまま。
- 末尾ボーン J3 も回転している（`matrix_basis` の角度 > 0）。

### ヘッドレス（タイマー登録・Bake）

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_driver.py"
```

結果: `DRIVER OK`

- `driver.start` でタイマー登録、`_tick()` でステップ。
- `driver.stop` でタイマー解除。
- `Bake Action` でアクション作成、元のフレームに復帰。

### GUI（実際のタイマー周期）

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_gui.py"
```

結果（例）: `GUI OK frame=1 moved=1.317948 pose=0.029949`
（移動量と角度はタイマー周期に依存するため実行ごとに変わる）

- UI セッションでタイマーが実際に周期実行された。
- チェーンが動き、`scene.frame_current` は 1 のまま。
- `matrix_basis` への書き戻しも確認（J1 に非ゼロ回転）。

## 10. 後続

- Sphere / Capsule コライダー（`VRMC_springBone.colliders`）
- center 空間（`VRMC_springBone.springs[*].center`）
- スキップ/分岐チェーン
- チェーンごとの表示色、統計、FPS 表示
- ファイル読込時の自動再開、複数シーン同時実行
- `draw_handler` によるデバッグオーバーレイ（チェーン線、コライダー球）
