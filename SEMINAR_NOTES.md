# セミナー録画を「AIに質問できる状態」にする

Zoom で講座をやって録画し、あとから議事録・タイムスタンプ付き要約を作り、
内容について AI に質問する——そのための手順とツールのまとめです。

## なぜ NotebookLM に YouTube を貼ると弾かれるのか

NotebookLM の YouTube ソースには条件があります。

| 条件 | 内容 |
|---|---|
| 公開範囲 | **一般公開**の動画のみ。限定公開・非公開は対象外 |
| 字幕 | **字幕（自動生成でも可）が付いている**こと。無い動画は追加できない |
| 経過時間 | 投稿から **72時間**以内はインポートに失敗することがある |
| 取り込む中身 | **字幕テキストだけ**。映像・音声は読まれない |

重要なのは最後の行です。**NotebookLM は動画を文字起こししていません。**
YouTube が持っている字幕データをそのまま取り込んでいるだけなので、
字幕が無ければ渡すものが無く、エラーになります。

セミナー録画はふつう限定公開にするので、この時点で条件から外れます。
「YouTubeぶっこんでも認識できない」のはこれが理由で、設定の問題ではありません。

**回避策は昔から決まっていて「文字起こしをテキストとして渡す」です。**
限定公開のままでも、文字起こしのテキストなら NotebookLM のソースにできます。

## このリポジトリのツール

`seminar_notes.py` が、文字起こしを取ってくるところから議事録を書くところまでやります。

```bash
python3 -m pip install -r requirements.txt

# 録画から一式（文字起こし＋議事録）を作る
python3 seminar_notes.py https://youtu.be/XXXXXXXXXXX --title "第3回 社内勉強会"

# Zoom のクラウド録画から直接（YouTubeにアップし直さなくていい）
python3 seminar_notes.py --zoom-list                          # まず一覧で選ぶ
python3 seminar_notes.py --zoom "<会議ID>" --title "第3回 社内勉強会"

# 手元に録画ファイルがあるならそれでもいい（Zoomのローカル録画など）
python3 seminar_notes.py ./recording.m4a --title "Zoom録画（2026-08-27）"

# 文字起こしが既にあるなら、それを渡すのが一番速い（.txt / .vtt / .srt）
python3 seminar_notes.py ./transcript.txt --title "第3回 社内勉強会"

# 限定公開でログインが要る場合はブラウザのCookieを借りる
python3 seminar_notes.py <URL> --cookies-from-browser chrome

# できたものに質問する（NotebookLMの代わり）
python3 seminar_notes.py --ask "MCP版とAPI版の違いは？"
python3 seminar_notes.py --ask "料金の話はどこ？" --slug 2026-08-27-勉強会

# 重点を指定する（ツールの使い方が中心の回など）
python3 seminar_notes.py <URL> --title "..." --focus "ツールの使い方を手順まで詳しく"

# 保存済みの一覧
python3 seminar_notes.py --list

# 急ぐとき（クラウドで文字起こし。鍵と費用が要り、音声が外に出る）
python3 seminar_notes.py ./recording.m4a --title "..." --cloud-transcribe
```

### 出力

`seminars/<スラッグ>/` に3つ出ます。

- **`transcript.txt`** — タイムスタンプ付きの文字起こし。
  これを NotebookLM の「テキストを貼り付け」に渡せば、限定公開のままソースにできます
- **`notes.md`** — 議事録・タイムスタンプ付き要約・決まったこと・
  ネクストアクション・**参加者への配布メール文面**。
  ツールの操作説明があった回は **「ツールの使い方」** も付きます
  （番号付きの手順＋各手順のタイムスタンプ＋設定値の原文＋つまずきポイント）
- **`notes.html`** — `notes.md` を読む用にしたもの。タイムスタンプが拾いやすく、
  そのまま画面に出して読めます。議事録を作ると自動で付いてきます
