#!/usr/bin/env python3
"""
解説記事ビルダー — 検索流入で戦う「読み物」レイヤー。

日次ダイジェストは賞味期限が数日しかなく、検索では大手メディアに勝てない。
収益は「AIスクール 比較」「Claude Code 使い方」のような
"解決したい人が検索する言葉" で書いた少数の記事から生まれる。
そのための記事を articles/*.md から静的 HTML に変換する。

Markdown フロントマター:
    ---
    title: 記事タイトル
    description: 検索結果に出る説明文（120字前後）
    slug: url-slug
    keywords: キーワード, カンマ, 区切り
    offers: conoha-wing, kikagaku      # 優先して出す案件ID（省略可）
    published: 2026-08-25
    updated: 2026-08-25
    status: published                  # draft なら公開されない
    ---

単体実行:  python article_builder.py
"""

import html as _html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import glossary
import monetize
import site_theme

JST = timezone(timedelta(hours=9))
REPO_DIR = Path(__file__).parent
ARTICLES_DIR = REPO_DIR / "articles"

# 執筆者本人の言葉が必要な箇所に残すマーカー。残っていればビルド時に警告する。
TODO_MARKER = "✍️"


# ---------------------------------------------------------------- 解析

def parse_front_matter(raw: str) -> (Dict, str):
    """--- で囲まれた簡易フロントマターを読む（外部依存なし）。"""
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end < 0:
        return {}, raw

    meta: Dict = {}
    for line in raw[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key in ("keywords", "offers"):
            meta[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            meta[key] = value

    body = raw[end + 4:].lstrip("\n")
    return meta, body


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")


def collect_articles(include_drafts: bool = False) -> List[Dict]:
    """articles/*.md を新しい順に列挙する。"""
    if not ARTICLES_DIR.exists():
        return []

    found = []
    for path in sorted(ARTICLES_DIR.glob("*.md")):
        if path.name.startswith("_"):
            continue  # _keyword-plan.md のような作業用ファイルは対象外
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"⚠️  {path.name} を読めませんでした: {e}")
            continue

        meta, body = parse_front_matter(raw)
        if not meta.get("title"):
            print(f"⚠️  {path.name}: title が無いためスキップ")
            continue
        published_flag = meta.get("status", "draft") == "published"
        has_todo = TODO_MARKER in body
        # status: published でも加筆マーカーが残っていれば公開しない。
        # 「（例：〜）」のような下書き文言がそのまま世に出るのを防ぐための安全弁。
        if not include_drafts and (not published_flag or has_todo):
            continue

        slug = meta.get("slug") or _slugify(path.stem)
        published = meta.get("published", "")
        found.append({
            "slug": slug,
            "file": f"{slug}.html",
            "path": f"articles/{slug}.html",
            "source": path,
            "title": meta["title"],
            "description": meta.get("description", ""),
            "keywords": meta.get("keywords", []),
            "offers": meta.get("offers", []),
            "published": published,
            "updated": meta.get("updated", published),
            "status": meta.get("status", "draft"),
            "body": body,
            "todo": body.count(TODO_MARKER),
        })

    found.sort(key=lambda a: a.get("published", ""), reverse=True)
    return found


# ---------------------------------------------------------------- 変換

_EDITOR_NOTE_RE = re.compile(r"<!--[^>]*?" + re.escape(TODO_MARKER) + r".*?-->", re.DOTALL)


def strip_editor_notes(html_body: str) -> str:
    """執筆用メモを公開ページから取り除く。"""
    return _EDITOR_NOTE_RE.sub("", html_body)


def _render_markdown(body: str) -> str:
    import markdown
    return markdown.markdown(
        body,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )


_H2_RE = re.compile(r"<h2>(.*?)</h2>", re.DOTALL)

# 用語マークを入れてよい要素。見出し・pre/code・既存のリンクは除外する。
_PROSE_BLOCK_RE = re.compile(r"(<(?:p|li|td)>)(.*?)(</(?:p|li|td)>)", re.DOTALL)
_SKIP_INLINE_RE = re.compile(r"(<code>.*?</code>|<a\b.*?</a>|<[^>]+>)", re.DOTALL)


def _annotate_prose(html_body: str, ann) -> str:
    """段落・箇条書き・表セルの地の文にだけ用語マークを入れる。

    タグの中身やコード、既存リンクのテキストに触れると壊れるため、
    それらを避けて素のテキスト部分だけを処理する。
    """
    def per_block(m):
        inner = "".join(
            part if _SKIP_INLINE_RE.fullmatch(part) else ann(part)
            for part in _SKIP_INLINE_RE.split(m.group(2)) if part
        )
        return m.group(1) + inner + m.group(3)

    return _PROSE_BLOCK_RE.sub(per_block, html_body)


def _add_heading_ids(html_body: str) -> (str, List[Dict]):
    """h2 に id を振り、目次のもとになる一覧を返す。"""
    headings: List[Dict] = []

    def repl(m):
        text = re.sub(r"<.*?>", "", m.group(1)).strip()
        hid = f"h-{len(headings) + 1}"
        headings.append({"id": hid, "text": text})
        return f'<h2 id="{hid}">{m.group(1)}</h2>'

    return _H2_RE.sub(repl, html_body), headings


def _render_toc(headings: List[Dict]) -> str:
    if len(headings) < 3:
        return ""
    items = "".join(
        f'      <li><a href="#{h["id"]}">{_html.escape(h["text"])}</a></li>\n'
        for h in headings
    )
    return (
        '  <nav class="toc">\n'
        '    <div class="toc-title">目次</div>\n'
        "    <ol>\n"
        f"{items}"
        "    </ol>\n"
        "  </nav>\n"
    )


def _split_for_midroll(html_body: str, headings: List[Dict]) -> (str, str):
    """記事の中盤（見出しの区切り）で本文を2つに割り、あいだに広告枠を入れられるようにする。"""
    if len(headings) < 4:
        return html_body, ""
    target = headings[len(headings) // 2]["id"]
    marker = f'<h2 id="{target}">'
    idx = html_body.find(marker)
    if idx < 0:
        return html_body, ""
    return html_body[:idx], html_body[idx:]


# ---------------------------------------------------------------- ページ生成

def _pick_offers(config: Dict, article: Dict, limit: int) -> List[Dict]:
    """フロントマターで指定された案件を優先し、足りない分をキーワード一致で補う。"""
    if limit <= 0:
        return []

    live = {o["id"]: o for o in monetize.active_offers(config)}
    picked = [live[i] for i in article.get("offers", []) if i in live]

    if len(picked) < limit:
        text = " ".join(article.get("keywords", [])) + " " + article.get("title", "")
        rest = [o for o in monetize.active_offers(config) if o["id"] not in {p["id"] for p in picked}]
        rest.sort(key=lambda o: -monetize._score(o, [], text))
        picked += rest[: limit - len(picked)]

    return picked[:limit]


def build_article_page(article: Dict, config: Dict, related: List[Dict]) -> str:
    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    name = site.get("name", "")
    page_url = f"{base}/articles/{article['file']}" if base else ""

    html_body = strip_editor_notes(_render_markdown(article["body"]))
    html_body, headings = _add_heading_ids(html_body)

    # 解説記事の本文にも用語マークを付ける。読者層が「これから学ぶ人」なので、
    # ダイジェスト以上に効く。見出し・コード・既存リンクの中は避ける。
    gcfg = config.get("glossary", {})
    ann = (glossary.Annotator(limit=int(gcfg.get("max_marks_per_article", 18)), prefix="../")
           if gcfg.get("enabled", True) else None)
    if ann:
        html_body = _annotate_prose(html_body, ann)
    head_part, tail_part = _split_for_midroll(html_body, headings)

    published = article.get("published", "")
    updated = article.get("updated", published)

    head = monetize.build_head_tags(
        config,
        page_url=page_url,
        title=f"{article['title']} | {name}",
        description=article["description"],
        published=f"{published}T09:00:00+09:00" if published else "",
    )
    if article.get("keywords"):
        head += f'<meta name="keywords" content="{_html.escape(", ".join(article["keywords"]))}">\n'
    if base:
        breadcrumb = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "ホーム", "item": f"{base}/"},
                {"@type": "ListItem", "position": 2, "name": "エッセイ", "item": f"{base}/articles/"},
                {"@type": "ListItem", "position": 3, "name": article["title"], "item": page_url},
            ],
        }
        head += ('<script type="application/ld+json">'
                 + json.dumps(breadcrumb, ensure_ascii=False) + "</script>\n")

    slots = config.get("slots", {})
    n_mid = int(slots.get("in_content_offers", 0)) if tail_part else 0
    n_end = int(slots.get("footer_offers", 0))
    picked = _pick_offers(config, article, n_mid + n_end)
    mid_offers, end_offers = picked[:n_mid], picked[n_mid:n_mid + n_end]
    mid_block = monetize.render_offer_block(mid_offers, heading="この記事に関連するサービス")
    end_block = monetize.render_offer_block(end_offers, heading="次の一歩におすすめ")

    related_html = ""
    if related:
        cards = "".join(
            f'    <a class="issue" href="{r["file"]}">\n'
            f'      <div class="d">{_html.escape(r["title"])}</div>\n'
            f'      <div class="m">{_html.escape(r.get("description", "")[:60])}</div>\n'
            "    </a>\n"
            for r in related
        )
        related_html = (
            '  <div class="section-label">あわせて読みたい</div>\n'
            f'  <div class="issue-grid">\n{cards}  </div>\n'
        )

    meta_line = ""
    if published:
        meta_line = f"公開 {published}"
        if updated and updated != published:
            meta_line += f" ・ 最終更新 {updated}"

    body = f"""<div class="hero">
  <div class="hero-inner">
    <div class="crumbs"><a href="../">{_html.escape(name)}</a> ／ <a href="./">エッセイ</a></div>
    <h1>{_html.escape(article['title'])}</h1>
    <p>{_html.escape(article['description'])}</p>
  </div>
</div>

<main>
{monetize.render_disclosure(config)}
  <div class="article-meta">{_html.escape(meta_line)}</div>
{_render_toc(headings)}
  <article class="prose">
{head_part}
  </article>
{mid_block}
  <article class="prose">
{tail_part}
  </article>
{monetize.render_adsense_unit(config)}{end_block}{monetize.render_cta(config)}
{related_html}
  <p style="max-width:720px;margin:2.5rem auto 0;font-size:0.85rem;">
    <a href="../" style="color:var(--accent);font-weight:600;">← 毎朝のAIニュースダイジェストを見る</a>
  </p>
</main>

<footer>
  <strong>{_html.escape(name)}</strong> — {_html.escape(site.get("author", ""))}
  {site_theme.footer_links(config, prefix="../")}
</footer>
{glossary.assets(ann) if ann else ""}"""

    return site_theme.page_shell(
        f"{article['title']} | {name}", head, body,
        extra_css=site_theme.PROSE_CSS + (glossary.TOOLTIP_CSS if ann else ""),
    )


