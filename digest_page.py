#!/usr/bin/env python3
"""
日次ダイジェストのページ生成。

旧実装は 2026-04-13 の HTML を読み込んで文字列置換していたため、
構造が固定され、記事が何件あっても同じグリッドに敷き詰められていた。
50件のカードが平列で並び、どこから読めばいいのか分からない状態だった。

作り直した方針:
  - 冒頭に「今日の3行まとめ」を置き、ここだけ読めば済むようにする
  - カテゴリ順ではなく **重要度順** に並べる
  - 重要度3の記事は大きく扱い、視覚的に優先度を示す
  - サイト全体（トップ・読み物）と同じデザインに統一する

social_kit.py が過去号を解析して SNS 投稿文を作るため、
card / card-title-ja / card-source / card-body / dot filled といった
クラス名と出現順は旧実装から変えていない。
"""

import html as _html
import re
from datetime import datetime
from typing import Dict, List, Optional

import glossary
import monetize
import site_theme

CATEGORIES = ["model", "research", "business", "policy", "tools"]
CATEGORIES_JA = {
    "model": "モデル", "research": "研究", "business": "ビジネス",
    "policy": "ポリシー", "tools": "ツール",
}
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

DIGEST_CSS = """
  :root {
    --model:#1d4ed8; --research:#6d28d9; --business:#065f46;
    --policy:#92400e; --tools:#0e7490;
  }
  .lead { max-width:760px; margin:0 auto 2.5rem; padding:1.5rem 1.7rem;
    background:var(--card-bg); border:1px solid var(--border); border-radius:8px; }
  .lead-label { font-size:0.7rem; font-weight:700; letter-spacing:0.14em;
    color:var(--text-muted); margin-bottom:0.9rem; }
  .lead ol { list-style:none; counter-reset:lead; display:flex; flex-direction:column; gap:0.7rem; }
  .lead li { counter-increment:lead; position:relative; padding-left:1.9rem;
    font-size:0.95rem; line-height:1.85; }
  .lead li::before { content:counter(lead); position:absolute; left:0; top:0.3em;
    width:1.25rem; height:1.25rem; border-radius:50%; background:var(--accent); color:#fff;
    font-size:0.68rem; font-weight:700; display:flex; align-items:center; justify-content:center; }
  .digest { max-width:760px; margin:0 auto; display:flex; flex-direction:column; gap:1rem; }
  .card { padding:1.4rem 1.5rem; background:var(--card-bg); border:1px solid var(--border);
    border-left:3px solid var(--text-muted); border-radius:8px; }
  .card.model{border-left-color:var(--model)} .card.research{border-left-color:var(--research)}
  .card.business{border-left-color:var(--business)} .card.policy{border-left-color:var(--policy)}
  .card.tools{border-left-color:var(--tools)}
  .card-top { display:flex; align-items:center; gap:0.6rem; margin-bottom:0.6rem; }
  .card-label { font-size:0.66rem; font-weight:700; letter-spacing:0.06em; padding:2px 7px;
    border-radius:3px; color:#fff; background:var(--text-muted); }
  .card-label.model{background:var(--model)} .card-label.research{background:var(--research)}
  .card-label.business{background:var(--business)} .card-label.policy{background:var(--policy)}
  .card-label.tools{background:var(--tools)}
  .stars { display:flex; gap:3px; }
  .dot { width:6px; height:6px; border-radius:50%; background:var(--border); }
  .dot.filled { background:var(--text-muted); }
  .card-title-ja { font-size:1.08rem; font-weight:700; line-height:1.6; }
  .card-title-en { margin-top:0.25rem; font-size:0.78rem; color:var(--text-muted); line-height:1.5; }
  .card-source { margin-top:0.5rem; font-size:0.72rem; color:var(--text-muted); }
  .card-body { margin-top:0.7rem; font-size:0.9rem; line-height:1.95; }
  .card-link { display:inline-block; margin-top:0.9rem; font-size:0.82rem; font-weight:600;
    color:var(--accent); text-decoration:none; }
  .card-link:hover { text-decoration:underline; }
  .card.top { border-left-width:4px; background:linear-gradient(180deg,rgba(14,116,144,0.04),transparent); }
  .card.top .card-title-ja { font-size:1.25rem; }
  .tier { max-width:760px; margin:2rem auto 0.5rem; font-size:0.7rem; font-weight:700;
    letter-spacing:0.14em; color:var(--text-muted); }
  .tier:first-of-type { margin-top:0; }
  .top-nav { display:flex; flex-wrap:wrap; gap:0.4rem; margin-top:1.3rem; }
  .top-nav a { padding:0.4rem 0.95rem; border:1px solid rgba(255,255,255,0.3); border-radius:999px;
    font-size:0.78rem; font-weight:600; color:#e2e8f0; text-decoration:none; }
  .top-nav a:hover { background:rgba(255,255,255,0.12); }
  .listen { max-width:760px; margin:0 auto 2.5rem; padding:1.2rem 1.4rem;
    background:linear-gradient(135deg,#0f172a,#1e293b); border-radius:10px; color:#e2e8f0; }
  .listen-head { display:flex; align-items:baseline; gap:0.6rem; flex-wrap:wrap; margin-bottom:0.75rem; }
  .listen-head strong { font-size:0.95rem; color:#fff; }
  .listen-head span { font-size:0.76rem; color:#94a3b8; }
  .listen audio { width:100%; height:40px; display:block; }
  .speed-row { display:flex; align-items:center; gap:0.4rem; margin-top:0.7rem; flex-wrap:wrap; }
  .speed-label { font-size:0.7rem; color:#94a3b8; margin-right:0.2rem; }
  .speed-btn { padding:0.3rem 0.75rem; background:rgba(255,255,255,0.1);
    border:1px solid rgba(255,255,255,0.25); border-radius:999px; color:#e2e8f0;
    font-size:0.75rem; font-weight:600; cursor:pointer; }
  .speed-btn.on { background:#22d3ee; border-color:#22d3ee; color:#0f172a; }
  .copy-feed { padding:0.25rem 0.7rem; background:rgba(255,255,255,0.12);
    border:1px solid rgba(255,255,255,0.3); border-radius:6px; color:#e2e8f0;
    font-size:0.72rem; font-weight:600; cursor:pointer; }
  .listen-sub { margin-top:0.8rem; font-size:0.74rem; color:#94a3b8; line-height:1.8; }
  .listen-sub a { color:#7dd3fc; text-decoration:none; }
  .listen-sub a:hover { text-decoration:underline; }
  details.genre { max-width:760px; margin:0 auto 0.75rem; background:var(--card-bg);
    border:1px solid var(--border); border-radius:8px; overflow:hidden; }
  details.genre > summary { list-style:none; cursor:pointer; padding:1rem 1.3rem;
    display:flex; align-items:center; gap:0.7rem; font-weight:700; font-size:0.92rem;
    -webkit-tap-highlight-color:transparent; }
  details.genre > summary::-webkit-details-marker { display:none; }
  details.genre > summary::before { content:"▸"; font-size:0.8rem; color:var(--text-muted);
    transition:transform .15s; }
  details.genre[open] > summary::before { transform:rotate(90deg); }
  details.genre > summary .cnt { margin-left:auto; font-size:0.72rem; font-weight:600;
    color:var(--text-muted); }
  details.genre .genre-dot { width:9px; height:9px; border-radius:50%; background:var(--text-muted); }
  details.genre.model .genre-dot{background:var(--model)} details.genre.research .genre-dot{background:var(--research)}
  details.genre.business .genre-dot{background:var(--business)} details.genre.policy .genre-dot{background:var(--policy)}
  details.genre.tools .genre-dot{background:var(--tools)}
  details.genre .genre-body { padding:0 0.9rem 0.9rem; display:flex; flex-direction:column; gap:0.75rem; }
  details.genre .card { border:none; border-left:3px solid var(--border); background:var(--bg);
    border-radius:6px; }
  .subscribe { max-width:760px; margin:2.5rem auto 0; padding:1rem 1.3rem; text-align:center;
    border:1px dashed var(--border); border-radius:8px; font-size:0.8rem; color:var(--text-muted); }
  .subscribe a { color:var(--accent); font-weight:600; text-decoration:none; }
  @media (max-width:640px){ .card{padding:1.15rem 1.2rem} .card.top .card-title-ja{font-size:1.1rem} }
"""


