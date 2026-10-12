#!/usr/bin/env python3
"""
ニュースレター取り込み — Gmail に届いた注目の差出人を読み、知見だけを残す。

## 流れ

    fetch   Gmail(IMAP) と RSS（Substack など）から取得 → knowledge/inbox/*.md に保存
    distill 保存したメールを Claude が読み、要点だけを knowledge.json に記録
    run     fetch → distill → INDEX.md 再生成 まで一気に

## 誰を見るか

`monetize_config.json` の `knowledge.watch` に書きます（既定はイケハヤさん・テツメモさん）。
コードを触らずに追加・削除できます。1人につき、メールの差出人（senders）と
RSS（feeds）の両方を持てます。メールで届かない発信（Substack の投稿など）は feeds で追います。

## 認証

日次ダイジェストのメール送信と同じ `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD`（アプリパスワード）を
そのまま使います。新しい鍵は要りません。読むだけで、削除も既読化もしません。

## 公開リポジトリなので

取り込んだメール本文は `knowledge/inbox/` に置かれ、**.gitignore で除外**されています。
他人の有料コンテンツを公開リポジトリに置かないためです。
コミットされるのは、自分の言葉に落とし込んだ要点（knowledge.json）だけ。

## 使い方

    python knowledge_ingest.py run                 # 取得して蒸留（毎朝の自動実行もこれ）
    python knowledge_ingest.py fetch --days 14
    python knowledge_ingest.py distill --limit 3
    python knowledge_ingest.py sources             # 見ている差出人
"""

import argparse
import email
import html as _html
import imaplib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from pathlib import Path
from typing import Dict, List, Optional

import knowledge
import monetize

REPO_DIR = Path(__file__).parent
INBOX_DIR = REPO_DIR / "knowledge" / "inbox"
JST = timezone(timedelta(hours=9))

DEFAULT_WATCH = [
    {"name": "イケハヤ", "senders": ["info@mag.ikehaya.com", "info@ikemag.jp"]},
    {"name": "テツメモ", "senders": ["tetumemo@m-newsletter.com"]},
]

MAX_BODY_CHARS = 14000   # Claude に渡す本文の上限（長い号は前半で十分要点が出る）
DEFAULT_LOOKBACK = 7
DEFAULT_MAX_PER_RUN = 4

DISTILL_PROMPT = """あなたは、あるエンジニア（個人開発者）の「学びの記録係」です。
届いたニュースレターを読み、**本人が今後の判断に使える知見だけ**を抜き出して記録します。

## 記録する人の状況

「世界一わかりやすいAIニュース」という個人サイトを運営しています。
- AIニュースを毎朝自動収集し、Claude が日本語で書き、サイト・ポッドキャスト・メールで配信
- 全工程が GitHub Actions で自動化され、Claude Code のサブスク枠で動いている
- 目的は Claude Code の月額（約3万円）をサイト収益で賄うこと
- 収益は「解説記事・用語ページで検索流入 → 高単価ASP」の設計。日次ニュースでは検索で戦わない
- 人力でやるのは SNS 投稿と週1本の記事執筆だけ

## 抜き出す基準

**残すもの**
- 使える道具・手法（ツール名、Skill やプロンプトの設計、自動化の型）
- 運営・発信・収益化の考え方で、根拠や数字があるもの
- 失敗談とその原因（これが一番価値がある）

**捨てるもの**
- 単なる商品の宣伝・値段・部数の告知
- その日限りのニュース（このサイトが自前で扱うので不要）
- 中身のない精神論

抜き出すものが無ければ `entries` を空配列にしてください。**無理に埋めないこと。**
1通から取るのは多くても3件です。

## 書き方

- **本文をそのまま引用しない。** 有料コンテンツなので、必ず自分の言葉で要約する
- summary は2〜4文。「何の話か」「なぜ効くか」が分かること
- takeaways は箇条書きで、あとから読んで意味が通る具体的な文にする
  （×「Skill が便利」→ ○「教材を Skill 化するとき、教材本体は書き換えず"合わせ込み"の Skill を別に作ると更新に強い」）
- apply は**このプロジェクトに具体的に効く場合だけ**書く。無ければ空配列
- confidence は次から選ぶ:
    fact    … 一次情報・公式仕様など、確かめられる事実
    claim   … 出典が主張しているが未検証（ニュースレターの多くはこれ）
    opinion … 個人の意見・体験談
- tags は日本語で1〜3個（例: 自動化, 収益化, コンテンツ運用, Claude Code, 動画生成）

## 出力形式

次の JSON だけを出力してください。前置き・説明・コードフェンスは付けないこと。

{"entries": [{"title": "...", "summary": "...", "takeaways": ["..."], "apply": ["..."], "tags": ["..."], "confidence": "claim"}]}
"""


