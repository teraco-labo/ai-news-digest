#!/usr/bin/env python3
"""
サイト共通のガワ（CSS とページ骨格）。
トップ・アーカイブ・解説記事がすべて同じ見た目になるよう1箇所に集約する。
"""

import html as _html

PAGE_CSS = """
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root { --bg:#f8fafc; --card-bg:#fff; --text:#1e293b; --text-muted:#64748b; --border:#e2e8f0; --accent:#0e7490; }
  body { font-family:'Noto Sans JP','Inter',sans-serif; background:var(--bg); color:var(--text);
    line-height:1.7; -webkit-font-smoothing:antialiased; }
  a { color:inherit; }
  .hero { background:linear-gradient(135deg,#0f172a,#1e293b); color:#fff; padding:3rem 1.5rem; }
  .hero-inner { max-width:1100px; margin:0 auto; }
  .hero h1 { font-size:1.8rem; font-weight:700; letter-spacing:0.01em; }
  .hero p { margin-top:0.6rem; font-size:0.95rem; color:#cbd5e1; max-width:640px; }
  .hero-actions { margin-top:1.5rem; display:flex; flex-wrap:wrap; gap:0.75rem; }
  .crumbs { font-size:0.75rem; color:#94a3b8; margin-bottom:0.75rem; }
  .crumbs a { text-decoration:none; }
  .crumbs a:hover { text-decoration:underline; }
  .btn { display:inline-block; padding:0.6rem 1.3rem; border-radius:6px; font-size:0.85rem;
    font-weight:700; text-decoration:none; }
  .btn-primary { background:#22d3ee; color:#0f172a; }
  .btn-ghost { border:1px solid rgba(255,255,255,0.35); color:#e2e8f0; }
  main { max-width:1100px; margin:0 auto; padding:2.5rem 1.5rem 4rem; }
  .section-label { font-size:0.75rem; font-weight:700; letter-spacing:0.12em; color:var(--text-muted);
    text-transform:uppercase; margin:2.5rem 0 1rem; }
  .section-label:first-child { margin-top:0; }
  .issue-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:1rem; }
  .issue { display:block; padding:1rem 1.1rem; background:var(--card-bg); border:1px solid var(--border);
    border-radius:8px; text-decoration:none; transition:border-color .15s; }
  .issue:hover { border-color:var(--accent); }
  .issue .d { font-size:0.95rem; font-weight:700; }
  .issue .m { margin-top:0.25rem; font-size:0.75rem; color:var(--text-muted); }
  .issue-list { list-style:none; columns:2; column-gap:2rem; }
  .issue-list li { break-inside:avoid; padding:0.35rem 0; border-bottom:1px solid var(--border); }
  .issue-list a { font-size:0.85rem; text-decoration:none; }
  .issue-list a:hover { color:var(--accent); }
  .issue-list .m { font-size:0.72rem; color:var(--text-muted); margin-left:0.5rem; }
  footer { border-top:1px solid var(--border); padding:2rem 1.5rem; text-align:center;
    font-size:0.78rem; color:var(--text-muted); }
  .sub-grid { max-width:760px; margin:0 auto; display:grid;
    grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:0.8rem; }
  .sub-card { display:flex; flex-direction:column; gap:0.3rem; padding:1.1rem 1.2rem;
    background:var(--card-bg); border:1px solid var(--border); border-radius:8px;
    text-decoration:none; transition:border-color .15s; }
  .sub-card:hover { border-color:var(--accent); }
  .sub-card.mail { border-color:var(--accent); border-width:2px;
    background:linear-gradient(180deg,rgba(14,116,144,0.05),transparent); }
  .sub-embed { cursor:default; }
  .sub-badge { display:block; margin-top:0.5rem; padding:0.6rem; text-align:center;
    border-radius:6px; font-size:0.85rem; font-weight:700; text-decoration:none; color:#fff; }
  .sub-badge.spotify { background:#1db954; }
  .sub-badge.apple { background:#8e44ec; }
  .sub-copy { margin-top:0.6rem; width:100%; padding:0.6rem; background:var(--accent);
    color:#fff; font-size:0.85rem; font-weight:700; border:none; border-radius:6px;
    cursor:pointer; }
  .sub-advanced { max-width:760px; margin:0.8rem auto 0; font-size:0.72rem;
    color:var(--text-muted); }
  .sub-advanced a { color:var(--text-muted); }
  .sub-embed form { margin-top:0.5rem; }
  .sub-embed input[type="email"] { width:100%; padding:0.6rem 0.8rem; font-size:0.9rem;
    border:1px solid var(--border); border-radius:6px; background:var(--bg); color:var(--text); }
  .sub-embed button, .sub-embed input[type="submit"] { margin-top:0.5rem; width:100%;
    padding:0.65rem; background:var(--accent); color:#fff; font-size:0.88rem; font-weight:700;
    border:none; border-radius:6px; cursor:pointer; }
  .sub-ico { font-size:1.2rem; }
  .sub-t { font-size:0.92rem; font-weight:700; }
  .sub-d { font-size:0.76rem; line-height:1.7; color:var(--text-muted); }
  .lang-switch { display:flex; flex-wrap:wrap; align-items:center; gap:0.35rem;
    margin-top:1rem; font-size:0.74rem; }
  .lang-switch .globe { opacity:0.7; margin-right:0.15rem; }
  .lang-switch .lang { padding:0.25rem 0.7rem; border-radius:999px;
    border:1px solid rgba(255,255,255,0.25); color:#cbd5e1; text-decoration:none; }
  .lang-switch a.lang:hover { background:rgba(255,255,255,0.12); color:#fff; }
  .lang-switch .lang.on { background:rgba(255,255,255,0.9); color:#0f172a; font-weight:700;
    border-color:transparent; }
  .lang-switch .lang.soon { opacity:0.45; cursor:default; }
  .lang-switch .lang.soon em { font-style:normal; font-size:0.62rem; margin-left:0.3rem;
    opacity:0.85; }
  .footer-links { margin-top:0.9rem; font-size:0.75rem; }
  .footer-links a { color:var(--text-muted); text-decoration:none; }
  .footer-links a:hover { color:var(--accent); text-decoration:underline; }
  .footer-brand { margin-top:1.1rem; font-size:0.68rem; letter-spacing:0.04em;
    color:var(--text-muted); opacity:0.55; }
  @media (max-width:640px){ .issue-list{columns:1;} .hero h1{font-size:1.4rem;} }
"""

