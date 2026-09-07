#!/usr/bin/env python3
"""
SNS拡散キット — 毎日のダイジェストから、そのままコピペできる投稿文を作る。

なぜ必要か:
  解説記事のSEOは効き始めるまで数ヶ月かかる。その間の流入と、
  将来の見込み客リストは SNS で作るしかない。
  ただしネタを毎日ひねり出すのは続かないので、
  すでに毎朝生成しているダイジェストから機械的に作る。

自動投稿はしない:
  X の投稿APIは有料かつ凍結リスクがあり、自動投稿されたテキストは伸びにくい。
  「文面は自動、投稿ボタンは人間」が現時点でいちばん費用対効果が高い。

使い方:
  python social_kit.py                 # 最新のダイジェストから生成
  python social_kit.py --date 2026-07-16
  python social_kit.py --backfill 30   # 過去30日ぶんをまとめて生成（SNSネタの貯金）
"""

import html as _html
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import glossary
import monetize

JST = timezone(timedelta(hours=9))
REPO_DIR = Path(__file__).parent
SOCIAL_DIR = REPO_DIR / "social"
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

X_LIMIT = 280  # X の重み付き文字数上限（日本語は1文字=2）

CATEGORIES_JA = {
    "model": "モデル", "research": "研究", "business": "ビジネス",
    "policy": "ポリシー", "tools": "ツール",
}


_URL_RE = re.compile(r"https?://\S+")


def weighted_len(text: str) -> int:
    """X の文字数カウント（全角＝2、半角＝1）に合わせて数える。"""
    total = 0
    for ch in text:
        total += 2 if unicodedata.east_asian_width(ch) in ("F", "W", "A") else 1
    return total


def x_length(text: str) -> int:
    """X 上での実際の長さ。URL は t.co に短縮されるため長さに関係なく23文字扱い。"""
    return weighted_len(_URL_RE.sub("", text)) + 23 * len(_URL_RE.findall(text))


# ---------------------------------------------------------------- 記事の取得

_CARD_RE = re.compile(
    r'<article class="card (\w+)(?: top)?".*?'
    r'<div class="card-title-ja">(.*?)</div>.*?'
    r'<div class="card-source">(.*?)</div>.*?'
    r'<div class="card-body">(.*?)</div>',
    re.DOTALL,
)
_STARS_RE = re.compile(r'<div class="stars">(.*?)</div>\s*</div>', re.DOTALL)


def load_from_html(date_iso: str) -> Dict[str, List[Dict]]:
    """公開済みダイジェスト HTML から記事を読み戻す（過去分の再利用用）。"""
    path = REPO_DIR / f"ai-news-{date_iso}.html"
    if not path.exists():
        return {}

    raw = path.read_text(encoding="utf-8", errors="ignore")
    result: Dict[str, List[Dict]] = {}
    for block in raw.split('<article class="card ')[1:]:
        block = '<article class="card ' + block
        m = _CARD_RE.search(block)
        if not m:
            continue
        category, title, source, body = m.groups()
        # stars ブロックは <div class="dot filled"> を内包するため、
        # 単純に最初の </div> まで切ると 0 個に数えてしまう。stars 全体を取る。
        sm = _STARS_RE.search(block)
        importance = sm.group(1).count("dot filled") if sm else 2
        result.setdefault(category, []).append({
            "title_ja": _html.unescape(re.sub(r"<.*?>", "", title)).strip(),
            "source": _html.unescape(re.sub(r"<.*?>", "", source)).strip().split(" · ")[0],
            "summary": _html.unescape(re.sub(r"<.*?>", "", body)).strip(),
            "importance": importance or 2,
        })
    return result


