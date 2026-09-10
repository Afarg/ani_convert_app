# ani_convert_app (PixelAnimator)

[img_to_pixcel_app](https://github.com/Afarg/img_to_pixcel_app) が生成したピクセルキャラクター画像（1〜4アングル）を読み込ませると、**まばたき**と**歩行**の差分フレームを自動生成するローカルWebアプリ。

> Generates blink and walk-cycle diff frames from pixel-art character sprites produced by `img_to_pixcel_app`, by editing the existing sprite pixels in place — no new viewpoints are fabricated.

3プロジェクトから成るパイプラインの2段目にあたるツール（生成した差分フレームは [agent-village](https://github.com/Afarg/agent-village) のダッシュボードに取り込むと、キャラクターが目を閉じたり歩いたりするアニメーションとして表示される）。

## 特徴

- **まばたき**: 元画像（ピクセル化前の高解像度画像）から目の位置を検出し、ピクセル化の縮小率に合わせて座標変換。最終ピクセルグリッド上で目にあたるマスを閉じ目色に塗り替えて生成。
- **歩行**: アングルを問わず、既存スプライトの脚部ピクセルを画像内で動かすことで歩行ループ用の2フレーム目を生成する決定論的処理。
- 「1枚の画像から未提供のアングル・新しい視点情報を捏造しない」という [img_to_pixcel_app](https://github.com/Afarg/img_to_pixcel_app) と共通の設計方針。提供されたアングルの数だけ同じ手法を適用し、提供されなかったアングルはスキップする。
- FastAPI + ブラウザUIでのプレビュー対応。

## 技術スタック

- Python / FastAPI（`uvicorn`）
- 画像処理: Pillow, OpenCV（`opencv-python-headless`）, NumPy, Matplotlib

## セットアップ

```bash
python -m venv .venv
.venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

詳細は `docs/design/03-environment-and-setup.md` を参照。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| `00-overview.md` | 全体像・スコープ・背景 |
| `01-architecture.md` | システム構成・技術スタック |
| `02-generation-pipeline.md` | まばたき・歩行差分の生成パイプライン詳細 |
| `03-environment-and-setup.md` | 環境構築手順 |
| `04-output-format-and-agent-village-handoff.md` | 出力形式・Agent Villageへの受け渡し |
| `05-constraints-and-limitations.md` | 制約・既知の限界 |