def build_index_page(articles: List[Dict], config: Dict) -> str:
    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    name = site.get("name", "")

    head = monetize.build_head_tags(
        config,
        page_url=f"{base}/articles/" if base else "",
        title=f"エッセイ | {name}",
        description="AIの使い方・学び方・仕事への活かし方をまとめた解説記事の一覧です。",
    ).replace('<meta property="og:type" content="article">',
              '<meta property="og:type" content="website">')

    if articles:
        cards = "".join(
            f'    <a class="issue" href="{a["file"]}">\n'
            f'      <div class="d">{_html.escape(a["title"])}</div>\n'
            f'      <div class="m">{_html.escape(a.get("description", "")[:80])}</div>\n'
            "    </a>\n"
            for a in articles
        )
        listing = f'  <div class="issue-grid">\n{cards}  </div>\n'
    else:
        listing = ('  <p style="font-size:0.9rem;color:var(--text-muted);">'
                   "記事を準備中です。</p>\n")

    body = f"""<div class="hero">
  <div class="hero-inner">
    <div class="crumbs"><a href="../">{_html.escape(name)}</a></div>
    <h1>エッセイ</h1>
    <p>AIの使い方・学び方・仕事への活かし方。ニュースの一歩先を解説します。</p>
    <div class="hero-actions">
      <a class="btn btn-ghost" href="../">トップへ戻る</a>
    </div>
  </div>
</div>

<main>
{monetize.render_disclosure(config)}
{listing}</main>

<footer>
  <strong>{_html.escape(name)}</strong> — {_html.escape(site.get("author", ""))}
  {site_theme.footer_links(config, prefix="../")}
</footer>"""

    return site_theme.page_shell(f"エッセイ | {name}", head, body)


