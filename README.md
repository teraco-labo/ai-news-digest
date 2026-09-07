# 世界一わかりやすいAIニュース

AIの最新ニュースを毎朝6時に自動収集し、日本語で要約して配信するシステム。
**企業名・ツール名・専門用語にはすべて解説がつく**のが他のニュースまとめとの違いです。
サイト・ポッドキャスト・メールの3経路で届きます。

## 動いているもの

- **日次ダイジェスト** — RSS/Hacker Newsから収集 → 5カテゴリに分類 → Claude Haikuで日本語要約 → HTML生成
- **ポッドキャスト** — 対話形式の台本を生成 → `edge-tts` で音声化 → RSS配信
- **メール配信** — 毎朝Gmailで送信
- **AI用語集** — 記事中の専門用語を自動でマークし、ホバー（PC）/タップ（スマホ）で解説を表示。
  解説ページの中の用語にもさらに解説がつく入れ子構造。毎朝のキュレーションで用語が自動追加される
- **解説記事** — `articles/*.md` から静的HTMLを生成（検索流入用）
- **SNS投稿キット** — その日のダイジェストからコピペ用の投稿文を生成
- **セミナー議事録**（手動実行）— Zoom等の録画から文字起こし・議事録・タイムスタンプ付き要約を作り、
  内容にそのまま質問できる。限定公開の動画が NotebookLM に読めない問題への回答

セミナー議事録以外は GitHub Actions で毎朝6時（JST）に全自動実行されます。

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env    # APIキーを設定
```

必要な GitHub Secrets: `NEWS_API_KEY`, `GMAIL_ADDRESS`, `EMAIL_PASSWORD`
推奨: `CLAUDE_CODE_OAUTH_TOKEN`（`claude setup-token` で発行 — 記事の選別・日本語化を Max プランの月額内で実行）
予備: `CLAUDE_API_KEY`（トークン未設定時に従量課金 API へフォールバック）

## よく使うコマンド

```bash
python generate_news.py                  # ダイジェストを生成（全工程）
python generate_news.py --date 2026-07-16

python seo_builder.py                    # サイト再構築（トップ/アーカイブ/用語集/sitemap/RSS/記事）
python glossary.py                       # 用語ページだけ再生成
python article_builder.py --preview      # 解説記事の下書きプレビュー
python social_kit.py                     # SNS投稿文を生成
python social_kit.py --backfill 30       # 過去30日ぶんをまとめて生成

python monetize.py                       # 収益化設定の状態を確認
python revenue_tracker.py report         # 収支レポート
python revenue_tracker.py plan           # 目標達成までの逆算

python api_dashboard.py                  # APIコストの確認

python seminar_notes.py <録画URL> --title "勉強会"   # セミナーの文字起こし＋議事録
python seminar_notes.py --ask "料金の話はどこ？"     # 録画の内容に質問する
```

## 経緯と現状

**[PROJECT_LOG.md](PROJECT_LOG.md)** に、何をなぜそうしたか・ハマった罠・
次にやることをまとめています。作業を再開するときはここから。

## セミナーの録画から議事録を作る

録画を文字起こしして議事録・要約・配布メール文面まで作り、内容に質問できるようにする手順は
**[SEMINAR_NOTES.md](SEMINAR_NOTES.md)** にまとめています。
NotebookLM が限定公開の YouTube を読み込めない理由と回避策もそこに書いてあります。

## 記事を書く

解説記事に自分の言葉を入れる方法は **[WRITING.md](WRITING.md)** にまとめています。
一番ラクなのは Claude に話すだけの方法です。

## 収益化について

設定と手順は **[MONETIZATION.md](MONETIZATION.md)** を参照。
戦略の背景と判断材料は **[STRATEGY_BRIEF.md](STRATEGY_BRIEF.md)** にまとめています。

収益化の設定はすべて `monetize_config.json` に集約されており、
**アフィリエイトURLが未設定の案件は一切表示されません**（空の広告枠は出ません）。