def _flatten(categorized: Dict[str, List[Dict]]) -> List[Dict]:
    """重要度の高い順に並べ替える。同順位はカテゴリの定義順で安定させる。"""
    items = []
    for category in CATEGORIES:
        for a in categorized.get(category, []):
            items.append({**a, "category": a.get("category", category)})
    items.sort(key=lambda a: (-int(a.get("importance", 2)), CATEGORIES.index(a["category"])))
    return items


def _card(article: Dict, emphasize: bool, ann=None) -> str:
    category = article.get("category", "research")
    importance = max(1, min(3, int(article.get("importance", 2))))
    stars = "".join(
        f'<div class="dot{" filled" if i < importance else ""}"></div>' for i in range(3)
    )
    title_en = article.get("title_en", "")
    title_en_html = (f'      <div class="card-title-en">{_html.escape(title_en)}</div>\n'
                     if title_en else "")
    url = article.get("url", "")
    link_html = (f'      <a class="card-link" href="{_html.escape(url)}" target="_blank" '
                 f'rel="noopener">元記事を読む →</a>\n' if url else "")
    mark = ann if ann is not None else (lambda x: x)
    source = article.get("source", "")
    if isinstance(source, dict):  # RSS 由来の {"name": ...} 形式に耐える
        source = source.get("name", "")
    date = str(article.get("date") or article.get("publishedAt") or "")[:10]
    source_line = " · ".join(str(x) for x in (source, date) if x)

    return (
        f'    <article class="card {category}{" top" if emphasize else ""}">\n'
        '      <div class="card-top">\n'
        f'        <span class="card-label {category}">{CATEGORIES_JA.get(category, category)}</span>\n'
        f'        <div class="stars">{stars}</div>\n'
        '      </div>\n'
        f'      <div class="card-title-ja">{mark(_html.escape(article.get("title_ja", "")))}</div>\n'
        f'{title_en_html}'
        f'      <div class="card-source">{_html.escape(source_line)}</div>\n'
        f'      <div class="card-body">{mark(_html.escape(article.get("summary", "")))}</div>\n'
        f'{link_html}'
        '    </article>\n'
    )


