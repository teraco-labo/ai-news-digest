# このリポジトリで作業するときに、最初に読むこと

## プロジェクト

**世界一わかりやすいAIニュース** — AIニュースを毎朝6時に自動収集し、日本語で要約して
サイト・ポッドキャスト・メールで配信する。専門用語にすべて解説が付くのが差別化。
経緯・決定事項・ハマった罠は **[PROJECT_LOG.md](PROJECT_LOG.md)** に全部ある。

## ナレッジ（運営者の「AIに覚えておいてほしいこと」）

Claude はセッションが終われば会話を忘れる。**リポジトリのファイルに書いたものだけが残る。**
イケハヤさん・テツメモさん・Fujin さんの発信や、会話で「覚えといて」と言われたことは `knowledge/` に貯めてある。

### いつ、何を読むか

| こんなとき | 読むもの |
|---|---|
| セッションの最初 | `knowledge/INDEX.md`（一覧だけ。本文は無い） |
| 助言・設計・実装をするとき | 関係する語で `python knowledge.py search <語>` → 使うものを `python knowledge.py show <ID>` |
| 作業が ✅採用 の項目の話題に触れるとき | その項目を `show` で読んで、**必ず従う**（運営者が試して採用したルール） |
| 運営者に「最近何を覚えた？」と聞かれたとき | `python knowledge.py report --since 7` |

確からしさ（INDEX の末尾の記号）を混同しないこと。
事＝検証済み（事実として使ってよい）／主＝出典の主張（「〜と言われている」と断る）／意＝意見・体験（一般則にしない）。

### 運営者が「覚えといて」と言ったとき

その場で `python knowledge.py add ...`（複数なら `--json -`）で記録する。会話に残しただけでは消える。

- 入れるのは今後の判断に効くものだけ。その日限りのニュースは入れない
- **出典の本文を貼らず、自分の言葉で要約する**（公開リポジトリ。`knowledge/inbox/` は .gitignore 済み）

### 「真似してみよう」→「良かったら覚えて」の流れ

1. 試すと決めたら `python knowledge.py try <ID> --note "何をどう試すか"`
2. 良かったら `python knowledge.py adopt <ID> --note "何が良かったか"` → INDEX の先頭に ✅ で載り、以後のセッションで守るルールになる
3. 合わなかったら `python knowledge.py reject <ID> --note "理由"`

運営者のAI（Amber＝別の場所で動いている Claude Code）に覚えてもらう＝ここで ✅採用 にすること。採用したものは `knowledge/AMBER.md` に本文ごと書き出され、Amber はそれを取り込む。

## よく使うコマンド

```bash
python generate_news.py              # ダイジェスト生成（全工程）
python seo_builder.py                # サイト再構築
python knowledge_ingest.py run       # ニュースレター取り込み→蒸留→索引更新
python knowledge.py search <語>      # 蓄積から探す
python knowledge.py show <ID>        # 1件の本文
python knowledge.py report --since 7 # 直近の報告
python knowledge.py stats            # 何がどれだけ溜まっているか
```

## この人の書き方の好み

- 文体は敬体（です・ます）。常体と混ぜない
- 専門用語は必ず開く。中学英語の範囲で読めることが基準
- カタカナ語を不自然に分かち書きしない
- 失敗談と数字を入れる（→ WRITING.md）
