#!/usr/bin/env python3
"""
ニュースレター用のHTML生成。

読者リストを育てるための中核。用途は2つ:

  1. RSS の <content:encoded> に本文を丸ごと載せる
     → Substack / beehiiv / Kit / MailerLite などの「RSSから自動配信」機能が
       そのまま使える。連携先を変えてもこちら側の実装は不要。
  2. 各サービスのAPIへ直接投げる（将来）

メール用なので制約がある:
  - <style> は多くのメールクライアントで無効化される → **すべてインラインstyle**
  - JavaScript は動かない → 用語解説のポップアップは使えないため、
    代わりに本文末尾へ「今日の用語」として定義をまとめて置く
"""

import html as _html
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import glossary
import monetize
import podcast_store
import social_kit

REPO_DIR = Path(__file__).parent

CATEGORIES = ["model", "research", "business", "policy", "tools"]
CATEGORIES_JA = {
    "model": "モデル", "research": "研究", "business": "ビジネス",
    "policy": "ポリシー", "tools": "ツール",
}
CAT_COLOR = {
    "model": "#1d4ed8", "research": "#6d28d9", "business": "#065f46",
    "policy": "#92400e", "tools": "#0e7490",
}
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

# メールでは font-family を各要素に書かないと Outlook 等で崩れる
FONT = "'Hiragino Sans','Noto Sans JP','Yu Gothic',sans-serif"


def _esc(t: str) -> str:
    return _html.escape(str(t or ""))


def _lead_block(overview: List[str]) -> str:
    if not overview:
        return ""
    items = "".join(
        f'<li style="margin:0 0 10px;font-size:15px;line-height:1.85;color:#1e293b;">'
        f"{_esc(line)}</li>"
        for line in overview
    )
    return (
        f'<div style="margin:0 0 28px;padding:18px 20px;background:#f1f5f9;'
        f'border-radius:8px;font-family:{FONT};">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;'
        f'color:#64748b;margin:0 0 12px;">今日の3行まとめ</div>'
        f'<ol style="margin:0;padding-left:20px;">{items}</ol></div>'
    )


def _card(a: Dict, emphasize: bool) -> str:
    cat = a.get("category", "research")
    color = CAT_COLOR.get(cat, "#64748b")
    stars = "●" * int(a.get("importance", 2))
    title_size = "19px" if emphasize else "16px"
    url = a.get("url", "")
    link = (f'<a href="{_esc(url)}" style="color:{color};font-size:13px;'
            f'font-weight:600;text-decoration:none;">元記事を読む →</a>') if url else ""
    return (
        f'<div style="margin:0 0 18px;padding:16px 18px;background:#ffffff;'
        f'border:1px solid #e2e8f0;border-left:3px solid {color};border-radius:6px;'
        f'font-family:{FONT};">'
        f'<div style="font-size:11px;font-weight:700;color:{color};margin:0 0 8px;">'
        f'{CATEGORIES_JA.get(cat, cat)} <span style="color:#cbd5e1;">{stars}</span></div>'
        f'<div style="font-size:{title_size};font-weight:700;line-height:1.55;'
        f'color:#0f172a;margin:0 0 8px;">{_esc(a.get("title_ja"))}</div>'
        f'<div style="font-size:14px;line-height:1.9;color:#334155;margin:0 0 10px;">'
        f'{_esc(a.get("summary"))}</div>{link}</div>'
    )


def _terms_block(articles: List[Dict], base: str, limit: int = 6) -> str:
    """本文に出てきた用語の定義をまとめて載せる。

    メールではポップアップが使えないため、このサイトの売りである
    「専門用語ぜんぶ解説つき」をニュースレターでも成立させるための代替。
    """
    ann = glossary.Annotator(limit=limit)
    for a in articles:
        ann(_esc(a.get("title_ja", "")))
        ann(_esc(a.get("summary", "")))
    if not ann.used:
        return ""

    rows = ""
    for slug in sorted(ann.used):
        t = ann.terms.get(slug)
        if not t:
            continue
        reading = f'（{_esc(t["reading"])}）' if t.get("reading") else ""
        link = f"{base}/terms/{slug}.html" if base else ""
        name = (f'<a href="{link}" style="color:#0e7490;text-decoration:none;">'
                f'{_esc(t["term"])}</a>') if link else _esc(t["term"])
        rows += (
            f'<div style="margin:0 0 14px;">'
            f'<div style="font-size:14px;font-weight:700;color:#0f172a;">'
            f'{name}<span style="font-weight:400;font-size:12px;color:#64748b;">'
            f"{reading}</span></div>"
            f'<div style="font-size:13px;line-height:1.85;color:#475569;margin-top:3px;">'
            f'{_esc(t["short"])}</div></div>'
        )

    return (
        f'<div style="margin:32px 0 0;padding:20px;background:#f8fafc;'
        f'border:1px dashed #cbd5e1;border-radius:8px;font-family:{FONT};">'
        f'<div style="font-size:12px;font-weight:700;letter-spacing:1px;color:#64748b;'
        f'margin:0 0 14px;">📘 今日の用語</div>{rows}</div>'
    )


