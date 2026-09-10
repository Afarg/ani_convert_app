# 03. 環境構築・必要なソフトウェア — PixelAnimator

対象読者: 実装者・導入担当者。
関連: `../../img_to_pixcel_app/docs/design/03-environment-and-setup.md`（共通する前提の多くはそちらと同じ）。

**実装状況**: 実装済み・実機検証済み。

---

## 1. 前提条件

| 項目 | 要件 |
|---|---|
| Python | 3.10以上（`img_to_pixcel_app`と同じ） |
| OS | Windows / macOS / Linux |
| GPU | 不要（画像処理はすべてCPUで完結する古典的手法） |
| ネットワーク | `pip install`時のみ必要。以降は完全オフラインで動作（モデルファイルのダウンロードは一切発生しない、`img_to_pixcel_app`の`rembg`のような初回モデルダウンロードすら無い） |

`img_to_pixcel_app`と同じPython環境を使い回すことも可能だが、**両ツールは独立して動くことを前提に別々の仮想環境（venv）で運用することを推奨**する（一方の依存関係更新が他方に影響しないようにするため）。実際に別々の`.venv`で構築・検証済み。

## 2. 必要なpipパッケージ

| パッケージ | 役割 | 備考 |
|---|---|---|
| `fastapi` / `uvicorn` | ローカルサーバー | `img_to_pixcel_app`と共通 |
| `python-multipart` | バンドル（複数ファイル）のアップロード受信 | 同上 |
| `Pillow` | フレーム画像の読み書き・貼り付け合成 | 同上 |
| `opencv-python-headless` | 目の検出（彩度ベースのヒューリスティック、`02-generation-pipeline.md` §2.1） | GUI依存の無いheadless版を採用。`connectedComponentsWithStats`等の基本機能のみ使用し、モデルファイルは不要 |
| `numpy` | bounding box計算、脚部領域のピクセル操作、彩度解析 | 同上 |

`requirements.txt`（実装済み・実際にこの内容で動作確認済み）:

```
fastapi
uvicorn[standard]
python-multipart
Pillow
opencv-python-headless
numpy
```

> **更新履歴（実機検証で判明）**: 当初案では`opencv-python`（Haar cascade同梱を期待）を挙げていたが、実装時に判明した2点により変更した。(1) インストールしたOpenCVビルド（5.0.0系）に`haarcascade_eye.xml`が同梱されておらず、公式配布元からの取得も本セッションの権限設定でブロックされたため、目検出はヒューリスティックのみの方式に変更した（`02-generation-pipeline.md` §2.1、`01-architecture.md` §4）。(2) GUI機能は不要なサーバー用途のため、`opencv-python`ではなく`opencv-python-headless`を採用した。結果として、当初期待していた「モデルダウンロード不要」という利点はそのまま維持できている（ヒューリスティックのみなのでそもそもモデル自体が不要）。

## 3. 起動方法（実装済み）

```bash
cd ani_convert_app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 4373
```

既定ポートは4373（Agent Village=4173、PixelForge=4273と衝突しない値、`docs/operations-guide.md`の運用方針と一貫させる）。