- **`meta.json`** — 元URL・取得方法・文字数の記録

さらに `seminars/index.html` に**全部の回の目次**ができます（新しい順）。
会が増えても「あの話はどの回か」を探せるように、議事録を作るたびに更新されます。
手で作り直すときは `python3 seminar_notes.py --index`。

セミナーの中身は社外に出せないことが多いので、`seminars/` は `.gitignore` 済みです。
GitHub には上がりません。

**このフォルダ自体を外に置きたい場合**は、`.env` に1行足せば出力先が変わります。

```
SEMINAR_NOTES_DIR=/Users/shuichifujisaki/Documents/セミナー議事録
```

このリポジトリは公開サイトのものなので、社外秘の文字起こしをフォルダの中に
置きたくない場合はこちらを使ってください。

### 文字起こしの取り方

上から順に試して、通ったところで止まります。

0. **手元の文字起こしをそのまま読む** — `.txt` `.vtt` `.srt` を渡した場合
1. **Zoom のクラウド録画から取る** — Zoom 自身が作った文字起こし。**話者名が入る**
2. **YouTube の字幕を API で取得** — 限定公開でも字幕さえあれば通る。無料・数秒
3. **yt-dlp で自動生成字幕を取得** — 2が塞がれたときの予備
4. **音声から文字起こしする** — 字幕が無い動画・ローカル録画用

**4 は既定で Mac の中だけで処理します**（`whisper`）。鍵も費用も要らず、
セミナーの音声が外に出ません。代償は時間で、**録画の再生時間とだいたい同じくらい**
かかります（1時間の録画で1時間弱）。

急ぐときだけ `--cloud-transcribe` を足すとクラウド（Gemini）で数分で終わります。
そのかわり `GEMINI_API_KEY` が要り、費用がかかり、音声が Google に渡ります。
**社外に出せない録画では既定のまま（Mac の中）にしてください。**

0〜3 と 4 の既定は、追加費用ゼロです（1 は Zoom の設定が要ります）。

ローカルの `whisper` が入っていない場合は `brew install openai-whisper` で入ります。
使うモデルは `WHISPER_MODEL`（既定 `turbo`）で変えられます。

**録画が Zoom にあるなら 1 が一番いい。** 理由は3つ。YouTube にアップし直す手間が
要らない、AIに文字起こしさせる費用がかからない、そして **誰の発言かが残る**。
話者名が入ると、議事録のネクストアクションに担当者が自動で埋まります。

### Zoom のクラウド録画を使う準備

Zoom の設定をしなくても使う方法と、一度だけ設定して自動化する方法があります。

**(A) 設定なしで今すぐ**

Zoom のウェブ画面で録画を開き、「音声文字起こし」の VTT ファイルをダウンロードして、
そのファイルを渡すだけです。

```bash
python3 seminar_notes.py ~/Downloads/GMT20260825-020000_Recording.transcript.vtt \
  --title "9月の運営ミーティング"
```

**(B) 一度だけ設定して自動化する**

毎回ダウンロードするのが面倒なら、Zoom に「サーバー間 OAuth アプリ
（Server-to-Server OAuth App）」を1つ作ります。プログラムから Zoom の録画を
読むための鍵で、作れるのは Zoom アカウントの管理者だけです。

