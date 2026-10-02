#!/usr/bin/env python3
"""
収益化レイヤー — 生成済みの日次ダイジェスト HTML に
  1. SEO/OGP メタ（検索・SNS からの流入をつくる）
  2. アクセス解析タグ（どこが稼いでいるか測る）
  3. アフィリエイト枠 / 自社商品 CTA（収益化する）
を後付けで注入するモジュール。

設計方針:
  - 設定は monetize_config.json だけ。コードを触らずに ON/OFF できる。
  - url が空の案件は「表示しない」。空の広告枠や偽リンクは絶対に出さない。
  - 掲出時は必ず PR 表記を伴う（景品表示法のステマ規制対応）。
  - 設定ファイルが無くても例外を投げず、素の HTML をそのまま返す。
"""

import json
import zlib
import html as _html
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

REPO_DIR = Path(__file__).parent
CONFIG_FILE = REPO_DIR / "monetize_config.json"

_PLACEHOLDER_HINTS = ("your_", "xxxx", "ここに", "example.com", "取得後")


def load_config() -> Dict:
    """設定を読む。無ければ空 dict（＝収益化レイヤー全体が no-op になる）。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  monetize_config.json の読み込みに失敗: {e}")
        return {}


def site_url(fallback: str = "https://teraco-labo.github.io/ai-news-digest") -> str:
    """公開サイトのベースURL。

    アカウント移管や独自ドメインへの切り替えのたびに各スクリプトを直す羽目に
    ならないよう、URL は monetize_config.json の1箇所だけで決める。
    """
    try:
        url = load_config().get("site", {}).get("base_url", "")
        return url.rstrip("/") if url else fallback
    except Exception:
        return fallback


def podcast_url(fallback: str = "") -> str:
    """ポッドキャストの配信ベースURL。未設定ならサイトと同じURLを使う。"""
    try:
        url = load_config().get("podcast", {}).get("base_url", "")
        return url.rstrip("/") if url else site_url()
    except Exception:
        return fallback or site_url()


def _filled(value: Optional[str]) -> bool:
    """未設定・プレースホルダのままなら False。"""
    if not value or not str(value).strip():
        return False
    low = str(value).lower()
    return not any(h in low for h in _PLACEHOLDER_HINTS)


def active_offers(config: Dict) -> List[Dict]:
    """アフィリエイト URL が実際に埋まっている案件だけを返す。"""
    return [o for o in config.get("offers", []) if _filled(o.get("url"))]


# ---------------------------------------------------------------- 案件の選定

def _stable_hash(text: str) -> int:
    """PYTHONHASHSEED に左右されない安定ハッシュ（毎回同じ順序を再現するため）。"""
    return zlib.crc32(text.encode("utf-8")) % 97


def _score(offer: Dict, categories: List[str], text: str) -> int:
    score = int(offer.get("priority", 0))
    score += 3 * len(set(offer.get("categories", [])) & set(categories))
    low = text.lower()
    score += 2 * sum(1 for kw in offer.get("keywords", []) if kw.lower() in low)
    return score


def select_offers(config: Dict, categorized: Optional[Dict[str, List[Dict]]],
                  date: datetime, limit: int) -> List[Dict]:
    """その日の記事内容に合う案件を、日付で決まる順序（＝毎日少しずつ入れ替わる）で選ぶ。"""
    offers = active_offers(config)
    if not offers or limit <= 0:
        return []

    categories: List[str] = []
    text = ""
    if categorized:
        categories = [c for c, items in categorized.items() if items]
        for items in categorized.values():
            for a in items:
                text += f" {a.get('title_en', '')} {a.get('title_ja', '')} {a.get('summary', '')}"

    rotation = int(date.strftime("%Y%m%d"))
    ranked = sorted(
        offers,
        key=lambda o: (-_score(o, categories, text),
                       (rotation + _stable_hash(o.get("id", ""))) % max(len(offers), 1),
                       o.get("id", "")),
    )
    return ranked[:limit]


# ---------------------------------------------------------------- パーツの描画

def _css() -> str:
    return """