# 解説記事の本文用。読み物として成立する行間・見出し設計にする。
LEGAL_CSS = """
  .legal { max-width:720px; margin:0 auto; }
  .legal h2 { margin:2.2rem 0 0.7rem; font-size:1.05rem; font-weight:700; }
  .legal h2:first-child { margin-top:0; }
  .legal p { font-size:0.88rem; line-height:1.95; color:var(--text-muted); }
  .legal p + p { margin-top:0.8rem; }
  .legal dl { display:grid; grid-template-columns:auto 1fr; gap:0.5rem 1.5rem; font-size:0.88rem; }
  .legal dt { font-weight:700; white-space:nowrap; }
  .legal dd { margin:0; color:var(--text-muted); }
  .legal .strong-note { padding:1rem 1.2rem; background:rgba(14,116,144,0.07);
    border-left:3px solid var(--accent); border-radius:0 6px 6px 0; }
  .legal .strong-note p { color:var(--text); font-weight:500; }
"""

PROSE_CSS = """
  .prose { max-width:720px; margin:0 auto; }
  .prose > * + * { margin-top:1.1rem; }
  .prose h2 { margin-top:2.8rem; padding-bottom:0.5rem; border-bottom:2px solid var(--border);
    font-size:1.3rem; font-weight:700; line-height:1.5; }
  .prose h3 { margin-top:2rem; font-size:1.05rem; font-weight:700; }
  .prose p { font-size:0.95rem; line-height:2.0; }
  .prose ul, .prose ol { padding-left:1.4rem; }
  .prose li { font-size:0.95rem; line-height:1.9; margin-top:0.4rem; }
  .prose a { color:var(--accent); font-weight:500; }
  .prose strong { font-weight:700; }
  .prose blockquote { padding:0.8rem 1.1rem; border-left:3px solid var(--accent);
    background:rgba(14,116,144,0.06); border-radius:0 6px 6px 0; font-size:0.9rem; }
  .prose blockquote p { font-size:0.9rem; line-height:1.85; }
  .prose code { padding:0.15em 0.4em; background:#e2e8f0; border-radius:3px;
    font-family:'SFMono-Regular',Consolas,monospace; font-size:0.85em; }
  .prose pre { padding:1rem; background:#0f172a; color:#e2e8f0; border-radius:8px;
    overflow-x:auto; font-size:0.82rem; line-height:1.7; }
  .prose pre code { background:none; color:inherit; padding:0; }
  .prose table { width:100%; border-collapse:collapse; font-size:0.85rem; display:block; overflow-x:auto; }
  .prose th, .prose td { padding:0.6rem 0.8rem; border:1px solid var(--border); text-align:left; }
  .prose th { background:#f1f5f9; font-weight:700; white-space:nowrap; }
  .prose hr { border:none; border-top:1px solid var(--border); margin:2.5rem 0; }
  .prose img { max-width:100%; height:auto; border-radius:8px; }
  .toc { max-width:720px; margin:2rem auto; padding:1.1rem 1.3rem; background:var(--card-bg);
    border:1px solid var(--border); border-radius:8px; }
  .toc-title { font-size:0.75rem; font-weight:700; letter-spacing:0.1em; color:var(--text-muted);
    margin-bottom:0.6rem; }
  .toc ol { list-style:none; counter-reset:toc; }
  .toc li { counter-increment:toc; padding:0.25rem 0; font-size:0.85rem; }
  .toc li::before { content:counter(toc) ". "; color:var(--text-muted); }
  .toc a { text-decoration:none; }
  .toc a:hover { color:var(--accent); text-decoration:underline; }
  .article-meta { max-width:720px; margin:0 auto 2rem; font-size:0.78rem; color:var(--text-muted); }
"""