def _lead(overview: List[str], ann=None) -> str:
    if not overview:
        return ""
    mark = ann if ann is not None else (lambda x: x)
    items = "".join(f"      <li>{mark(_html.escape(line))}</li>\n" for line in overview)
    return (
        '  <div class="lead">\n'
        '    <div class="lead-label">今日の3行まとめ</div>\n'
        f'    <ol>\n{items}    </ol>\n'
        "  </div>\n"
    )


def _listen(date: datetime, available: bool) -> str:
    """埋め込み音声プレイヤー。

    再生速度ボタン付き（選んだ速度はブラウザに記憶され、次の日も同じ速度で再生される）。
    src は相対パス — 絶対URLだと未デプロイの環境で鳴らないため。
    購読の案内は「RSS」という言葉を使わず、アプリ名またはコピーボタンで示す。
    """
    if not available:
        return ""
    date_iso = date.strftime("%Y-%m-%d")
    cfg = monetize.load_config()
    pod_cfg = cfg.get("podcast", {})
    base = monetize.podcast_url()

    # 購読の行: Spotify / Apple の番組URLがあればそれを、無ければURLコピーを出す
    spotify = pod_cfg.get("spotify_url", "").strip()
    apple = pod_cfg.get("apple_url", "").strip()
    sub_bits = []
    if spotify:
        sub_bits.append(f'<a href="{spotify}">Spotify で聴く</a>')
    if apple:
        sub_bits.append(f'<a href="{apple}">Apple Podcast で聴く</a>')
    if sub_bits:
        sub_line = "毎朝の配信を購読： " + " ／ ".join(sub_bits)
    else:
        feed = f"{base}/podcast/feed.xml"
        sub_line = (
            "ポッドキャストアプリで毎朝受け取るには "
            f'<button type="button" class="copy-feed" data-copy="{feed}" '
            "onclick=\"navigator.clipboard.writeText(this.dataset.copy)"
            ".then(()=>{this.textContent='✓ コピーしました';"
            "setTimeout(()=>this.textContent='番組アドレスをコピー',2000);});\">"
            "番組アドレスをコピー</button>"
            " して、アプリの「番組を追加」に貼り付けてください"
        )

    return (
        '  <div class="listen" id="listen">\n'
        '    <div class="listen-head">\n'
        "      <strong>🎧 今日の音声版</strong>\n"
        "      <span>対話形式・ながら聴き向け（10〜15分）</span>\n"
        "    </div>\n"
        f'    <audio id="pod-audio" controls preload="none" src="podcast/ai-news-{date_iso}.mp3">\n'
        f'      <a href="podcast/ai-news-{date_iso}.mp3">音声ファイルを開く</a>\n'
        "    </audio>\n"
        '    <div class="speed-row"><span class="speed-label">再生速度</span>\n'
        + "".join(
            f'      <button type="button" class="speed-btn" data-speed="{v}">{label}</button>\n'
            # 単独プレイヤー(podcast/player.html)と選択肢を揃えること
            for v, label in [("0.75", "0.75×"), ("1", "1×"), ("1.25", "1.25×"),
                             ("1.5", "1.5×"), ("2", "2×"), ("2.5", "2.5×")]
        )
        + "    </div>\n"
        f'    <div class="listen-sub">{sub_line}</div>\n'
        "  </div>\n"
        """<script>
(function(){
  var audio = document.getElementById('pod-audio');
  if (!audio) return;
  var btns = document.querySelectorAll('.speed-btn');
  function apply(v){
    audio.playbackRate = parseFloat(v);
    btns.forEach(function(b){ b.classList.toggle('on', b.dataset.speed === v); });
    try { localStorage.setItem('wk-speed', v); } catch(e) {}
  }
  var saved = '1';
  try { saved = localStorage.getItem('wk-speed') || '1'; } catch(e) {}
  apply(saved);
  audio.addEventListener('play', function(){ audio.playbackRate = parseFloat(saved); });
  btns.forEach(function(b){
    b.addEventListener('click', function(){ saved = b.dataset.speed; apply(saved); });
  });
})();
</script>
"""
    )


