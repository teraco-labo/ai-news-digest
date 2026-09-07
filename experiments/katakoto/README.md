# 【実験】ミカを「片言の外国人」にするバージョン

2026-08-26 に検証した実験。**本番の毎朝の配信には組み込んでいない。**
`generate_news.py` からは一切呼ばれないので、置いてあるだけでは何も起きない。

## 結論

動作は良好。声は **`en-US-AvaMultilingualNeural`（英語アクセント）が最良**という評価。
ただし「AI音声が片言だとリスナーの気が散る」という判断で**本番投入は見送り**。
必要になったら復活させる。

## 仕組み（2段構え）

1. **声** — edge-tts の Multilingual ボイスに日本語を読ませると外国語訛りになる。
   ミカだけこれに差し替え、てらこ先生は通常の日本語ボイスのまま。`rate="-8%"` で少しゆっくり。
2. **セリフ** — Gemini でミカのセリフだけを片言に書き換える。
   助詞を省く／やさしい言葉／一人称「わたし」／「えーと」と言葉を探す／
   カタカナ外来語を好む／一文を短く／意味は変えない。
   「明るく一生懸命な外国人」として書き、戯画化・失礼な表現にはしない。

## ファイル

| ファイル | 中身 |
|---|---|
| `generate_katakoto.py` | 生成スクリプト（既存の台本を読み込んで片言版を作る） |
| `sample-ava.mp3` | 生成結果のサンプル（4分・冒頭16ターン） |
| `sample-ava-script.txt` | そのときの台本 |
| `voice-comparison-5.mp3` | 多言語ボイス5種の聴き比べ（英×2・仏・独・葡） |

## 使い方

```bash
GEMINI_API_KEY=xxx MIKA_VOICE=en-US-AvaMultilingualNeural \
  python3 experiments/katakoto/generate_katakoto.py podcast/script-YYYY-MM-DD.txt 16 /tmp/out.mp3
```

引数は「元の台本 / 使うターン数 / 出力先」。
`MIKA_VOICE` を変えれば他の訛り（`fr-FR-VivienneMultilingualNeural` など）も試せる。