def top_articles(categorized: Dict[str, List[Dict]], limit: int = 3) -> List[Dict]:
    """重要度の高い順に、カテゴリが偏らないよう選ぶ。"""
    pool = []
    for category, items in categorized.items():
        for a in items:
            pool.append({**a, "category": category})
    pool.sort(key=lambda a: (-int(a.get("importance", 2)), a.get("title_ja", "")))

    picked, used = [], set()
    for a in pool:
        if a["category"] in used and len(picked) < limit:
            continue
        picked.append(a)
        used.add(a["category"])
        if len(picked) >= limit:
            break
    for a in pool:  # 埋まらなければカテゴリ重複を許して補充
        if len(picked) >= limit:
            break
        if a not in picked:
            picked.append(a)
    return picked[:limit]


# ---------------------------------------------------------------- 投稿文の生成

def _trim(text: str, budget: int) -> str:
    """重み付き文字数で切り詰める。"""
    out = ""
    for ch in text:
        if weighted_len(out + ch) > budget:
            return out.rstrip("、。 ") + "…"
        out += ch
    return out


def build_x_posts(articles: List[Dict], date: datetime, url: str) -> List[Dict]:
    date_label = f"{date.month}/{date.day}"
    posts = []

    # ① まとめ投稿（いちばん拡散する型：数字＋箇条書き＋リンク）
    for title_budget in range(60, 15, -4):
        lines = [f"【{date_label} AIニュース3行まとめ】", ""]
        for a in articles:
            lines.append(f"▪️ {_trim(a['title_ja'], title_budget)}")
        lines += ["", url, "", "#AI #生成AI #AIニュース"]
        summary_post = "\n".join(lines)
        if x_length(summary_post) <= X_LIMIT:
            break
    posts.append({"label": "まとめ投稿（推奨）", "text": summary_post})

    # ② 単体深掘り（1本に絞ると反応が取りやすい）
    if articles:
        a = articles[0]
        head = f"これは見逃せない。\n\n{_trim(a['title_ja'], 70)}\n\n"
        tail = f"\n\n詳しくはこちら\n{url}\n\n#AI #生成AI"
        budget = X_LIMIT - x_length(head) - x_length(tail)
        posts.append({
            "label": "単体深掘り",
            "text": head + _trim(a.get("summary", ""), max(budget, 20)) + tail,
        })

    # ③ 問いかけ（リプライを誘って表示回数を伸ばす型）
    if articles:
        posts.append({
            "label": "問いかけ",
            "text": (f"{_trim(articles[0]['title_ja'], 60)}\n\n"
                     "……というニュースが出ていました。\n"
                     "これ、皆さんの仕事にはどう影響しそうですか？\n\n"
                     f"今日のAIニュースまとめ↓\n{url}\n\n#AI #生成AI"),
        })

    for p in posts:
        p["length"] = x_length(p["text"])
        p["ok"] = p["length"] <= X_LIMIT
    return posts


def build_note_outline(articles: List[Dict], date: datetime, url: str) -> str:
    date_label = f"{date.year}年{date.month}月{date.day}日"
    lines = [
        f"# 【{date_label}】今日のAIニュースで、個人的に効いたもの3つ",
        "",
        "※ note / ブログ向けの下書きです。要約はそのまま使わず、"
        "「自分の仕事にどう関係するか」を1つずつ足してから公開してください。",
        "",
    ]
    for i, a in enumerate(articles, 1):
        lines += [
            f"## {i}. {a['title_ja']}",
            "",
            f"（出典: {a.get('source', '')} / カテゴリ: {CATEGORIES_JA.get(a.get('category', ''), '')}）",
            "",
            a.get("summary", ""),
            "",
            "**これをどう見るか**：",
            "",
            "",
        ]
    lines += ["---", "", f"毎朝6時のAIニュースまとめはこちら → {url}", ""]
    return "\n".join(lines)