1. [Zoom App Marketplace](https://marketplace.zoom.us/) にログイン
2. 右上の「Develop」→「Build App」→ **Server-to-Server OAuth** を選ぶ
3. 名前を付けて作成すると、**Account ID / Client ID / Client Secret** の3つが出る
4. 「Scopes」で `cloud_recording:read:list_user_recordings` と
   `cloud_recording:read:recording` を追加する
5. 「Activate your app」で有効化する
6. リポジトリの `.env` に3つを書く

```
ZOOM_ACCOUNT_ID=（Account ID）
ZOOM_CLIENT_ID=（Client ID）
ZOOM_CLIENT_SECRET=（Client Secret）
```

`.env` は `.gitignore` 済みなので、GitHub には上がりません。

なお **Zoom の文字起こしは、有料プランでクラウド録画＋音声文字起こしをオンに
している場合だけ作られます。** オフだと録画はあっても文字起こしが無く、その場合は
音声から起こす（`GEMINI_API_KEY` が要る）ほうに自動で落ちます。

### ネットワークが YouTube を塞いでいる環境では

会社のプロキシやクラウド実行環境が YouTube への接続を禁止していると、1〜3 は
どれも通りません（`403 Forbidden` で止まります）。その場合は 0 を使います。

YouTube の動画ページで 説明欄の「...もっと見る」→「文字起こしを表示」を開き、
右側に出るテキストをコピーしてファイルに保存すれば、それを渡すだけで
議事録まで進められます。

議事録の作成と質問への回答は Claude が担当します。`claude` CLI がログイン済みなら
サブスクリプションの枠で動き、無ければ `ANTHROPIC_API_KEY` の従量課金に落ちます
（`curate.py` と同じ仕組み）。

## 運用の流れ

1. Zoom で録画する
2. **クラウド録画なら、そのまま次へ。** ローカル録画なら YouTube に限定公開でアップ
   するか、録画ファイルをそのまま使う
3. `python3 seminar_notes.py --zoom-list` でどの録画かを選び、
   `python3 seminar_notes.py --zoom "<会議ID>" --title "..."`
   （YouTube・ファイルの場合は `python3 seminar_notes.py <URL or ファイル> --title "..."`）
4. `notes.md` の議事録を Google ドキュメントに貼って、必要なら手直しする
5. `notes.md` の末尾にあるメール文面に、議事録URLと録画URLを差し込んで送る
6. あとから内容を確認したくなったら `--ask` で質問する。
   NotebookLM を使いたい場合は `transcript.txt` をソースとして貼り付ける

## つまずきどころ

| 症状 | 対処 |
|---|---|
| 字幕APIで取れない | 動画に字幕が無い。`--audio` で音声から文字起こしする |
| 限定公開でダウンロードできない | `--cookies-from-browser chrome` でログイン状態を借りる |
| 音声の文字起こしが遅い | Mac の中で処理しているため、録画の長さとだいたい同じ時間かかる。急ぐなら `--cloud-transcribe`（鍵と費用が要る） |
| 「whisper が入っていない」と出る | `brew install openai-whisper` で入れる |
| 無音のところに「ご視聴ありがとうございました」等が混ざる | whisper が無音を埋めようとする癖。議事録側では無視されるが、文字起こしを直接配るときは消す |
| 議事録が作られない | `claude` CLI がログイン済みか、`ANTHROPIC_API_KEY` があるか確認する |
| 話者が「講師」「参加者」になる | 音声からの文字起こしは話者名を推測できない。`notes.md` で手で直す |
| 人名が聞き取り違いで崩れている | YouTube の自動字幕はよくある。Zoom の文字起こしなら話者名が正しく入る。配布前に名前だけ直す |
| Zoom の録画が見つからない | `--zoom-list --zoom-days 90` で期間を広げる。共有リンクではなく会議IDを渡すと確実 |
| Zoom に文字起こしが無い | 有料プランで「音声文字起こし」がオンのときだけ作られる。オフなら音声から起こすので `GEMINI_API_KEY` が要る |

## 参考

- [Add or discover new sources for your notebook — Gemini Notebook Help](https://support.google.com/gemininotebook/answer/16215270?hl=en&co=GENIE.Platform%3DDesktop)
- [限定公開YouTube動画をNotebookLMに渡す「無理のない」運用術（Zenn / SoftBank）](https://zenn.dev/softbank/articles/22ef4a4bc3aec4)
- [NotebookLMで動画を読み込む方法｜YouTube・MP4・200MB超の対処法](https://skillstack-lab.com/notebooklm-video/)
