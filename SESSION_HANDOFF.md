# セッション引き継ぎメモ（2026-10-04 時点）

このファイルは、「世界一わかりやすいAIニュース」構築セッションでやったことを
**別のセッション（別のClaude）に引き継ぐため**のまとめです。
詳しい経緯は `PROJECT_LOG.md`、プロジェクトの約束事は `CLAUDE.md` を先に読むこと。

---

## 1. このプロジェクトの目的

- 持ち主（てらこ先生・非エンジニア）の Claude Code Max プラン費用（月約3万円）を
  回収するための**不労所得（アフィリエイト）システム**を作る
- 手段：毎朝自動生成のAIニュースサイトを育て、高単価ASP案件＋読者リスト（メルマガ）で収益化
- サイト名：**世界一わかりやすいAIニュース**（旧・てらこAIニュースダイジェスト）
- キャッチコピー：**「読むだけで賢くなる」**
- 将来：`news.teraco-labo.com` サブドメインへ移行（DNS設定待ち）、海外版（英・中・西）も構想あり

## 2. いまの状態（すべて稼働中）

- **本番URL**: https://teraco-labo.github.io/ai-news-digest/
- **毎朝6時（日本時間）に GitHub Actions が自動実行**：
  記事収集 → Claude による選別・日本語化（8〜12件）→ 用語解説の自動付与 →
  ポッドキャスト音声 → サイト全体再構築 → SNS投稿文生成 → 自動コミット＆プッシュ
- Claude の呼び出しは **`claude` CLI（サブスクリプション枠＝追加費用ゼロ）が最優先**。
  GitHub Secrets の `CLAUDE_CODE_OAUTH_TOKEN` で認証。API従量課金へのフォールバックは
  `curate.py` の `_curate_via_cli` が基準実装
- 用語集は118語（企業・モデル・チップ・著名人・VC・メディア等）。毎朝の生成時に
  新しい用語を最大8語まで自動発見して追加する仕組みが動いている

## 3. サイト設計の核（変更するとき必ず守る）

### 二層構造の原則（持ち主の言葉が根拠）
> 「一応世界一って名乗ってるんで、そこまでわかりやすくなくてもいいでしょって
> 言われる位丁寧でいい。**仕組みだけはね。文章まで馬鹿みたいに丁寧にすると
> 中級の方抜けていく**」

- **本文（記事の要約）は中級者向けの筆致を保つ。レベルを下げない**
- **やさしさは全部「用語レイヤー」が引き受ける**：
  色付き用語 → PCはマウスを乗せるとポップアップ、スマホはタップで下からシート表示
  → クリックで用語の詳細ページ（解説の中の用語にもさらにフォローが付く入れ子構造）
- 用語を拾う基準：「日常生活で聞き慣れない言葉かどうか」。**迷ったら拾う**。
  AI名・企業名・モデル名・著名人名はすべて対象。この方針は `curate.py` の
  プロンプトに書き込み済みなので、毎朝自動で適用される

### UI/UX の決まりごと
- **トップページ＝今日のニュースそのもの**（「最新号を読む」ボタンを挟まない）
- 音声プレイヤーは最上部・再生速度ボタン付き（0.75〜2.5倍・既定1倍）。記事ページ内の簡易版と、メールから開く `podcast/player.html`（`player_page.py` が毎回生成・同じ見た目）の2つがあり、速度の記憶は共通
- ジャンルごとアコーディオン、上下にナビゲーション
- 「RSS」という言葉は一般読者に通じないので前面に出さない。
  「ニュースレター」「メールマガジン」表現を使う（RSSは上級者向けの一行のみ）

## 4. 持ち主とのやりとりのルール（最重要・全プロジェクト共通）

- **持ち主は非エンジニア**。専門用語はその場で一言そえる。手順を渡して終わりにせず、
  こちらで実行できることは実行する（詳細は `CLAUDE.md`）