def newsletter_links(config: dict) -> dict:
    """メール購読の「登録ページURL」と「埋め込みフォーム」を設定から組み立てる。
    provider=substack なら substack_url 1つから両方作る（Substack は /subscribe と /embed を用意している）。
    signup_url / embed_html が直接書かれていればそちらを優先。未設定なら空＝どこにも出ない。"""
    nl = config.get("newsletter", {})
    if not nl.get("enabled", True):
        return {"signup_url": "", "embed_html": ""}
    signup = nl.get("signup_url", "").strip()
    embed = nl.get("embed_html", "").strip()
    base = nl.get("substack_url", "").strip().rstrip("/")
    if nl.get("provider") == "substack" and base:
        signup = signup or f"{base}/subscribe"
        embed = embed or (f'<iframe src="{base}/embed" width="100%" height="150" '
                          'style="border:1px solid var(--border);border-radius:6px;background:#fff;" '
                          'frameborder="0" scrolling="no" title="メールマガジン登録"></iframe>')
    return {"signup_url": signup, "embed_html": embed}


def subscribe_block(config: dict, prefix: str = "") -> str:
    """購読の導線。

    「RSS」のような作り手側の言葉を読者に見せない。
    メールは「メールマガジン」、音声は「Spotify / Apple Podcast」という
    誰でも知っている名前で置き、RSS は上級者向けの補足に格下げする。
    """
    site = config.get("site", {})
    nl = config.get("newsletter", {})
    pod_cfg = config.get("podcast", {})
    pod = pod_cfg.get("base_url", site.get("base_url", "")).rstrip("/")

    cards = []

    # --- メールマガジン ---
    links = newsletter_links(config)
    embed = links["embed_html"]
    if embed:
        cards.append(
            '    <div class="sub-card mail sub-embed">\n'
            '      <span class="sub-ico">✉️</span>\n'
            '      <span class="sub-t">メールマガジンで受け取る</span>\n'
            f'      <span class="sub-d">{_html.escape(nl.get("blurb", ""))}</span>\n'
            f"      {embed}\n"
            "    </div>\n"
        )
    elif links["signup_url"]:
        cards.append(
            f'    <a class="sub-card mail" href="{_html.escape(links["signup_url"])}">\n'
            '      <span class="sub-ico">✉️</span>\n'
            '      <span class="sub-t">メールマガジンで受け取る</span>\n'
            f'      <span class="sub-d">{_html.escape(nl.get("blurb", ""))} 無料・いつでも解除できます</span>\n'
            "    </a>\n"
        )

    # --- ポッドキャスト ---
    spotify = pod_cfg.get("spotify_url", "").strip()
    apple = pod_cfg.get("apple_url", "").strip()
    feed_url = f"{pod}/podcast/feed.xml" if pod else ""
    if spotify or apple:
        badges = ""
        if spotify:
            badges += (f'      <a class="sub-badge spotify" href="{_html.escape(spotify)}">'
                       "Spotify で聴く</a>\n")
        if apple:
            badges += (f'      <a class="sub-badge apple" href="{_html.escape(apple)}">'
                       "Apple Podcast で聴く</a>\n")
        cards.append(
            '    <div class="sub-card sub-embed">\n'
            '      <span class="sub-ico">🎧</span>\n'
            '      <span class="sub-t">ポッドキャストで聴く</span>\n'
            '      <span class="sub-d">通勤中や作業中に。毎朝10〜15分の音声版です</span>\n'
            f"{badges}"
            "    </div>\n"
        )
    elif feed_url:
        # 番組登録が済むまでの暫定。アプリへの登録方法を言葉で案内する
        cards.append(
            '    <div class="sub-card sub-embed">\n'
            '      <span class="sub-ico">🎧</span>\n'
            '      <span class="sub-t">ポッドキャストで聴く</span>\n'
            '      <span class="sub-d">お使いのポッドキャストアプリの「番組を追加」「URLで追加」に、'
            "下のボタンでコピーした番組アドレスを貼り付けてください</span>\n"
            f'      <button type="button" class="sub-copy" data-copy="{_html.escape(feed_url)}" '
            "onclick=\"navigator.clipboard.writeText(this.dataset.copy)"
            ".then(()=>{this.textContent='✓ コピーしました';"
            "setTimeout(()=>this.textContent='番組アドレスをコピー',2000);});\">"
            "番組アドレスをコピー</button>\n"
            "    </div>\n"
        )

    if not cards:
        return ""

    # RSS は上級者向けの一行に格下げ（一般の読者には意味が通らないため）
    advanced = (
        '  <p class="sub-advanced">上級者向け：'
        f'<a href="{prefix}feed.xml">RSS配信</a>'
        "（サイトの更新を自動で受け取るための仕組みです。Feedly などの"
        "RSSリーダーをお使いの方はこちらを登録してください）</p>\n"
    )

    return ('  <div class="section-label">毎朝うけとる</div>\n'
            f'  <div class="sub-grid">\n{"".join(cards)}  </div>\n'
            + advanced)


