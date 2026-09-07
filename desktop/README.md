# デスクトップアイコン（macOS）

`サブスクAPIチェッカー.app` の材料と組み立て手順です。

## 中身

| ファイル | 役割 |
|---|---|
| `icon.svg` | アイコンの原図。ここだけ直せば全サイズに反映される |
| `icons/icon_*.png` | 原図から描き出した各サイズ（16〜1024px） |
| `icon.icns` | macOS 用にまとめたアイコン |
| `launcher.sh` | ダブルクリックしたときに走る中身 |
| `Info.plist` | アプリの名札（名前・アイコン・識別子） |
| `render_icon.mjs` | `icon.svg` → PNG（Playwright が要る） |
| `build_icns.py` | PNG → `.icns`（標準ライブラリだけ。macOS 不要） |
| `build_app.py` | 部品 → `.app` と配布用 zip |

## 組み立てなおす

アイコンの絵を変えたときだけ最初の1行が要ります。

```bash
node desktop/render_icon.mjs                              # SVG → PNG
python desktop/build_icns.py desktop/icons desktop/icon.icns   # PNG → icns
python desktop/build_app.py desktop/build                 # → .app と zip
```

`launcher.sh` や `Info.plist` を直しただけなら、最後の1行だけで足ります。

## 起動すると何が起きるか

1. チェッカー本体（teraco.money の `/advice/subscriptions`）をブラウザで開く（ここは何があっても必ず通る）
2. 手元の台帳を `service_costs.py check` で点検する
3. 🔴 があればダイアログで止める。🟡 は通知。何も無ければ「異常なし」

## 台帳の場所

`~/.subscheck-repo` にパスを1行書いておくと、そこを最優先で見ます。
書いていなければ次の順で探します。

```
~/teraco-labo-website
~/Documents/GitHub/ai-news-digest
~/Documents/Claude/ai-news-repo
```

## 署名について

自己署名すらしていないので、初回だけ macOS が止めます。
**右クリック → 開く** で通してください。以降は普通にダブルクリックで起動します。