def _subscribe(config: Dict) -> str:
    return site_theme.subscribe_block(config)


_LEAD_RE = re.compile(r"<ol>(.*?)</ol>", re.DOTALL)


def extract_overview(raw: str) -> List[str]:
    """公開済みページから「今日の3行まとめ」を読み戻す（用語マークは除く）。"""
    i = raw.find("lead-label")
    if i < 0:
        return []
    m = _LEAD_RE.search(raw[i:])
    if not m:
        return []
    return [_html.unescape(re.sub(r"<.*?>", "", li)).strip()
            for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.DOTALL)]


def build_sections(categorized: Dict[str, List[Dict]], date: datetime,
                   overview: Optional[List[str]] = None,
                   podcast_available: bool = False, ann=None) -> Dict[str, str]:
    """ダイジェスト本文の各ブロックを組み立てて返す。

    日次ページとトップページで同じ中身を使うため、描画をここに集約する。
    トップを「最新号への入口」ではなく「最新号そのもの」にするための土台。
    """
    items = _flatten(categorized)

    # 「3行まとめ」は最も読まれる場所なので、用語マークの枠を最優先で確保する
    lead = _lead(overview or [], ann)

    top = [a for a in items if int(a.get("importance", 2)) >= 3]
    rest = [a for a in items if int(a.get("importance", 2)) < 3]
    if not top and rest:
        top, rest = rest[:1], rest[1:]

    top_html = ""
    if top:
        top_html = ('  <div class="tier">注目のニュース</div>\n  <div class="digest">\n'
                    + "".join(_card(a, emphasize=True, ann=ann) for a in top)
                    + "  </div>\n")

    genres_html = ""
    if rest:
        genres_html = '  <div class="tier">ジャンル別のニュース（タップで開く）</div>\n'
        for category in CATEGORIES:
            cat_items = [a for a in rest if a["category"] == category]
            if not cat_items:
                continue
            open_attr = " open" if len(rest) <= 4 else ""
            cards = "".join(_card(a, emphasize=False, ann=ann) for a in cat_items)
            genres_html += (
                f'  <details class="genre {category}"{open_attr}>\n'
                f'    <summary><span class="genre-dot"></span>'
                f'{CATEGORIES_JA.get(category, category)}'
                f'<span class="cnt">{len(cat_items)}件</span></summary>\n'
                f'    <div class="genre-body">\n{cards}    </div>\n'
                "  </details>\n"
            )

    return {
        "lead": lead,
        "listen": _listen(date, podcast_available),
        "top": top_html,
        "genres": genres_html,
        "total": len(items),
    }