# ------------------------------------------------------------------ 設定

def config() -> Dict:
    return monetize.load_config().get("knowledge", {}) or {}


def watch_list() -> List[Dict]:
    entries = config().get("watch") or DEFAULT_WATCH
    return [w for w in entries if w.get("senders") or w.get("feeds")]


def sender_name(address: str) -> str:
    """差出人アドレスから、設定した呼び名を引く。"""
    address = address.lower()
    for watched in watch_list():
        for sender in watched.get("senders", []):
            if sender.lower() in address:
                return watched.get("name", sender)
    return address


# ------------------------------------------------------------------ メール取得

def _decode(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _html_to_text(raw: str) -> str:
    """HTML メールを読める素のテキストにする（完璧でなくてよい。要点が取れれば十分）。"""
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _body_of(message) -> str:
    """本文を取り出す。text/plain を優先し、無ければ HTML を落として使う。"""
    plain, rich = "", ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if "attachment" in str(part.get("Content-Disposition", "")):
                continue
            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except Exception:
                continue
            if part.get_content_type() == "text/plain" and not plain:
                plain = decoded
            elif part.get_content_type() == "text/html" and not rich:
                rich = decoded
    else:
        try:
            charset = message.get_content_charset() or "utf-8"
            decoded = (message.get_payload(decode=True) or b"").decode(charset, errors="replace")
        except Exception:
            decoded = ""
        if message.get_content_type() == "text/html":
            rich = decoded
        else:
            plain = decoded

    text = plain.strip() or _html_to_text(rich)
    # 配信解除リンクや追跡URLは知見ではないので落とす
    text = re.sub(r"https?://\S{60,}", "[URL]", text)
    return text.strip()


def _slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^\w぀-ヿ一-鿿]+", "-", text).strip("-")
    return (cleaned[:limit] or "mail").lower()


def fetch(days: int = DEFAULT_LOOKBACK, verbose: bool = True) -> List[Path]:
    """対象の差出人からのメールを取り込み、inbox に保存する。読むだけで何も変更しない。"""
    address = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not address or not password:
        if verbose:
            print("⚠️  GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定のため取り込みをスキップします")
            print("   （日次メール配信と同じアプリパスワードをそのまま使えます）")
        return []

    watched = watch_list()
    if not watched:
        if verbose:
            print("   監視対象の差出人が設定されていません")
        return []

    since_date = (datetime.now(JST) - timedelta(days=days)).strftime("%d-%b-%Y")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    try:
        server = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        server.login(address, password)
    except imaplib.IMAP4.error as e:
        if verbose:
            print(f"⚠️  Gmail(IMAP) にログインできませんでした: {e}")
            print("   → Gmail の設定で IMAP が有効か、アプリパスワードが正しいか確認してください")
        return []
    except Exception as e:
        if verbose:
            print(f"⚠️  Gmail への接続に失敗しました: {e}")
        return []

    try:
        server.select("INBOX", readonly=True)
        for target in watched:
            for sender in target.get("senders", []):
                try:
                    status, data = server.search(None, f'(FROM "{sender}" SINCE "{since_date}")')
                except Exception as e:
                    if verbose:
                        print(f"   ⚠️  検索に失敗（{sender}）: {e}")
                    continue
                if status != "OK" or not data or not data[0]:
                    continue
                for uid in data[0].split():
                    saved_path = _save_one(server, uid, target.get("name", sender), verbose)
                    if saved_path:
                        saved.append(saved_path)
    finally:
        try:
            server.close()
        except Exception:
            pass
        server.logout()

    if verbose:
        print(f"✓ 新しく取り込んだメール: {len(saved)} 通")
    return saved


