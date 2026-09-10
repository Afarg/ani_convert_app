# 04. 出力形式・Agent Villageへの受け渡し — PixelAnimator

対象読者: 実装者。
関連: `02-generation-pipeline.md`（生成されるフレーム）、`agents_app/docs/design/07-directional-animation-support.md`（Agent Village側の消費方法、本ドキュメントの対）。

---

## 1. なぜAgent Village側の対応が別途必要か

Agent Village（`agents_app`）は現状、キャラクター画像を**1枚の静止テクスチャ**として表示するだけで、複数フレームを切り替えて再生する仕組みを持たない（`public/js/game.js`の`applyCharacterSprite`は単一テクスチャの差し替えのみ）。そのため、本ツールがどれだけ良い差分フレームを作っても、**Agent Village側に再生機構が無ければ表示されない。** この対応は`agents_app/docs/design/07-directional-animation-support.md`で別途設計する。本書はPixelAnimator側が「何を」出力するかを定義する。

## 2. 出力形式: アニメーションバンドル

**フェーズ2（正面+斜め、推奨構成）の例:**

```
<character-id>-anim/
├─ anim-manifest.json
├─ front.png             # 立ちフレーム(img_to_pixcel_appの出力そのまま。idle用) - 必須
├─ front_blink.png       # まばたきフレーム(検出できた場合のみ)
├─ diagonal_left.png     # 移動表示の基本アングル(左向き) - 推奨（フェーズ2以降でどちらか一方以上が存在）
├─ diagonal_left_blink.png
├─ diagonal_left_walk1.png   # 歩行パターン1(右脚+左手シフト)
├─ diagonal_left_walk2.png   # 歩行パターン2(左脚+右手シフト)
├─ diagonal_right.png    # 提供されていれば同様に続く（片方だけの場合は無い）
├─ diagonal_right_blink.png
├─ diagonal_right_walk1.png
├─ diagonal_right_walk2.png
├─ back.png              # 以下、フェーズ3（任意アレンジ）で提供された分だけ同様に続く
├─ back_blink.png
├─ back_walk1.png
├─ back_walk2.png
...
```

**フェーズ1（正面のみ）の例:**

```
<character-id>-anim/
├─ anim-manifest.json
├─ front.png             # 必須
├─ front_blink.png       # まばたきフレーム(検出できた場合のみ)
├─ front_walk1.png       # front しか無いため、front にも歩行フレームを生成する（02-generation-pipeline.md §3更新履歴2）
└─ front_walk2.png
```

`anim-manifest.json`の例（フェーズ2、斜め左のみ提供の場合）:

```jsonc
{
  "characterId": "code-reviewer",
  "views": {
    "front": {
      "idle": ["front.png", "front_blink.png"]      // blinkが無ければ ["front.png"] のみ。diagonal_left等の他アングルがあるためwalkは持たない
    },
    "diagonal_left": {
      "idle": ["diagonal_left.png", "diagonal_left_blink.png"],
      "walk": ["diagonal_left_walk1.png", "diagonal_left_walk2.png"]
    }
    // フェーズ1なら diagonal_left/diagonal_right キー自体が無く、代わりに front.walk が存在する。
    // 斜めを両方提供した場合は diagonal_left と diagonal_right の両方のキーを持つ。フェーズ3なら back / side も同様のキーを持つ
  }
}
```

> **更新履歴（2026-07-29）**: 左右非対称なキャラクターに対応するため、`img_to_pixcel_app`側の「斜め」入力が`diagonal_left`/`diagonal_right`の2枠に分かれた（`img_to_pixcel_app/docs/design/06-multi-angle-input.md`更新履歴）。本ツール(`app/bundle.py`)は`manifest.json`の`views`キーをそのまま汎用的に処理しているため、view名の変更自体に伴うコード変更は不要だった。歩行フレームの命名も`_walk2.png`単独から`_walk1.png`/`_walk2.png`の2枚に変更されている（`02-generation-pipeline.md` §3・§4参照）。

- `idle`配列の要素数が1の場合、Agent Village側はまばたきせず静止表示する（`07-directional-animation-support.md`側でこの縮退ケースを扱う）。
- `front`は入力側（`img_to_pixcel_app`）で唯一の必須スロットのため、`views`に必ず存在する。`diagonal`/`back`/`side`は推奨または任意のため無いこともある。`views`に存在しないアングルについては、Agent Village側は該当方向の移動時に代替として`diagonal`、それも無ければ`front`を使う、というフォールバックにする（`07-directional-animation-support.md` §4.2、更新済み）。

## 3. Agent Villageへの受け渡し方法

`img_to_pixcel_app/docs/design/05-agent-village-integration.md`と同じ2パターンを踏襲する。

| 方法 | 内容 |
|---|---|
| 手動 | 生成されたバンドル一式（フォルダごと）をダウンロードし、Agent Village側の新しいアップロード窓口（`07-directional-animation-support.md`で新設）にまとめてアップロードする |
| 直接送信（任意） | PixelAnimatorのサーバーから、Agent Village側の新設APIへバンドル一式をPOSTする |

単一PNGだった従来の`/api/agents/:id/sprite`とは異なり、**複数ファイル＋マニフェストを一括で扱う新しいエンドポイントがAgent Village側に必要**になる点に注意（`07-directional-animation-support.md` §3）。