# ---------------------------------------------------------------- エントリポイント

def build_all(verbose: bool = True) -> List[Dict]:
    config = monetize.load_config()
    articles = collect_articles()
    published_slugs = {a["slug"] for a in articles}
    drafts = [a for a in collect_articles(include_drafts=True) if a["slug"] not in published_slugs]

    if not ARTICLES_DIR.exists():
        ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    for article in articles:
        related = [a for a in articles if a["slug"] != article["slug"]][:3]
        page = build_article_page(article, config, related)
        (ARTICLES_DIR / article["file"]).write_text(page, encoding="utf-8")
        if verbose:
            note = f"  ⚠️ 加筆マーカー {article['todo']} 箇所" if article["todo"] else ""
            print(f"✓ articles/{article['file']}{note}")

    (ARTICLES_DIR / "index.html").write_text(build_index_page(articles, config), encoding="utf-8")
    if verbose:
        print(f"✓ articles/index.html （公開 {len(articles)} 本 / 下書き {len(drafts)} 本）")
        for d in drafts:
            if d["todo"]:
                print(f"   ・公開保留: {d['source'].name} — 加筆マーカー {TODO_MARKER} が {d['todo']} 箇所残っています")
            else:
                print(f"   ・下書き: {d['source'].name} （status: published にすると公開されます）")

    return articles


def build_preview(verbose: bool = True) -> List[Dict]:
    """下書きを含めて .preview/ に出力する。公開物には一切影響しない。"""
    config = monetize.load_config()
    articles = collect_articles(include_drafts=True)
    out_dir = REPO_DIR / ".preview"
    out_dir.mkdir(exist_ok=True)

    for article in articles:
        related = [a for a in articles if a["slug"] != article["slug"]][:3]
        (out_dir / article["file"]).write_text(
            build_article_page(article, config, related), encoding="utf-8"
        )
        if verbose:
            print(f"👀 .preview/{article['file']}"
                  + (f"  （加筆マーカー {article['todo']} 箇所）" if article["todo"] else ""))
    return articles


if __name__ == "__main__":
    import sys
    if "--preview" in sys.argv:
        build_preview()
    else:
        build_all()