def _gmail_id(raw_header: bytes) -> str:
    """X-GM-MSGID（10進）を Gmail の画面やAPIと同じ16進IDに直す。

    こうしておくと、Claude が Gmail を直接読んで記録した知見と、
    この取り込みが拾った同じメールが、同じ ref になって重複しない。
    """
    match = re.search(rb"X-GM-MSGID\s+(\d+)", raw_header or b"")
    return format(int(match.group(1)), "x") if match else ""


def _save_one(server, uid: bytes, name: str, verbose: bool) -> Optional[Path]:
    try:
        status, data = server.fetch(uid, "(X-GM-MSGID RFC822)")
    except Exception:
        return None
    if status != "OK" or not data or not isinstance(data[0], tuple):
        return None

    message = email.message_from_bytes(data[0][1])
    gmail_id = _gmail_id(data[0][0])
    message_id = gmail_id or (message.get("Message-ID") or f"uid:{uid.decode()}").strip("<> ")
    ref = f"gmail:{message_id}"
    if knowledge.has_ref(ref):
        return None   # もう蒸留済み

    subject = _decode(message.get("Subject"))
    try:
        published = email.utils.parsedate_to_datetime(message.get("Date")).astimezone(JST).strftime("%Y-%m-%d")
    except Exception:
        published = knowledge.today()

    path = INBOX_DIR / f"{published}-{_slug(name)}-{_slug(subject, 30)}.md"
    if path.exists():
        return None

    body = _body_of(message)
    if not body:
        return None

    path.write_text(
        "\n".join([
            f"source_name: {name}",
            f"subject: {subject}",
            f"published: {published}",
            f"ref: {ref}",
            "---",
            "",
            body,
        ]),
        encoding="utf-8",
    )
    if verbose:
        print(f"   + {name}「{subject[:50]}」")
    return path


# ------------------------------------------------------------------ RSS 取得

def _local(tag: str) -> str:
    """名前空間を外したタグ名（{http://...}encoded → encoded）。"""
    return tag.rsplit("}", 1)[-1]


def _parse_feed(content: bytes) -> List[Dict]:
    """RSS 2.0 / Atom を、同じ形の辞書のリストにする。

    Substack・note・YouTube はどれもこのどちらかで出しているので、
    標準ライブラリだけで読める。本文は全文（content:encoded / content）があればそれを、
    無ければ要約（description / summary）を使う。
    """
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields: Dict[str, str] = {}
        # 直下の子だけでなく子孫まで見る（YouTube の説明文は media:group の中にある）
        for child in node.iter():
            if child is node:
                continue
            name = _local(child.tag)
            if name == "link" and child.get("href"):          # Atom
                fields.setdefault("link", child.get("href"))
            elif child.text:
                fields.setdefault(name, child.text.strip())

        raw_date = fields.get("pubDate") or fields.get("published") or fields.get("updated") or ""
        published = ""
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date).astimezone(JST).strftime("%Y-%m-%d")
            except Exception:
                published = raw_date[:10]

        items.append({
            "title": fields.get("title", ""),
            "link": fields.get("link", "") or fields.get("guid", "") or fields.get("id", ""),
            "published": published,
            "body": fields.get("encoded") or fields.get("content") or fields.get("description") or fields.get("summary") or "",
        })
    return items