def build_term_post(date: datetime, url_base: str) -> Optional[Dict]:
    """「今日の用語」投稿。97語の辞書を日替わりでSNSの教育コンテンツに変える。

    ニュースのリンク投稿より、それ自体で完結する解説投稿のほうが拡散しやすく、
    「わかりやすく教える人」というブランドの発信としても筋がいい。
    """
    terms = glossary.published()
    if not terms:
        return None
    t = terms[int(date.strftime("%Y%m%d")) % len(terms)]  # 日付で決まる巡回
    reading = f"（{t['reading']}）" if t.get("reading") else ""
    url = f"{url_base}/terms/{t['slug']}.html" if url_base else ""
    text = (f"【今日のAI用語】{t['term']}{reading}\n\n"
            f"{t['short']}\n\n"
            + (f"もう一歩くわしく↓\n{url}\n\n" if url else "")
            + "#AI用語 #生成AI #AI初心者")
    return {"label": "今日の用語（教育系・拡散向き）", "text": text,
            "length": x_length(text), "ok": x_length(text) <= X_LIMIT}


def build_kit(categorized: Dict[str, List[Dict]], date: datetime,
              config: Optional[Dict] = None) -> str:
    config = config if config is not None else monetize.load_config()
    base = config.get("site", {}).get("base_url", "").rstrip("/")
    date_iso = date.strftime("%Y-%m-%d")
    url = f"{base}/ai-news-{date_iso}.html" if base else ""

    articles = top_articles(categorized, limit=3)
    if not articles:
        return ""

    posts = build_x_posts(articles, date, url)
    term_post = build_term_post(date, base)
    if term_post:
        posts.append(term_post)

    out = [
        f"# SNS投稿キット {date_iso}（{WEEKDAYS_JA[date.weekday()]}）",
        "",
        "自動生成です。**そのままコピペで投稿できます**が、"
        "1行でも自分の感想を足したほうが確実に伸びます。",
        "",
        "## X（旧Twitter）",
        "",
    ]
    for p in posts:
        status = "OK" if p["ok"] else "⚠️ 上限超過・要短縮"
        out += [f"### {p['label']}  — {p['length']}/{X_LIMIT} {status}", "", "```", p["text"], "```", ""]

    out += ["## note / ブログ下書き", "", "```markdown", build_note_outline(articles, date, url), "```", ""]
    return "\n".join(out)


def write_kit(categorized: Dict[str, List[Dict]], date: datetime,
              config: Optional[Dict] = None, verbose: bool = True) -> Optional[Path]:
    content = build_kit(categorized, date, config)
    if not content:
        return None
    SOCIAL_DIR.mkdir(exist_ok=True)
    path = SOCIAL_DIR / f"{date.strftime('%Y-%m-%d')}.md"
    path.write_text(content, encoding="utf-8")
    if verbose:
        print(f"✓ SNS投稿キット: social/{path.name}")
    return path


# ---------------------------------------------------------------- CLI

def main():
    args = sys.argv[1:]

    if "--backfill" in args:
        n = int(args[args.index("--backfill") + 1])
        made = 0
        for path in sorted(REPO_DIR.glob("ai-news-*.html"), reverse=True):
            m = re.match(r"ai-news-(\d{4}-\d{2}-\d{2})\.html$", path.name)
            if not m:
                continue
            date_iso = m.group(1)
            categorized = load_from_html(date_iso)
            if not categorized:
                continue
            if write_kit(categorized, datetime.strptime(date_iso, "%Y-%m-%d"), verbose=False):
                made += 1
            if made >= n:
                break
        print(f"✓ 過去 {made} 日ぶんの投稿キットを social/ に作成しました")
        return

    if "--date" in args:
        date_iso = args[args.index("--date") + 1]
    else:
        candidates = sorted(REPO_DIR.glob("ai-news-*.html"), reverse=True)
        if not candidates:
            print("ダイジェストが見つかりません")
            return
        date_iso = re.findall(r"(\d{4}-\d{2}-\d{2})", candidates[0].name)[0]

    categorized = load_from_html(date_iso)
    if not categorized:
        print(f"ai-news-{date_iso}.html から記事を読み取れませんでした")
        return
    write_kit(categorized, datetime.strptime(date_iso, "%Y-%m-%d"))


if __name__ == "__main__":
    main()