- **見た目の変更をしたら、毎回必ず2点セットで提示**：
  1. プレビュー用アーティファクト（**この固定URLに上書き更新**。新規作成しない）：
     https://claude.ai/code/artifact/3dcc7ea2-521f-4cc9-a8f8-17cc625a3b2e
     作り方：`index.html` の相対リンクを本番の絶対URLに書き換え、上部に
     「プレビューです」の帯を付けたコピーを発行する
  2. 本番URL：https://teraco-labo.github.io/ai-news-digest/
  - **ファイル添付は禁止**（受け取り側でダウンロード扱いになり開けない）
- このルールは他の5リポジトリ（teraco-labo-website-v2 / line-outou /
  teraco-prompt-engineering / fins / teraco-money※AGENTS.md側）にも配布済み
- API を使ったら `api_cost_calculator.record_anthropic_usage` で必ず記録。
  黙って課金を増やさない
- 設計やアイデアで改善できる点を見つけたら**積極的に提案してよい**（持ち主の依頼）

## 5. 主なファイル（触るときの入口）

| ファイル | 役割 |
|---|---|
| `generate_news.py` | 毎朝の全工程の親玉。ブランチを自動判定してプッシュ |
| `curate.py` | Claude による記事選別・日本語化・新用語発見。CLI優先の2段構えの基準実装 |
| `glossary.py` | 用語集（`glossary.json` 118語）と、本文への色付きマーク付与・ツールチップ |
| `digest_page.py` | 日刊号ページの見た目。`build_sections()` はトップページと共用 |
| `seo_builder.py` | トップ・アーカイブ・RSS・sitemap などサイト全体の再構築 |
| `site_theme.py` | 共通の枠・CSS・購読ブロック・言語切替（準備中バッジ） |
| `newsletter.py` | メール用HTML（全部インラインスタイル。JS不可なので用語はまとめブロック） |
| `social_kit.py` | X投稿文・note下書き。過去号HTMLを再解析するのでclass名の変更に注意 |
| `rerender.py` | 過去号をClaude費用ゼロで再レンダリング |
| `article_builder.py` | 読み物（記事）のビルド。`✍️` マーカーが残っていると公開されない |
| `monetize_config.json` | サイト名・URL・案件・ニュースレター等の一元設定 |

## 6. ハマりどころ（同じ穴に落ちないこと）

| 罠 | 対処 |
|---|---|
| `ANTHROPIC_API_KEY` が古いと CLI の OAuth トークンより優先されて401になる | トークンがあるときは API キー系の環境変数を除去（`_curate_via_cli` 参照） |
| GitHub Pages は workflow 成功≠公開完了（最大1時間遅れ） | deployments API の status=success を確認してから「反映済み」と報告する |
| CNAME ファイルを DNS 設定より先に置くとサイト全体が404 | 必ず DNS → CNAME の順（`DOMAIN_SETUP.md`） |
| アーティファクトでは `<base>` タグが無視される | 相対リンクを全部絶対URLに書き換える |
| f-string の中のバックスラッシュ（Python 3.11） | 変数に事前に切り出してから埋め込む |
| クラウドセッション（スマホ等から起動）では持ち主のブラウザを操作できない | ログイン済み画面での操作が必要な作業は、Mac のローカルセッションで行う |
| `social_kit` は生成後のHTMLを正規表現で再解析している | カードのclass名や構造を変えたら round-trip テストをする |

## 7. 残っている作業（持ち主のアカウント作業待ち）

### 7-0. ポッドキャスト音声を Cloudflare R2 へ移す（2026-10-05 ほぼ完了）

**なぜ**：mp3 をリポジトリに入れ続けると GitHub の推奨上限1GBを数か月で超える。
R2 は保存10GB・転送料無料で当面0円。持ち主承認済み（2026-10-04）。

**済んだこと（2026-10-05、Mac のローカルセッション）**
- R2 有効化（カード登録は持ち主本人）、バケット `ai-news-podcast`（APAC・標準）、公開URL
  `https://pub-59f9285441114b44af1b246d89bf3b21.r2.dev`（r2.dev＝開発用・レート制限あり）