def lang_switch(config: dict, prefix: str = "") -> str:
    """言語切り替え。未対応の言語は「準備中」として無効表示にする。

    先に置き場所を作っておくことで、英語版を出したときに
    設定の status を live にするだけで切り替えが有効になる。
    """
    langs = config.get("site", {}).get("languages", [])
    if len(langs) < 2:
        return ""
    current = config.get("site", {}).get("lang", "ja")
    items = []
    for l in langs:
        label = _html.escape(l.get("label", l.get("code", "")))
        if l.get("code") == current:
            items.append(f'<span class="lang on">{label}</span>')
        elif l.get("status") == "live" and l.get("url"):
            items.append(f'<a class="lang" href="{_html.escape(l["url"])}">{label}</a>')
        else:
            items.append(f'<span class="lang soon" title="準備中">{label}'
                         f'<em>準備中</em></span>')
    return '<div class="lang-switch"><span class="globe">🌐</span>' + "".join(items) + "</div>"


def footer_links(config: dict, prefix: str = "") -> str:
    """全ページ共通のフッターリンク。運営者情報は広告を出す以上、どのページからも辿れる必要がある。"""
    items = [
        (f"{prefix}", "トップ"),
        (f"{prefix}terms/", "AI用語集"),
        (f"{prefix}articles/", "読み物"),
        (f"{prefix}archive.html", "バックナンバー"),
    ]
    if config.get("legal", {}).get("enabled"):
        items.append((f"{prefix}about.html", "運営者情報・免責事項"))
    parent = config.get("site", {}).get("parent_site_url", "")
    if parent:
        items.append((parent, config.get("site", {}).get("parent_site_name", "運営元")))
    links = " ／ ".join(f'<a href="{href}">{label}</a>' for href, label in items)
    return f'<div class="footer-links">{links}</div>'


def footer_brand(config: dict) -> str:
    """運営元の通称を、いちばん下に小さく置く。
    見出し・音声の番組名は site.name（世界一わかりやすいAIニュース）を使い、
    こちらは署名としてひっそり出すだけ。持ち主の指示による住み分け。"""
    line = config.get("site", {}).get("brand_line", "").strip()
    if not line:
        return ""
    import html as _h
    return f'<div class="footer-brand">{_h.escape(line)}</div>'


def page_shell(title: str, head_extra: str, body: str, extra_css: str = "") -> str:
    """全ページ共通の HTML 骨格。"""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html.escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{PAGE_CSS}{extra_css}</style>{head_extra}</head>
<body>
{body}
</body>
</html>
"""
