# SpringBone Preview

タイムラインを再生せずに、ビューポート上でスプリングボーン（二次揺れ）を
シミュレーションする Blender 5.3 アドオンです。

シミュレーションはメインスレッドの `bpy.app.timers` で駆動されるため、ポーズ操作や
オブジェクト移動に追従してボーンが動き、`scene.frame_current` は変化しません。
結果に満足したらキーフレームにベイクできます。

- Blender: 5.3
- カテゴリ: Rigging
- 場所: `View3D > Sidebar > SpringBone`
- アルゴリズムと設計: [`docs/springbone_runtime_ja.md`](docs/springbone_runtime_ja.md)
  （英語: [`docs/springbone_runtime_en.md`](docs/springbone_runtime_en.md)）

## インストール

リポジトリのルートがアドオンパッケージ本体です。`__init__.py` を含む `springbone`
フォルダがそれに当たります。

### 方法 1: フォルダをコピーする

1. `springbone` フォルダごと、Blender のアドオンディレクトリにコピーします。例:
   - `%APPDATA%\Blender Foundation\Blender\5.3\scripts\addons\`（Windows）
   - `~/.config/blender/5.3/scripts/addons/`（Linux）
   - `~/Library/Application Support/Blender/5.3/scripts/addons/`（macOS）
   - または `Preferences > File Paths > Scripts` に登録した任意のパス
2. フォルダ名は `springbone` のままにしてください。パッケージが
   `springbone/__init__.py` として解決される必要があります。
3. Blender を再起動するか、`Preferences > Add-ons > Refresh` を実行します。
4. `Preferences > Add-ons` を開き、**SpringBone Preview** を検索してチェックを入れます。

### 方法 2: ZIP からインストールする

1. `springbone` フォルダを ZIP 化します。アーカイブのルートに
   `springbone/__init__.py` が来るようにしてください。
2. Blender で `Preferences > Add-ons > Install...` を開き、ZIP を選択します。
3. 一覧に現れる **SpringBone Preview** を有効化します。

## 使い方

### 1. チェーンを作る

1. Armature オブジェクトを選択し、**Pose** モード（または **Edit** モード）に入ります。
2. チェーンにするボーンを、根元から先端に向かって選択します。
   - 1 本からでも構いません。
   - 選択したボーンは**直接の親子関係**で連続している必要があります。ボーンを
     飛ばしたり分岐させたりするとエラーになります。
   - 選択順は問いません。階層の深さで自動的に並べ替えられます。
3. 3D ビューポートのサイドバーで **SpringBone** タブを開き、
   **Add Selected Chain** をクリックします。

選択した各ボーンがジョイントになります。チェーンは Armature オブジェクトに保存される
ため、.blend ファイルにも残ります。

### 2. プレビューを実行する

1. **Start** をクリックします。
2. 親ボーンを動かすか、Armature オブジェクト自体を移動・回転します。チェーンが
   スプリングの動きで追従します。
3. タイムラインは**再生しないでください**。再生中はライブプレビューが自動的に止まり、
   再生終了時に時計がリセットされます。

パネル上部には `Running` / `Stopped` と現在のフレームが表示されます。プレビュー中も
フレームは変わりません。

### 3. 動きを調整する

Armature 全体の設定（パネル上部）:

| 設定 | 既定値 | 説明 |
|---|---|---|
| `Update Hz` | 60 | シミュレーションのタイマー周期。重いシーンでは下げます。 |
| `Substeps` | 1 | 1 ティックあたりの固定サブステップ数。硬め・速めの動きにしたいときに増やします。 |
| `Use Evaluated Parents` | オン | 親ボーンのポーズを評価済み depsgraph から取得し、親のアニメーションや Constraint を反映します。オフにすると depsgraph 評価を避けられます。 |
| `Reset Pose on Stop` | オン | プレビュー停止時に、バインド時のポーズへ戻します。 |

ジョイントごとの設定（チェーン一覧でジョイントを展開）:

| 設定 | 既定値 | 説明 |
|---|---|---|
| `Stiffness` | 1.0 | rest 方向へ引き戻す強さ。 |
| `Drag Force` | 0.4 | 速度の減衰（0 = 減衰なし、1 = 完全に減衰）。 |
| `Gravity Power` | 0.0 | 一定の外力の強さ。 |
| `Gravity Direction` | (0, 0, -1) | その外力の方向（ワールド空間）。 |
| `Hit Radius` | 0.02 | コライダー対応用の予約フィールド。 |

チェーン単位のフィールド: `Name` と `Center Bone`（後者は将来の center 空間対応用で、
現在は未使用）。

### 4. キーフレームにベイクする

1. シーンのフレーム範囲を、ベイクしたい範囲に設定します。
2. **Bake Action** をクリックします。

アドオンはライブプレビューを停止し、新しいシミュレーションをバインドし直して、
シーンのフレームレートで 1 フレームずつステップし、チェーンの各ボーンに回転キーを
挿入します（各ボーンの回転モードに応じて `rotation_quaternion` /
`rotation_axis_angle` / `rotation_euler`）。完了後は元のフレームに戻ります。

ベイクはキーを書き込むため、チェーン対象ボーンに既存のキーがある場合は先に削除して
ください。残っていると depsgraph 評価でシミュレーション結果が上書きされます。

### 5. 停止と後片付け

- **Stop** でプレビューを終了します。`Reset Pose on Stop` が有効なら、バインド前の
  ポーズに戻ります。
- **Reset Pose** はいつでもバインド時のポーズに戻します。停止中でも動作し、その場合は
  チェーン対象ボーンの `matrix_basis` をクリアします。
- **Rebind** は現在のポーズから rest データとシミュレーション状態を再構築します。
  ボーンの rest 位置を編集した後や、チェーンを変更した後に使います。

アドオンはオペレータ外のタイマーからポーズデータを書き込みます。ファイルを保存する前に
プレビューを停止する（または **Reset Pose** を実行する）ようにしてください。

## パネルとオペレータ一覧

| 操作 | オペレータ | 備考 |
|---|---|---|
| `Start` | `springbone.start_preview` | チェーンが不正な場合はエラーで失敗します。 |
| `Stop` | `springbone.stop_preview` | 実行中のみ使用できます。 |
| `Add Selected Chain` | `springbone.add_chain` | Pose / Edit モードで、直接の親子ボーンを選択します。 |
| `Rebind` | `springbone.bind` | 実行中のみ使用できます。 |
| `Reset Pose` | `springbone.reset_pose` | バインド時のポーズに戻します。 |
| `Bake Action` | `springbone.bake_action` | シーンのフレーム範囲全体をベイクします。 |

## 動作上の注意

- タイムラインは一切変更しません。プレビューの時計は壁時計ベースです。
- 再生中、およびインターフェースがロックされている間（レンダーやジョブ実行中）は
  ライブプレビューを停止します。
- ファイル読込時と Undo/Redo 時は、ランタイムの参照が古くなるため自動的にプレビューを
  停止します。これらの操作の後は再度 **Start** を押してください。
- レンダーではタイマーが動かないため、レンダー前にベイクしてください。
- スプリングボーン自身への Constraint は非対応です。親ボーンの Constraint と
  アニメーションは `Use Evaluated Parents` で扱います。
- オブジェクトの非一様スケールは長さ拘束を歪めます。

設計の詳細、API の根拠、既知の制約は
[`docs/springbone_runtime_ja.md`](docs/springbone_runtime_ja.md) を参照してください。

## 検証スクリプト

ヘッドレスでの確認:

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_runtime.py"

& "D:\data\apps\blender\blender-5.3.0\blender.exe" -b --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_driver.py"
```

GUI での確認（Blender を起動し、実際のタイマーを動かします）:

```powershell
& "D:\data\apps\blender\blender-5.3.0\blender.exe" --factory-startup `
  --python "D:\data\apps\blender\addons50\springbone\tests\smoke_gui.py"
```