- アカウントAPIトークン「ai-news-digest podcast」（Admin Read & Write・無期限）
- 鍵の置き場：GitHub Secrets（`R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `CLOUDFLARE_API_TOKEN`）と
  **Mac のキーチェーン**（サービス名 `teraco-r2`、アカウント名は同じ4つ）。値は会話に出していない
- `podcast_store.py` を新設。音声URLの決め方・R2 へのアップロード・台帳 `podcast/audio.json` を一本化。
  R2 に上げられない日は従来どおり `podcast/` に置く保険（台帳 where=site、コミット時 `git add -f`）
- 音声の有無の判定を台帳に変更（seo_builder / generate_news / rerender / newsletter / podcast_teraco_voice）
- `update_feed` の中で R2 へ上げる（クラウドの朝の処理も、Mac の本人の声への差し替えも同じ道を通る）
- **guid は固定**：episodes.json に `guid`（元のURL）を保存し、feed.xml の guid はそれを使う。移行前後で60件一致を確認
- 既存115本をアップロード、feed.xml の enclosure 60件と過去号115ページの音声URLを R2 に差し替え（本番反映・取得確認済み）
- `.gitignore` に `podcast/ai-news-*.mp3`。workflow に R2 の Secrets を渡す。requirements に boto3
- Mac の差し替えジョブ `~/ai-office/bin/teraco-voice-podcast.sh` を、mp3 をコミットしない形に変更
  （元は `.bak-20261005`）。作業用の複製 `~/ai-office/work/ai-news-digest/venv` に boto3 を入れた
- gh の認証には workflow 権限が無いので、workflow ファイルを含む push は SSH（`git@github.com:`）で行った

**残り**
1. 10/6 朝の自動実行と Mac の差し替えで、新しい回が R2 に載るか確認（`podcast/audio.json` の where が r2、
   GitHub Actions のログに「音声を R2 へ」）
2. Spotify で新しい回と過去の回が再生でき、重複していないことを確認
3. 確認できたら、リポジトリの mp3 を `git rm --cached` で消す（R2 にあることは `python3 podcast_store.py check` で確認）。
   **過去の履歴（約720MB）の書き換えは持ち主の同意なしにやらない**
4. 将来：r2.dev から独自ドメイン（Cloudflare の DNS 管理下が必要）へ。まだ持ち主に説明していない

### 7-1. それ以外（以前からの持ち越し）

こちらの実装は完了済み。持ち主が登録したら値を `monetize_config.json` に入れるだけ。

1. ~~Kit~~ → **Substack に変更・接続済（2026-09-04）**。既存媒体 teracosensei.substack.com のセクション「世界一わかりやすいAIニュース」を使う。RSS自動配信は無いので、週1で Substack に投稿する運用（`NEWSLETTER_SETUP.md` 末尾）
2. ~~Spotify~~ **済（2026-09-04 再登録、`podcast.spotify_url` 設定済）**。**Apple Podcasts** は未登録 → 番組URLをもらう
3. **GA4** の測定IDをもらう（現状アクセス数がゼロ件も測れていない。最優先で推奨）
4. **Search Console** に sitemap.xml を登録
5. **A8.net** 等のASP登録 → 承認された案件URLを `offers` に貼る
6. DNS で `news` → `teraco-labo.github.io.` の CNAME 設定（順序厳守）

提案済み・返事待ちのアイデア：号ごとのOGP画像自動生成、日曜の週間まとめ号。

## 8. 使わなくなったもの

- 旧セッション（てらこAIニュースダイジェスト作り込み）は引退。以後この仕組みで完結
- 未マージブランチ `mcareer-briefing-chatwork-h4yh3y` / `remotion-install-1bnjrv` は
  **記録として GitHub に残すだけ**。マージも削除もしない（持ち主の指示）