def render(categorized: Dict[str, List[Dict]], date: datetime,
           overview: Optional[List[str]] = None,
           podcast_available: bool = False,
           config: Optional[Dict] = None) -> str:
    config = config if config is not None else monetize.load_config()
    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    name = site.get("name", "AI News Digest")

    items = _flatten(categorized)
    total = len(items)
    date_str = f"{date.year}年{date.month}月{date.day}日"
    date_iso = date.strftime("%Y-%m-%d")
    weekday = WEEKDAYS_JA[date.weekday()]

    listen_nav = '<a href="#listen">🎧 音声で聴く</a>' if podcast_available else ""

    # 用語マークは3行まとめ→注目→ジャンル別の順に付く。上限に達したら以降は素通し。
    gcfg = config.get("glossary", {})
    ann = (glossary.Annotator(limit=int(gcfg.get("max_marks_per_page", 26)))
           if gcfg.get("enabled", True) else None)

    head = monetize.build_head_tags(
        config,
        page_url=f"{base}/ai-news-{date_iso}.html" if base else "",
        title=f"AI最新ニュースまとめ {date_str} | {name}",
        description=(overview[0] if overview else
                     f"{date_str}のAI関連ニュース{total}件を日本語で要約してお届けします。"),
        published=f"{date_iso}T06:00:00+09:00",
    )

    sec = build_sections(categorized, date, overview, podcast_available, ann)
    lead_html = sec["lead"]
    body_parts = [sec["top"], sec["genres"]]

    body = f"""<div class="hero">
  <div class="hero-inner">
    <div class="crumbs"><a href="./">{_html.escape(name)}</a></div>
    <h1>{date_str}（{weekday}）のAIニュース</h1>
    <p>厳選 {total} 件。3分で今日のAIがわかります。</p>
    <div class="top-nav">
      <a href="./">トップ</a>
      <a href="articles/">読み物</a>
      <a href="terms/">AI用語集</a>
      <a href="archive.html">バックナンバー</a>{listen_nav}
    </div>
    {site_theme.lang_switch(config)}
  </div>
</div>

<main>
{lead_html}
{_listen(date, podcast_available)}
{"".join(body_parts)}
{_subscribe(config)}
</main>

<footer>
  <strong>{_html.escape(name)}</strong> — {date_str}（{weekday}）／ {total} 件収録<br>
  毎朝6時に自動生成しています。
  {site_theme.footer_links(config)}
  {site_theme.footer_brand(config)}
</footer>
{glossary.assets(ann) if ann else ""}"""

    return site_theme.page_shell(
        f"AI最新ニュースまとめ {date_str} | {name}", head, body,
        extra_css=DIGEST_CSS + (glossary.TOOLTIP_CSS if ann else ""),
    )


if __name__ == "__main__":
    import social_kit
    c = social_kit.load_from_html("2026-07-16")
    html = render(c, datetime(2026, 7, 16),
                  overview=["サンプルの3行まとめです。", "2行目です。", "3行目です。"],
                  podcast_available=True)
    from pathlib import Path
    out = Path(".preview"); out.mkdir(exist_ok=True)
    (out / "digest-sample.html").write_text(html, encoding="utf-8")
    print(f"👀 .preview/digest-sample.html ({len(html):,} bytes)")
