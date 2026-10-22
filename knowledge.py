#!/usr/bin/env python3
"""
ナレッジ蓄積 — 「読んで終わり」を「次の判断に効く」に変える。

## なぜ必要か

Claude はセッションが終わると、そこで話したことを忘れます。
「ブレイン教材を読ませたから覚えているのでは」と思われがちですが、そうではありません。
覚えているように見えるのは、**同じ会話の中にいる間だけ**です。

つまり知識を残す方法はひとつしかありません。**リポジトリのファイルに書くこと。**
このモジュールはそのための保管庫です。ここに入れた知見は、
`CLAUDE.md` 経由で毎回のセッション開始時に読み込まれ、以後の相談で使われます。

## 何を入れるか

イケハヤさん・テツメモさんのニュースレター、教材、自分の失敗など、
「次に何かを決めるときに効く」ものだけ。ニュースそのものは対象外です
（それは日次ダイジェストの仕事）。

## 公開リポジトリであることの注意

このリポジトリは公開されています。**有料教材やニュースレターの本文をそのまま貼らないこと。**
入れるのは自分の言葉に落とした要点だけ。取り込んだメール本文（knowledge/inbox/）は
.gitignore で除外してあり、コミットされません。

## 使い方

    python knowledge.py add --title "..." --summary "..." --source テツメモ
    python knowledge.py list                    # 一覧
    python knowledge.py search Skill            # 検索
    python knowledge.py show <ID>               # 1件の全文
    python knowledge.py try <ID> --note "..."   # 真似してみる（試し中にする）
    python knowledge.py adopt <ID> --note "..." # 良かったので採用（＝毎回守るルールになる）
    python knowledge.py reject <ID> --note "..."# 合わなかったので見送り
    python knowledge.py report --since 7        # 直近7日の報告
    python knowledge.py build                   # INDEX.md を再生成
    python knowledge.py stats

一番ラクなのは Claude に話すことです（→ KNOWLEDGE.md）。
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO_DIR = Path(__file__).parent
KNOWLEDGE_DIR = REPO_DIR / "knowledge"
STORE_FILE = KNOWLEDGE_DIR / "knowledge.json"
INDEX_FILE = KNOWLEDGE_DIR / "INDEX.md"
AMBER_FILE = KNOWLEDGE_DIR / "AMBER.md"
PERSONA_FILE = KNOWLEDGE_DIR / "persona.md"  # 手で書くプロフィール（名前・表記ルール・コハクちゃん）   # 運営者のAI（Amber）が取り込む学習ノート
INBOX_DIR = KNOWLEDGE_DIR / "inbox"

JST = timezone(timedelta(hours=9))

# 情報の確からしさ。ニュースレターの断言をそのまま事実として扱わないための区別。
CONFIDENCE_LABEL = {
    "fact": "検証済み",
    "claim": "出典の主張",
    "opinion": "意見・体験",
}

# 「読む→真似する→良ければ覚える」の段階。採用したものだけが、毎回守るルールになる。
TRIAL_LABEL = {
    "": "",
    "trying": "🧪試し中",
    "adopted": "✅採用",
    "rejected": "⏸見送り",
}
CONFIDENCE_SHORT = {"fact": "事", "claim": "主", "opinion": "意"}
SKIP_TAG = "対象外"  # 宣伝だけだったメールの記録。索引には出さない


def today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ ストア

def load() -> Dict:
    if not STORE_FILE.exists():
        return {"version": 1, "updated": "", "entries": []}
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  knowledge.json の読み込みに失敗: {e}")
        return {"version": 1, "updated": "", "entries": []}


def save(data: Dict):
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    data["updated"] = today()
    STORE_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def entries(data: Optional[Dict] = None) -> List[Dict]:
    return (data if data is not None else load()).get("entries", [])


def _make_id(title: str, date: str) -> str:
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:6]
    return f"{date.replace('-', '')}-{digest}"


def _normalize(entry: Dict) -> Dict:
    """欠けたフィールドを埋める。手書きの JSON を流し込んでも壊れないように。"""
    date = str(entry.get("date") or today())[:10]
    source = entry.get("source") or {}
    if isinstance(source, str):
        source = {"name": source}
    # source_title / ref / published を平らに書いた JSON も受け取る（入れ子にし忘れると ref が消え、同じメールを読み直すため）
    for flat, key in (("source_type", "type"), ("source_title", "title"), ("ref", "ref"), ("published", "published")):
        if entry.get(flat) and not source.get(key):
            source = {**source, key: entry[flat]}
    return {
        "id": entry.get("id") or _make_id(str(entry.get("title", "")), date),
        "date": date,
        "title": str(entry.get("title", "")).strip(),
        "summary": str(entry.get("summary", "")).strip(),
        "takeaways": [str(t).strip() for t in (entry.get("takeaways") or []) if str(t).strip()],
        "apply": [str(a).strip() for a in (entry.get("apply") or []) if str(a).strip()],
        "tags": [str(t).strip() for t in (entry.get("tags") or []) if str(t).strip()],
        "confidence": entry.get("confidence") if entry.get("confidence") in CONFIDENCE_LABEL else "claim",
        "source": {
            "type": source.get("type", "manual"),      # newsletter / material / manual / web
            "name": source.get("name", ""),            # イケハヤ / テツメモ / 自分の失敗 …
            "title": source.get("title", ""),          # メールの件名など
            "ref": source.get("ref", ""),              # gmail:<messageId> など辿れる手がかり
            "published": str(source.get("published", ""))[:10],
        },
        "visibility": entry.get("visibility", "private"),  # サイトには一切出さない
        "trial": {
            "status": (entry.get("trial") or {}).get("status", "") if (entry.get("trial") or {}).get("status", "") in TRIAL_LABEL else "",
            "note": str((entry.get("trial") or {}).get("note", "")).strip(),
            "date": str((entry.get("trial") or {}).get("date", ""))[:10],
        },
    }


def _dedupe_key(entry: Dict) -> str:
    ref = entry["source"].get("ref", "")
    return ref if ref else entry["title"]


def add(entry: Dict, verbose: bool = True) -> Optional[Dict]:
    """1件追加する。同じ出典・同じタイトルのものは追加しない（重複防止）。"""
    normalized = _normalize(entry)
    if not normalized["title"]:
        if verbose:
            print("⚠️  title が空のため追加しませんでした")
        return None

    data = load()
    existing_keys = {_dedupe_key(e) for e in map(_normalize, data.get("entries", []))}
    if _dedupe_key(normalized) in existing_keys:
        if verbose:
            print(f"・スキップ（登録済み）: {normalized['title'][:50]}")
        return None

    data.setdefault("entries", []).append(normalized)
    save(data)
    if verbose:
        print(f"✓ 追加: {normalized['title'][:60]}  [{normalized['id']}]")
    return normalized


def add_many(items: List[Dict], verbose: bool = True) -> int:
    return sum(1 for item in items if add(item, verbose=verbose))


def has_ref(ref: str) -> bool:
    """この出典はもう蒸留済みか（取り込みの二重処理を防ぐ）。"""
    return any((e.get("source") or {}).get("ref") == ref for e in entries())


# ------------------------------------------------------------------ 検索・抽出

def _variants(word: str) -> List[str]:
    """日本語の活用ゆれを吸収する（「読み間違い」で「読み間違える」も拾う）。

    3文字以上の語は、末尾を1文字落とした語幹でも探す。分かち書きの無い日本語で
    辞書を持たずに済ませるための、ざっくりした方法。
    """
    word = word.lower()
    return [word, word[:-1]] if len(word) >= 3 else [word]


def search(query: str, limit: int = 20) -> List[Dict]:
    """語で探す。タイトルとタグに当たったものを上に、同点なら新しいものを上に。

    入口（INDEX.md）を一覧だけにしたので、本文に届くかどうかはこの検索にかかっている。
    """
    words = [w for w in re.split(r"\s+", query.strip()) if w]
    if not words:
        return []
    hits = []
    for entry in map(_normalize, entries()):
        if SKIP_TAG in entry["tags"]:
            continue
        strong = " ".join([entry["title"], " ".join(entry["tags"])]).lower()
        weak = " ".join([
            entry["summary"], " ".join(entry["takeaways"]), " ".join(entry["apply"]),
            entry["source"]["name"], entry["source"]["title"],
        ]).lower()
        score = 0
        for word in words:
            for i, form in enumerate(_variants(word)):
                found = 3 * strong.count(form) + weak.count(form)
                if found:
                    score += found if i == 0 else found * 0.8  # 語幹一致は少しだけ下げる
                    break
        if score:
            hits.append((score, entry["source"]["published"] or entry["date"], entry))
    hits.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [e for _, _, e in hits[:limit]]


def since(days: int) -> List[Dict]:
    threshold = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return [e for e in map(_normalize, entries()) if e["date"] >= threshold]


def by_tag() -> Dict[str, List[Dict]]:
    grouped: Dict[str, List[Dict]] = {}
    for entry in map(_normalize, entries()):
        for tag in (entry["tags"] or ["未分類"]):
            grouped.setdefault(tag, []).append(entry)
    return dict(sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])))


# ------------------------------------------------------------------ 索引の生成

def _one_liner(entry: Dict) -> str:
    """索引の1行。本文は載せない（本文は show で必要なときだけ読む）。"""
    src = entry["source"]
    who = src["name"] or src["type"]
    when = (src["published"] or entry["date"])[5:].replace("-", "/")
    mark = CONFIDENCE_SHORT.get(entry["confidence"], "")
    trial = TRIAL_LABEL.get(entry["trial"]["status"], "")
    head = f"{trial} " if trial else ""
    return f"- {head}`{entry['id']}` {entry['title']} — {who} {when}・{mark}"


def build_index(verbose: bool = True) -> str:
    """INDEX.md を作り直す。Claude がセッション開始時に読むのはこのファイル。

    ここは「玄関」なので一覧だけにする。以前は本文まで全部載せていて、
    16件で49KB・1件がタグの数だけ重複して載っていた。件数が増えるほど
    毎回のセッションが重くなるため、本文は show / search で必要なときだけ読む。
    （テツメモさん 2026-09-22号「AGENTS.mdを231行から10行へ」の考え方）
    """
    all_entries = sorted(
        (e for e in map(_normalize, entries()) if SKIP_TAG not in e["tags"]),
        key=lambda e: (e["source"]["published"] or e["date"]), reverse=True,
    )
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    adopted = [e for e in all_entries if e["trial"]["status"] == "adopted"]
    trying = [e for e in all_entries if e["trial"]["status"] == "trying"]

    lines = [
        "# ナレッジ索引",
        "",
        "<!-- knowledge.py build が生成します。手で編集しても次回上書きされます。 -->",
        "",
        f"最終更新: {today()} ／ 全 {len(all_entries)} 件（✅採用 {len(adopted)}・🧪試し中 {len(trying)}）",
        "",
        "**一覧だけです。本文はここに載せていません。** 読み方:",
        "",
        "- 助言・設計・実装をするとき → 関係する語で `python knowledge.py search <語>`、"
        "使うものは `python knowledge.py show <ID>` で本文を読む",
        "- ✅採用 は運営者が試して採用したルール → その話題に触れる作業では必ず `show` で読んで従う",
        "- 末尾の記号は確からしさ: 事＝検証済み／主＝出典の主張（断言しない）／意＝意見・体験",
        "",
    ]

    if adopted:
        lines += ["## ✅ 採用済み（守るルール）", ""]
        lines += [_one_liner(e) for e in adopted] + [""]
    if trying:
        lines += ["## 🧪 試し中", ""]
        lines += [_one_liner(e) for e in trying] + [""]

    # 各項目は最初のタグにだけ載せる（重複させない）
    grouped: Dict[str, List[Dict]] = {}
    for entry in all_entries:
        grouped.setdefault((entry["tags"] or ["未分類"])[0], []).append(entry)
    if grouped:
        lines += ["## 一覧", ""]
        for tag, group in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"### {tag}")
            lines += [_one_liner(e) for e in group] + [""]

    if not all_entries:
        lines += [
            "まだ1件も入っていません。",
            "Claude に「これ覚えといて」と話すのが一番早い（→ KNOWLEDGE.md）。",
            "",
        ]

    text = "\n".join(lines)
    INDEX_FILE.write_text(text, encoding="utf-8")
    build_amber(all_entries, verbose=verbose)
    if verbose:
        print(f"✓ {INDEX_FILE.relative_to(REPO_DIR)} を更新（{len(all_entries)}件・{len(text.encode('utf-8')):,} bytes）")
    return text


def build_amber(all_entries: Optional[List[Dict]] = None, verbose: bool = True) -> str:
    """Amber（運営者が普段使っている Claude Code のセッション）向けの学習ノートを作る。

    Amber は別の場所で動いているので、このリポジトリの CLAUDE.md は読まない。
    Amber の CLAUDE.md からこのファイルを @ で取り込んでもらう前提で、
    「守ること（✅採用）」だけは本文ごと載せ、残りは一覧への案内にとどめる。
    """
    if all_entries is None:
        all_entries = [e for e in map(_normalize, entries()) if SKIP_TAG not in e["tags"]]
    adopted = [e for e in all_entries if e["trial"]["status"] == "adopted"]
    trying = [e for e in all_entries if e["trial"]["status"] == "trying"]

    lines = [
        "# Amber の学習ノート",
        "",
        "<!-- ai-news-digest の knowledge.py が自動で作ります。手で編集しても上書きされます。 -->",
        "",
        f"最終更新: {today()}",
        "",
        "Amber（藤崎さんのAIパートナー）が、ニュースレター（テツメモ・イケハヤ・Fujin など）から集め、",
        "**実際に試して効果を確かめ、採用した知見**です。Amber として動くときは必ず守ること。",
        "",
    ]
    if PERSONA_FILE.exists():
        # 手で書いたプロフィールを、見出しを1段下げて丸ごと取り込む
        persona = PERSONA_FILE.read_text(encoding="utf-8")
        persona = re.sub(r"<!--.*?-->\n?", "", persona, flags=re.S)
        for line in persona.splitlines():
            if line.startswith("# "):
                continue
            lines.append(("#" + line) if line.startswith("#") else line)
        lines.append("")
    lines += ["## 守ること（✅採用）", ""]
    if adopted:
        for e in adopted:
            lines += [f"### {e['title']}", "", e["summary"], ""]
            lines += [f"- {t}" for t in e["takeaways"]]
            if e["trial"]["note"]:
                lines += ["", f"採用した理由（{e['trial']['date']}）: {e['trial']['note']}"]
            lines += ["", f"<small>出典: {e['source']['name']} {e['source']['published']}・"
                          f"{CONFIDENCE_LABEL.get(e['confidence'], '')}・`{e['id']}`</small>", ""]
    else:
        lines += ["まだありません。試して効果を確かめたものがここに入ります。", ""]

    if trying:
        lines += ["## 試し中（まだルールではない）", ""]
        lines += [f"- {e['title']}" for e in trying] + [""]

    lines += [
        "## もっと知りたいとき",
        "",
        f"ほかに {len(all_entries)} 件の知見があります。一覧は同じフォルダの `INDEX.md`。",
        "本文は ai-news-digest のフォルダで `python knowledge.py search <語>` / `python knowledge.py show <ID>`。",
        "",
        "確からしさ: 検証済み＝事実として使ってよい／出典の主張＝「〜と言われている」と断る／意見・体験＝一般則にしない。",
        "",
    ]
    text = "\n".join(lines)
    AMBER_FILE.write_text(text, encoding="utf-8")
    if verbose:
        print(f"✓ {AMBER_FILE.relative_to(REPO_DIR)} を更新（✅採用 {len(adopted)}件）")
    return text


def get(entry_id: str) -> Optional[Dict]:
    for entry in map(_normalize, entries()):
        if entry["id"] == entry_id:
            return entry
    return None


def set_trial(entry_id: str, status: str, note: str = "") -> Optional[Dict]:
    """真似してみた結果を記録する。adopted にしたものが「毎回守るルール」になる。"""
    data = load()
    for raw in data.get("entries", []):
        if _normalize(raw)["id"] == entry_id:
            raw["id"] = _normalize(raw)["id"]
            raw["trial"] = {"status": status, "note": note.strip(), "date": today()}
            save(data)
            return _normalize(raw)
    return None


# ------------------------------------------------------------------ 報告

def report(days: int = 7) -> str:
    """「新しく蓄えたナレッジ」の報告文（Markdown）。"""
    recent = sorted((e for e in since(days) if SKIP_TAG not in e["tags"]),
                    key=lambda e: e["date"], reverse=True)
    head = f"## ナレッジ報告（直近{days}日）\n\n"
    if not recent:
        return head + f"この{days}日で新しく記録したものはありません。\n"

    sources: Dict[str, int] = {}
    for entry in recent:
        sources[entry["source"]["name"] or "その他"] = sources.get(entry["source"]["name"] or "その他", 0) + 1
    summary = "・".join(f"{name} {count}件" for name, count in sorted(sources.items(), key=lambda kv: -kv[1]))

    out = [head.rstrip(), "", f"新しく {len(recent)} 件を記録しました（{summary}）。", ""]
    for entry in recent:
        src = entry["source"]
        out.append(f"### {entry['title']}")
        out.append("")
        out.append(f"{entry['summary']}")
        out.append("")
        if entry["takeaways"]:
            out += [f"- {t}" for t in entry["takeaways"]] + [""]
        if entry["apply"]:
            out.append("**このプロジェクトへの応用**: " + " / ".join(entry["apply"]))
            out.append("")
        if entry["trial"]["status"]:
            out.append(f"**{TRIAL_LABEL[entry['trial']['status']]}**（{entry['trial']['date']}）: {entry['trial']['note']}")
            out.append("")
        meta = f"出典: {src['name']}"
        if src["title"]:
            meta += f"「{src['title'][:60]}」"
        if src["published"]:
            meta += f"（{src['published']}）"
        meta += f" ／ {CONFIDENCE_LABEL.get(entry['confidence'], '')}"
        out += [f"<small>{meta}</small>", ""]
    return "\n".join(out) + "\n"


def table_report(days: int = 7) -> str:
    """「取り入れたこと・やらなかったこと」の一覧表（Markdown）。藤崎さんへの定期報告用。"""
    threshold = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")
    all_entries = [e for e in map(_normalize, entries()) if SKIP_TAG not in e["tags"]]

    def cell(text: str, limit: int = 70) -> str:
        text = " ".join(str(text).split()).replace("|", "／")
        return text if len(text) <= limit else text[:limit - 1] + "…"

    def who(entry: Dict) -> str:
        src = entry["source"]
        when = (src["published"] or entry["date"])[5:].replace("-", "/")
        return f"{src['name'] or 'その他'} {when}"

    def decided(status: str) -> List[Dict]:
        rows = [e for e in all_entries if e["trial"]["status"] == status and (e["trial"]["date"] or e["date"]) >= threshold]
        return sorted(rows, key=lambda e: e["trial"]["date"] or e["date"], reverse=True)

    adopted, rejected = decided("adopted"), decided("rejected")
    trying = [e for e in all_entries if e["trial"]["status"] == "trying"]
    learned = sorted((e for e in all_entries if not e["trial"]["status"] and e["date"] >= threshold),
                     key=lambda e: e["date"], reverse=True)
    skipped = sum(1 for e in map(_normalize, entries()) if SKIP_TAG in e["tags"] and e["date"] >= threshold)

    out = [f"## Amber の取り入れ報告（直近{days}日）", "",
           f"取り入れた {len(adopted)} 件 ／ 試し中 {len(trying)} 件 ／ やらなかった {len(rejected)} 件 ／ "
           f"覚えただけ {len(learned)} 件 ／ 知見なし {skipped} 通", ""]

    def table(title: str, rows: List[Dict], last_head: str, last) -> None:
        out.append(f"### {title}")
        out.append("")
        if not rows:
            out.extend(["（ありません）", ""])
            return
        out.extend([f"| 日付 | 取り入れたもの | 出どころ | {last_head} |", "|---|---|---|---|"])
        for e in rows:
            day = (e["trial"]["date"] or e["date"])[5:].replace("-", "/")
            out.append(f"| {day} | {cell(e['title'], 60)} | {cell(who(e), 20)} | {cell(last(e))} |")
        out.append("")

    table("✅ 取り入れたこと（採用して、毎回守るルールにした）", adopted, "何が良かったか", lambda e: e["trial"]["note"])
    table("🧪 試している最中", trying, "何をどう試しているか", lambda e: e["trial"]["note"])
    table("⏸ やらなかったこと（試して見送った）", rejected, "見送った理由", lambda e: e["trial"]["note"])
    table("📥 覚えただけ（まだ試していない）", learned, "うちでの使い道",
          lambda e: e["apply"][0] if e["apply"] else (e["takeaways"][0] if e["takeaways"] else ""))
    return "\n".join(out)


def send_report_email(days: int = 7, to: str = "") -> bool:
    """報告をメールで送る。日次ダイジェストと同じアプリパスワードを使う。"""
    import smtplib
    from email.mime.text import MIMEText

    address = __import__("os").getenv("GMAIL_ADDRESS")
    password = __import__("os").getenv("GMAIL_APP_PASSWORD")
    if not address or not password:
        print("⚠️  GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定のため送信をスキップします")
        return False

    recent = since(days)
    if not recent:
        print(f"   この{days}日で新しい知見が無いため、報告メールは送りません")
        return False

    body = report(days)
    message = MIMEText(body, "plain", "utf-8")
    message["Subject"] = f"ナレッジ報告 {today()}（新しく {len(recent)} 件）"
    message["From"] = address
    message["To"] = to or address
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
            server.login(address, password)
            server.send_message(message)
        print(f"✓ 報告メールを送信しました → {message['To']}")
        return True
    except Exception as e:
        print(f"⚠️  報告メールの送信に失敗: {e}")
        return False


def stats() -> Dict:
    all_entries = list(map(_normalize, entries()))
    sources: Dict[str, int] = {}
    for entry in all_entries:
        key = entry["source"]["name"] or entry["source"]["type"]
        sources[key] = sources.get(key, 0) + 1
    pending = len(list(INBOX_DIR.glob("*.md"))) if INBOX_DIR.exists() else 0
    return {
        "total": len(all_entries),
        "last_7_days": len(since(7)),
        "last_30_days": len(since(30)),
        "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
        "tags": {tag: len(group) for tag, group in by_tag().items()},
        "inbox_files": pending,
    }


# ------------------------------------------------------------------ CLI

def _print_entry(entry: Dict, full: bool = False):
    src = entry["source"]
    tags = ("#" + " #".join(entry["tags"])) if entry["tags"] else ""
    trial = TRIAL_LABEL.get(entry["trial"]["status"], "")
    print(f"[{entry['date']}] {trial + ' ' if trial else ''}{entry['title']}")
    print(f"    {entry['summary'][:160]}")
    if full and entry["takeaways"]:
        for takeaway in entry["takeaways"]:
            print(f"    - {takeaway}")
    if entry["apply"]:
        print(f"    → 応用: {' / '.join(entry['apply'])}")
    print(f"    {src['name'] or src['type']} ／ {CONFIDENCE_LABEL.get(entry['confidence'], '')} {tags}  [{entry['id']}]")
    print()


def main():
    parser = argparse.ArgumentParser(description="ナレッジ蓄積")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="1件追加する")
    p_add.add_argument("--title", required=False, default="")
    p_add.add_argument("--summary", default="")
    p_add.add_argument("--takeaway", action="append", default=[], help="学び（複数可）")
    p_add.add_argument("--apply", action="append", default=[], help="このプロジェクトへの応用（複数可）")
    p_add.add_argument("--tag", action="append", default=[])
    p_add.add_argument("--source", default="", help="出典の名前（イケハヤ / テツメモ など）")
    p_add.add_argument("--source-type", default="manual",
                       choices=["newsletter", "material", "manual", "web"])
    p_add.add_argument("--source-title", default="")
    p_add.add_argument("--ref", default="")
    p_add.add_argument("--published", default="")
    p_add.add_argument("--confidence", default="claim", choices=list(CONFIDENCE_LABEL))
    p_add.add_argument("--json", default="", help="JSON で渡す（'-' で標準入力）")

    p_list = sub.add_parser("list", help="一覧")
    p_list.add_argument("--tag", default="")
    p_list.add_argument("--source", default="")
    p_list.add_argument("--limit", type=int, default=30)
    p_list.add_argument("--full", action="store_true")

    p_search = sub.add_parser("search", help="検索")
    p_search.add_argument("query", nargs="+")
    p_search.add_argument("--limit", type=int, default=20)

    p_report = sub.add_parser("report", help="新しく蓄えたナレッジの報告")
    p_report.add_argument("--since", type=int, default=7)
    p_report.add_argument("--email", action="store_true", help="報告をメールで送る")
    p_report.add_argument("--table", action="store_true", help="取り入れたこと・やらなかったことの一覧表にする")
    p_report.add_argument("--to", default="", help="宛先（既定は自分）")

    p_show = sub.add_parser("show", help="1件の全文")
    p_show.add_argument("id")

    for name, label in (("try", "真似してみる（試し中にする）"),
                        ("adopt", "採用する（毎回守るルールになる）"),
                        ("reject", "見送る")):
        p_trial = sub.add_parser(name, help=label)
        p_trial.add_argument("id")
        p_trial.add_argument("--note", default="", help="試した結果・理由")

    sub.add_parser("build", help="INDEX.md を再生成")
    sub.add_parser("stats", help="統計")

    args = parser.parse_args()

    if args.command == "add":
        if args.json:
            raw = sys.stdin.read() if args.json == "-" else args.json
            payload = json.loads(raw)
            items = payload if isinstance(payload, list) else [payload]
            count = add_many(items)
            print(f"\n{count} 件を追加しました。")
        else:
            if not args.title:
                print("⚠️  --title か --json のどちらかが必要です")
                return 1
            add({
                "title": args.title,
                "summary": args.summary,
                "takeaways": args.takeaway,
                "apply": args.apply,
                "tags": args.tag,
                "confidence": args.confidence,
                "source": {
                    "type": args.source_type, "name": args.source,
                    "title": args.source_title, "ref": args.ref,
                    "published": args.published,
                },
            })
        build_index()

    elif args.command == "list":
        rows = list(map(_normalize, entries()))
        if args.tag:
            rows = [e for e in rows if args.tag in e["tags"]]
        if args.source:
            rows = [e for e in rows if args.source in e["source"]["name"]]
        rows.sort(key=lambda e: e["date"], reverse=True)
        if not rows:
            print("該当なし。")
            return 0
        print(f"{len(rows)} 件\n")
        for entry in rows[:args.limit]:
            _print_entry(entry, full=args.full)

    elif args.command == "search":
        hits = search(" ".join(args.query), limit=args.limit)
        if not hits:
            print("該当なし。")
            return 0
        print(f"{len(hits)} 件ヒット\n")
        for entry in hits:
            _print_entry(entry, full=True)

    elif args.command == "report":
        if args.table:
            print(table_report(args.since))
        elif args.email:
            send_report_email(args.since, args.to)
        else:
            print(report(args.since))

    elif args.command == "show":
        entry = get(args.id)
        if not entry:
            print(f"見つかりません: {args.id}")
            return 1
        src = entry["source"]
        print(f"# {entry['title']}\n")
        print(entry["summary"] + "\n")
        for t in entry["takeaways"]:
            print(f"- {t}")
        if entry["apply"]:
            print("\n応用:")
            for a in entry["apply"]:
                print(f"- {a}")
        if entry["trial"]["status"]:
            print(f"\n{TRIAL_LABEL[entry['trial']['status']]}（{entry['trial']['date']}）: {entry['trial']['note']}")
        print(f"\n出典: {src['name']}「{src['title']}」{src['published']} ／ "
              f"{CONFIDENCE_LABEL.get(entry['confidence'], '')} ／ #{' #'.join(entry['tags'])} ／ {entry['id']}")

    elif args.command in ("try", "adopt", "reject"):
        status = {"try": "trying", "adopt": "adopted", "reject": "rejected"}[args.command]
        entry = set_trial(args.id, status, args.note)
        if not entry:
            print(f"見つかりません: {args.id}")
            return 1
        print(f"{TRIAL_LABEL[status]}: {entry['title']}")
        build_index()

    elif args.command == "build":
        build_index()

    elif args.command == "stats":
        info = stats()
        print(f"蓄積: {info['total']} 件（直近7日 {info['last_7_days']} 件 / 30日 {info['last_30_days']} 件）")
        print("出典別:")
        for name, count in info["sources"].items():
            print(f"  {name}: {count}")
        print("タグ別:")
        for tag, count in info["tags"].items():
            print(f"  {tag}: {count}")
        if info["inbox_files"]:
            print(f"\n未蒸留のメール: {info['inbox_files']} 件（python knowledge_ingest.py distill）")

    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