def fetch_feeds(days: int = DEFAULT_LOOKBACK, verbose: bool = True) -> List[Path]:
    """RSS を読んで inbox に保存する。メールで届かない発信を追うため。"""
    import requests

    threshold = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []

    for target in watch_list():
        name = target.get("name", "")
        for url in target.get("feeds", []):
            try:
                resp = requests.get(url, timeout=20, headers={"User-Agent": "ai-news-digest knowledge reader"})
                resp.raise_for_status()
            except Exception as e:
                if verbose:
                    print(f"   ⚠️  RSS を読めませんでした（{name}: {url}）: {e}")
                continue

            items = _parse_feed(resp.content)
            if not items and verbose:
                print(f"   ⚠️  RSS に記事が見つかりませんでした（{url}）")
            for item in items:
                if not item["link"] or (item["published"] and item["published"] < threshold):
                    continue
                ref = f"rss:{item['link']}"
                if knowledge.has_ref(ref):
                    continue
                path = INBOX_DIR / f"{item['published'] or knowledge.today()}-{_slug(name)}-{_slug(item['title'], 30)}.md"
                if path.exists():
                    continue
                body = _html_to_text(item["body"])
                if not body:
                    continue
                path.write_text("\n".join([
                    f"source_name: {name}",
                    f"subject: {item['title']}",
                    f"published: {item['published']}",
                    f"ref: {ref}",
                    "---",
                    "",
                    body,
                ]), encoding="utf-8")
                saved.append(path)
                if verbose:
                    print(f"   + {name}（RSS）「{item['title'][:50]}」")

    if verbose:
        print(f"✓ RSS から新しく取り込んだ記事: {len(saved)} 本")
    return saved


# ------------------------------------------------------------------ 蒸留

def _parse_inbox_file(path: Path) -> Dict:
    text = path.read_text(encoding="utf-8")
    header, _, body = text.partition("\n---\n")
    meta = {}
    for line in header.splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            meta[key.strip()] = value.strip()
    return {"meta": meta, "body": body.strip(), "path": path}


def _ask_claude(prompt: str, verbose: bool = True) -> Optional[Dict]:
    """キュレーションと同じ経路で Claude に聞く（サブスク枠 → API の順）。"""
    import curate

    exe = shutil.which("claude")
    if exe:
        env = os.environ.copy()
        # 失効した API キーが OAuth トークンより優先されて 401 になる罠を避ける
        if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("CLAUDE_API_KEY", None)
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
        cmd = [exe, "-p", "--output-format", "json",
               "--model", config().get("cli_model", "opus")]
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True,
                                  text=True, timeout=600, env=env)
            if proc.returncode == 0:
                try:
                    wrapper = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    wrapper = {"result": proc.stdout}
                if not wrapper.get("is_error"):
                    parsed = curate._extract_json(wrapper.get("result", ""))
                    if parsed is not None:
                        return parsed
            elif verbose:
                print(f"   ⚠️  Claude Code CLI がエラー（exit {proc.returncode}）→ API を試します")
        except subprocess.TimeoutExpired:
            if verbose:
                print("   ⚠️  Claude Code CLI がタイムアウト → API を試します")
        except Exception as e:
            if verbose:
                print(f"   ⚠️  Claude Code CLI の実行に失敗: {e}")

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        if verbose:
            print("   ⚠️  Claude を呼べません（CLI も API キーも無し）。蒸留は見送ります")
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=config().get("model", "claude-opus-5"),
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        return curate._extract_json("".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ))
    except Exception as e:
        if verbose:
            print(f"   ⚠️  API 経由の蒸留に失敗: {e}")
        return None


def _known_titles_block(source_name: str, limit: int = 60) -> str:
    """同じ発信者の記録済み知見のタイトル。

    同じ人がニュースレターと Substack で同じ話を書くことがあるので、
    既に持っている知見を見せて、重複して記録させないようにする。
    """
    titles = [e["title"] for e in map(knowledge._normalize, knowledge.entries())
              if e["source"]["name"] == source_name and not e["title"].startswith("（知見なし）")]
    if not titles:
        return ""
    lines = "\n".join(f"- {t}" for t in titles[-limit:])
    return ("この発信者から既に記録済みの知見（同じ内容は記録しないこと。"
            "新しい事実・数字・失敗談が加わっている場合だけ、差分として記録してよい）:\n"
            + lines + "\n\n")