<style id="mz-style">
  .mz-disclosure { max-width: 1100px; margin: 0 auto 1rem; padding: 0.5rem 0.75rem;
    font-size: 0.7rem; line-height: 1.6; color: var(--text-muted, #64748b);
    background: rgba(148,163,184,0.10); border-radius: 6px; }
  .mz-block { max-width: 1100px; margin: 2rem auto; }
  .mz-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem; }
  .mz-head h2 { font-size: 0.9rem; font-weight: 700; color: var(--text, #1e293b); letter-spacing: 0.02em; }
  .mz-pr { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.08em; padding: 2px 6px;
    border-radius: 3px; background: #94a3b8; color: #fff; }
  .mz-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1rem; }
  .mz-card { display: flex; flex-direction: column; gap: 0.4rem; padding: 1rem;
    background: var(--card-bg, #fff); border: 1px solid var(--border, #e2e8f0);
    border-left: 3px solid #0e7490; border-radius: 8px; }
  .mz-card .mz-name { font-size: 0.68rem; font-weight: 600; color: var(--text-muted, #64748b); letter-spacing: 0.04em; }
  .mz-card .mz-title { font-size: 0.95rem; font-weight: 700; color: var(--text, #1e293b); line-height: 1.5; }
  .mz-card .mz-body { font-size: 0.8rem; line-height: 1.7; color: var(--text-muted, #64748b); }
  .mz-card .mz-cta { margin-top: auto; padding-top: 0.6rem; font-size: 0.8rem; font-weight: 600;
    color: #0e7490; text-decoration: none; }
  .mz-card .mz-cta:hover { text-decoration: underline; }
  .mz-badge { align-self: flex-start; font-size: 0.6rem; font-weight: 700; padding: 2px 6px;
    border-radius: 3px; background: #0e7490; color: #fff; }
  .mz-cta-block { max-width: 1100px; margin: 2rem auto; padding: 1.5rem;
    background: linear-gradient(135deg, #0f172a, #1e293b); border-radius: 10px; color: #e2e8f0; }
  .mz-cta-block h2 { font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem; color: #fff; }
  .mz-cta-block p { font-size: 0.85rem; line-height: 1.8; color: #cbd5e1; }
  .mz-cta-block a { display: inline-block; margin-top: 0.9rem; padding: 0.6rem 1.4rem;
    background: #22d3ee; color: #0f172a; font-size: 0.85rem; font-weight: 700;
    border-radius: 6px; text-decoration: none; }
  .mz-ad { max-width: 1100px; margin: 2rem auto; text-align: center; }
</style>
"""


def _offer_card(offer: Dict) -> str:
    badge = offer.get("badge", "")
    badge_html = f'      <span class="mz-badge">{_html.escape(badge)}</span>\n' if badge else ""
    return (
        '    <div class="mz-card">\n'
        f'{badge_html}'
        f'      <div class="mz-name">{_html.escape(offer.get("name", ""))}</div>\n'
        f'      <div class="mz-title">{_html.escape(offer.get("headline", ""))}</div>\n'
        f'      <div class="mz-body">{_html.escape(offer.get("body", ""))}</div>\n'
        f'      <a class="mz-cta" href="{_html.escape(offer.get("url", ""))}" '
        f'target="_blank" rel="nofollow sponsored noopener" '
        f'data-mz-offer="{_html.escape(offer.get("id", ""))}">詳しく見る →</a>\n'
        '    </div>\n'
    )


def render_offer_block(offers: List[Dict], heading: str = "スポンサー") -> str:
    if not offers:
        return ""
    cards = "".join(_offer_card(o) for o in offers)
    return (
        '\n  <section class="mz-block">\n'
        '    <div class="mz-head">\n'
        '      <span class="mz-pr">PR</span>\n'
        f'      <h2>{_html.escape(heading)}</h2>\n'
        '    </div>\n'
        '    <div class="mz-grid">\n'
        f'{cards}'
        '    </div>\n'
        '  </section>\n'
    )


def render_disclosure(config: Dict) -> str:
    d = config.get("disclosure", {})
    if not d.get("enabled") or not d.get("text"):
        return ""
    if not active_offers(config) and not config.get("adsense", {}).get("enabled"):
        return ""  # 広告を1つも出していない日は開示文も出さない
    return f'\n  <div class="mz-disclosure">{_html.escape(d["text"])}</div>\n'


def render_cta(config: Dict) -> str:
    cta = config.get("cta", {})
    if not cta.get("enabled") or not _filled(cta.get("url")) or not _filled(cta.get("button_label")):
        return ""
    return (
        '\n  <section class="mz-cta-block">\n'
        f'    <h2>{_html.escape(cta.get("heading", ""))}</h2>\n'
        f'    <p>{_html.escape(cta.get("body", ""))}</p>\n'
        f'    <a href="{_html.escape(cta["url"])}" target="_blank" rel="noopener" '
        f'data-mz-cta="1">{_html.escape(cta["button_label"])}</a>\n'
        '  </section>\n'
    )


def render_adsense_unit(config: Dict) -> str:
    ad = config.get("adsense", {})
    if not ad.get("enabled") or not _filled(ad.get("client_id")) or not _filled(ad.get("in_article_slot")):
        return ""
    return (
        '\n  <div class="mz-ad">\n'
        '    <ins class="adsbygoogle" style="display:block" '
        f'data-ad-client="{_html.escape(ad["client_id"])}" '
        f'data-ad-slot="{_html.escape(ad["in_article_slot"])}" '
        'data-ad-format="auto" data-full-width-responsive="true"></ins>\n'
        '    <script>(adsbygoogle = window.adsbygoogle || []).push({});</script>\n'
        '  </div>\n'
    )


# ---------------------------------------------------------------- head の注入

def build_head_tags(config: Dict, *, page_url: str, title: str,
                    description: str, published: str = "") -> str:
    site = config.get("site", {})
    parts = ["\n<!-- monetize.py: SEO / analytics -->\n"]

    parts.append(f'<meta name="description" content="{_html.escape(description)}">\n')
    parts.append(f'<link rel="canonical" href="{_html.escape(page_url)}">\n')
    parts.append('<meta name="robots" content="index, follow, max-image-preview:large">\n')

    parts.append('<meta property="og:type" content="article">\n')
    parts.append(f'<meta property="og:title" content="{_html.escape(title)}">\n')
    parts.append(f'<meta property="og:description" content="{_html.escape(description)}">\n')
    parts.append(f'<meta property="og:url" content="{_html.escape(page_url)}">\n')
    parts.append(f'<meta property="og:site_name" content="{_html.escape(site.get("name", ""))}">\n')
    parts.append(f'<meta property="og:locale" content="{_html.escape(site.get("locale", "ja_JP"))}">\n')
    if site.get("base_url"):
        parts.append(f'<meta property="og:image" content="{_html.escape(site["base_url"])}/podcast/cover.jpg">\n')
    parts.append('<meta name="twitter:card" content="summary_large_image">\n')
    if _filled(site.get("twitter")):
        parts.append(f'<meta name="twitter:site" content="{_html.escape(site["twitter"])}">\n')

    if site.get("base_url"):
        parts.append(
            f'<link rel="alternate" type="application/rss+xml" title="{_html.escape(site.get("name", ""))}" '
            f'href="{_html.escape(site["base_url"])}/feed.xml">\n'
        )

    jsonld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "description": description,
        "url": page_url,
        "inLanguage": "ja",
        "author": {"@type": "Person", "name": site.get("author", "")},
        "publisher": {"@type": "Organization", "name": site.get("name", "")},
    }
    if published:
        jsonld["datePublished"] = published
        jsonld["dateModified"] = published
    parts.append(
        '<script type="application/ld+json">'
        + json.dumps(jsonld, ensure_ascii=False)
        + "</script>\n"
    )

    ga = config.get("analytics", {}).get("ga4_measurement_id", "")
    if _filled(ga):
        parts.append(
            f'<script async src="https://www.googletagmanager.com/gtag/js?id={_html.escape(ga)}"></script>\n'
            "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
            f"gtag('js',new Date());gtag('config','{_html.escape(ga)}');</script>\n"
        )

    clarity = config.get("analytics", {}).get("clarity_id", "")
    if _filled(clarity):
        parts.append(
            "<script>(function(c,l,a,r,i,t,y){c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};"
            "t=l.createElement(r);t.async=1;t.src=\"https://www.clarity.ms/tag/\"+i;"
            "y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);})"
            f"(window,document,'clarity','script','{_html.escape(clarity)}');</script>\n"
        )

    ad = config.get("adsense", {})
    if ad.get("enabled") and _filled(ad.get("client_id")):
        parts.append(
            '<script async crossorigin="anonymous" '
            f'src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={_html.escape(ad["client_id"])}">'
            "</script>\n"
        )

    parts.append(_css())

    # アフィリエイトリンクのクリックを GA4 イベントとして記録する
    if _filled(ga):
        parts.append(
            "<script>document.addEventListener('click',function(e){"
            "var a=e.target.closest('[data-mz-offer],[data-mz-cta]');if(!a)return;"
            "gtag('event','affiliate_click',{offer_id:a.getAttribute('data-mz-offer')||'cta',"
            "link_url:a.href,page:location.pathname});});</script>\n"
        )

    return "".join(parts)


# ---------------------------------------------------------------- 注入本体

def _insert_before(haystack: str, marker: str, payload: str) -> str:
    idx = haystack.find(marker)
    if idx < 0:
        return haystack
    return haystack[:idx] + payload + haystack[idx:]


def apply_to_digest(html_output: str, categorized: Optional[Dict[str, List[Dict]]],
                    date: datetime, config: Optional[Dict] = None) -> str:
    """日次ダイジェスト HTML に SEO と収益枠を注入して返す。"""
    config = config if config is not None else load_config()
    if not config:
        return html_output

    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    date_iso = date.strftime("%Y-%m-%d")
    page_url = f"{base}/ai-news-{date_iso}.html" if base else ""

    total = sum(len(v) for v in (categorized or {}).values())
    import site_theme
    title = f"{site_theme.issue_label(date)} | {site.get('name', '')}"
    description = (
        f"{date.strftime('%Y年%m月%d日')}のAI関連ニュース{total}件を日本語で要約。"
        "モデル・研究・ビジネス・ポリシー・ツールの5カテゴリで重要ニュースだけを厳選しています。"
    )

    # 1. head
    html_output = _insert_before(
        html_output, "</head>",
        build_head_tags(config, page_url=page_url, title=title,
                        description=description, published=f"{date_iso}T06:00:00+09:00"),
    )

    # 2. 開示文（<main> 直後）
    disclosure = render_disclosure(config)
    if disclosure:
        idx = html_output.find("<main>")
        if idx >= 0:
            cut = idx + len("<main>")
            html_output = html_output[:cut] + "\n" + disclosure + html_output[cut:]

    slots = config.get("slots", {})
    n_mid = int(slots.get("in_content_offers", 0))
    n_foot = int(slots.get("footer_offers", 0))
    # 記事中と末尾で同じ案件が並ばないよう、まとめて選んでから振り分ける
    picked = select_offers(config, categorized, date, n_mid + n_foot)
    mid_offers, foot_offers = picked[:n_mid], picked[n_mid:n_mid + n_foot]

    # 3. 記事の途中（2つ目のカテゴリ見出しの直前）に差し込む
    in_content = render_offer_block(mid_offers, heading="今日のニュースに関連するサービス")
    if in_content:
        marker = '<div class="section-label"'
        first = html_output.find(marker)
        second = html_output.find(marker, first + 1) if first >= 0 else -1
        if second >= 0:
            html_output = html_output[:second] + in_content + "\n  " + html_output[second:]
        else:
            html_output = _insert_before(html_output, "</main>", in_content)

    # 4. ダイジェストのフッターにも運営者情報への導線を置く。
    #    広告を出すページから免責事項に辿れないのは、実務上まずい。
    try:
        import site_theme
        links = site_theme.footer_links(config)
        if "footer-links" not in html_output:
            html_output = _insert_before(
                html_output, "</footer>",
                '  <style>.footer-links{margin-top:0.9rem;font-size:0.72rem}'
                '.footer-links a{color:inherit;text-decoration:none;opacity:0.8}'
                '.footer-links a:hover{text-decoration:underline}</style>\n  ' + links + "\n",
            )
    except Exception as e:
        print(f"⚠️  フッターリンクの挿入をスキップしました: {e}")

    # 5. 本文末尾（</main> 直前）: AdSense → 案件 → 自社 CTA
    tail = render_adsense_unit(config)
    tail += render_offer_block(foot_offers, heading="AIを仕事にしたい人向け")
    tail += render_cta(config)
    if tail:
        html_output = _insert_before(html_output, "</main>", tail)

    return html_output


if __name__ == "__main__":
    cfg = load_config()
    live = active_offers(cfg)
    print(f"設定ファイル      : {'OK' if cfg else '未読込'}")
    print(f"登録済み案件      : {len(cfg.get('offers', []))} 件")
    print(f"うち掲出中(url有) : {len(live)} 件")
    for o in cfg.get("offers", []):
        mark = "✓" if _filled(o.get("url")) else "—"
        print(f"  {mark} {o['id']:<16} 想定単価 {o.get('payout_jpy_est', 0):>7,}円  ASP: {o.get('asp', '')}")
    print(f"GA4               : {'設定済み' if _filled(cfg.get('analytics', {}).get('ga4_measurement_id')) else '未設定'}")
    print(f"AdSense           : {'有効' if cfg.get('adsense', {}).get('enabled') else '無効'}")