def build_html(date_iso: str, config: Optional[Dict] = None,
               include_terms: bool = True) -> Optional[str]:
    """指定日のダイジェストを、メールで読める形のHTMLにする。"""
    config = config if config is not None else monetize.load_config()
    path = REPO_DIR / f"ai-news-{date_iso}.html"
    if not path.exists():
        return None

    categorized = social_kit.load_from_html(date_iso)
    articles = [{**a, "category": c} for c in CATEGORIES for a in categorized.get(c, [])]
    if not articles:
        return None

    import digest_page
    overview = digest_page.extract_overview(path.read_text(encoding="utf-8"))

    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    pod_base = config.get("podcast", {}).get("base_url", base).rstrip("/")
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    date_label = f"{dt.year}年{dt.month}月{dt.day}日（{WEEKDAYS_JA[dt.weekday()]}）"

    articles.sort(key=lambda a: (-int(a.get("importance", 2)), a["category"]))
    top = [a for a in articles if int(a.get("importance", 2)) >= 3] or articles[:1]
    rest = [a for a in articles if a not in top]

    audio = ""
    if podcast_store.has_audio(date_iso) and pod_base:
        audio = (
            f'<div style="margin:0 0 28px;padding:16px 18px;background:#0f172a;'
            f'border-radius:8px;font-family:{FONT};">'
            f'<div style="font-size:14px;font-weight:700;color:#ffffff;margin:0 0 4px;">'
            f"🎧 音声版もあります</div>"
            f'<div style="font-size:12px;color:#cbd5e1;margin:0 0 12px;">'
            f"通勤中や作業中に、対話形式で聴けます（10〜15分）</div>"
            f'<a href="{podcast_store.audio_url(date_iso)}" '
            f'style="display:inline-block;padding:9px 18px;background:#22d3ee;color:#0f172a;'
            f'font-size:13px;font-weight:700;border-radius:6px;text-decoration:none;">'
            f"再生する →</a></div>"
        )

    body = _lead_block(overview) + audio
    body += ('<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;color:#64748b;'
             f'margin:0 0 14px;font-family:{FONT};">注目のニュース</div>')
    body += "".join(_card(a, True) for a in top)
    if rest:
        body += ('<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;'
                 f'color:#64748b;margin:26px 0 14px;font-family:{FONT};">そのほかの動き</div>')
        body += "".join(_card(a, False) for a in rest)
    if include_terms:
        body += _terms_block(articles, base)

    web = (f'<div style="margin:28px 0 0;text-align:center;font-family:{FONT};">'
           f'<a href="{base}/" style="font-size:13px;color:#0e7490;text-decoration:none;">'
           f"ブラウザで読む（用語にカーソルを乗せると解説が出ます）→</a></div>") if base else ""

    return (
        f'<div style="max-width:640px;margin:0 auto;padding:24px 16px;font-family:{FONT};">'
        f'<div style="margin:0 0 6px;font-size:12px;color:#64748b;">{date_label}</div>'
        f'<div style="margin:0 0 24px;font-size:22px;font-weight:700;color:#0f172a;">'
        f'{_esc(site.get("name"))}</div>'
        f"{body}{web}</div>"
    )


if __name__ == "__main__":
    import sys
    date_iso = sys.argv[1] if len(sys.argv) > 1 else None
    if not date_iso:
        files = sorted(REPO_DIR.glob("ai-news-*.html"), reverse=True)
        date_iso = re.findall(r"(\d{4}-\d{2}-\d{2})", files[0].name)[0]
    html = build_html(date_iso)
    if html:
        out = REPO_DIR / ".preview"; out.mkdir(exist_ok=True)
        (out / f"newsletter-{date_iso}.html").write_text(html, encoding="utf-8")
        print(f"👀 .preview/newsletter-{date_iso}.html （{len(html):,} bytes）")
    else:
        print(f"{date_iso} のダイジェストが見つかりません")