def distill(limit: int = DEFAULT_MAX_PER_RUN, keep: bool = False, verbose: bool = True) -> int:
    """inbox のメールを読み、知見だけを knowledge.json に記録する。"""
    if not INBOX_DIR.exists():
        if verbose:
            print("   取り込み済みのメールがありません")
        return 0

    files = sorted(INBOX_DIR.glob("*.md"))
    if not files:
        if verbose:
            print("   取り込み済みのメールがありません")
        return 0

    added = 0
    for path in files[:limit]:
        item = _parse_inbox_file(path)
        meta, body = item["meta"], item["body"]
        ref = meta.get("ref", f"file:{path.name}")
        if knowledge.has_ref(ref):
            path.unlink(missing_ok=True)
            continue

        if verbose:
            print(f"   読んでいます: {meta.get('source_name', '?')}「{meta.get('subject', '')[:44]}」")

        prompt = (
            DISTILL_PROMPT
            + "\n---\n\n"
            + f"差出人: {meta.get('source_name', '')}\n"
            + f"件名: {meta.get('subject', '')}\n"
            + f"配信日: {meta.get('published', '')}\n\n"
            + _known_titles_block(meta.get("source_name", ""))
            + "本文:\n"
            + body[:MAX_BODY_CHARS]
        )
        data = _ask_claude(prompt, verbose=verbose)
        if data is None:
            if verbose:
                print("      → 蒸留できなかったので inbox に残します（次回再挑戦）")
            continue

        found = data.get("entries") or []
        if not found:
            if verbose:
                print("      → 記録すべき知見なし（宣伝メールなど）")
            # 「何も無かった」ことも覚えておかないと毎回読み直すことになる
            knowledge.add({
                "title": f"（知見なし）{meta.get('subject', '')[:50]}",
                "summary": "宣伝・告知が中心で、記録すべき知見はありませんでした。",
                "tags": ["対象外"],
                "confidence": "fact",
                "source": {
                    "type": "newsletter", "name": meta.get("source_name", ""),
                    "title": meta.get("subject", ""), "ref": ref,
                    "published": meta.get("published", ""),
                },
            }, verbose=False)
        else:
            for entry in found:
                entry["date"] = knowledge.today()
                entry["source"] = {
                    "type": "newsletter",
                    "name": meta.get("source_name", ""),
                    "title": meta.get("subject", ""),
                    "ref": ref,
                    "published": meta.get("published", ""),
                }
                if knowledge.add(entry, verbose=verbose):
                    added += 1

        if not keep:
            path.unlink(missing_ok=True)

    if verbose:
        print(f"✓ 新しく記録した知見: {added} 件")
    return added


# ------------------------------------------------------------------ CLI

def run(days: int = DEFAULT_LOOKBACK, limit: int = DEFAULT_MAX_PER_RUN, verbose: bool = True) -> int:
    if not config().get("enabled", True):
        if verbose:
            print("   ナレッジ取り込みは設定で無効化されています")
        return 0
    fetch(days=days, verbose=verbose)
    fetch_feeds(days=days, verbose=verbose)
    added = distill(limit=limit, verbose=verbose)
    knowledge.build_index(verbose=verbose)
    return added


def main():
    parser = argparse.ArgumentParser(description="ニュースレターからナレッジを取り込む")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="取得して蒸留する（既定）")
    p_run.add_argument("--days", type=int, default=None)
    p_run.add_argument("--limit", type=int, default=None)

    p_fetch = sub.add_parser("fetch", help="Gmail から取り込むだけ")
    p_fetch.add_argument("--days", type=int, default=None)

    p_distill = sub.add_parser("distill", help="取り込み済みのメールを蒸留する")
    p_distill.add_argument("--limit", type=int, default=None)
    p_distill.add_argument("--keep", action="store_true", help="蒸留後もメール本文を残す")

    sub.add_parser("sources", help="見ている差出人を表示")

    args = parser.parse_args()
    cfg = config()
    days = getattr(args, "days", None) or int(cfg.get("lookback_days", DEFAULT_LOOKBACK))
    limit = getattr(args, "limit", None) or int(cfg.get("max_per_run", DEFAULT_MAX_PER_RUN))

    if args.command == "fetch":
        fetch(days=days)
        fetch_feeds(days=days)
    elif args.command == "distill":
        distill(limit=limit, keep=args.keep)
        knowledge.build_index()
    elif args.command == "sources":
        print("見ている差出人:")
        for target in watch_list():
            print(f"  {target.get('name', '')}: {', '.join(target['senders'])}")
            if target.get("note"):
                print(f"    {target['note']}")
        print("\n追加・削除は monetize_config.json の knowledge.watch です。")
    else:
        run(days=days, limit=limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
