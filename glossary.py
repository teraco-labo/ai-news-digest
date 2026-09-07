#!/usr/bin/env python3
"""
用語辞書 — 記事中の専門用語に説明を付け、辞書ページを生成する。

このサイトの差別化の核。ニュースまとめは他にもあるが、
「AI企業名・ツール名・専門用語が色付きで、触れると説明が出る」ものは少ない。

読者体験:
  PC   … 用語にカーソルを乗せると2文の説明がポップアップ、クリックで解説ページへ
  スマホ… 用語をタップすると画面下からシートが出る（誤タップで遷移しない）
  解説ページの中の用語にもさらに説明が付く（入れ子の学習導線）

副次的な効果:
  用語ページはニュースと違って古びないため、検索流入の資産になる。
  「RAGとは」「Anthropicとは」を調べる読者は、体系的に学びたい層の一歩手前でもある。
"""

import html as _html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO_DIR = Path(__file__).parent
GLOSSARY_FILE = REPO_DIR / "glossary.json"
TERMS_DIR = REPO_DIR / "terms"

DEFAULT_LIMIT = 14  # 1ページに付ける説明の上限（付けすぎると本文が読めなくなる）


def load() -> Dict:
    if not GLOSSARY_FILE.exists():
        return {"terms": []}
    try:
        return json.loads(GLOSSARY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  glossary.json の読み込みに失敗: {e}")
        return {"terms": []}


def save(data: Dict):
    GLOSSARY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def published(data: Optional[Dict] = None) -> List[Dict]:
    data = data if data is not None else load()
    return [t for t in data.get("terms", []) if t.get("status", "draft") == "published"]


# ---------------------------------------------------------------- 本文への注釈

_ASCII_ONLY = re.compile(r"^[A-Za-z0-9 .\-·]+$")


def _surface_forms(term: Dict) -> List[str]:
    return [s for s in [term.get("term", "")] + term.get("aliases", []) if s]


def _build_matcher(terms: List[Dict]) -> Tuple[Optional[re.Pattern], Dict[str, str]]:
    """全用語＋別名から1本の正規表現を作る。

    長い表記を先に並べることで、「大規模言語モデル」を「モデル」より優先させる。
    英字だけの表記は前後の英数字を禁止し、RAPID の中の API のような誤検出を防ぐ。
    """
    lookup: Dict[str, str] = {}
    pieces: List[Tuple[int, str]] = []

    for t in terms:
        for surface in _surface_forms(t):
            key = surface.lower()
            if key in lookup:
                continue
            lookup[key] = t["slug"]
            esc = re.escape(surface)
            if _ASCII_ONLY.match(surface):
                esc = r"(?<![A-Za-z0-9])" + esc + r"(?![A-Za-z0-9])"
            pieces.append((len(surface), esc))

    if not pieces:
        return None, lookup

    pieces.sort(key=lambda x: -x[0])
    pattern = "|".join(p for _, p in pieces)
    return re.compile(pattern, re.IGNORECASE), lookup


def annotate(text: str, matcher: re.Pattern, lookup: Dict[str, str],
             used: Set[str], limit: int = DEFAULT_LIMIT,
             prefix: str = "", skip: Optional[Set[str]] = None) -> str:
    """HTMLエスケープ済みのテキストに用語マークを挿入する。

    used は呼び出し側で共有する集合。同じ用語は1ページに1回だけ付けることで、
    本文が色だらけになるのを防ぐ（used に入っているものは以降スキップされる）。
    """
    if not text or matcher is None:
        return text

    skip = skip or set()
    out: List[str] = []
    pos = 0

    for m in matcher.finditer(text):
        slug = lookup.get(m.group(0).lower())
        if not slug or slug in used or slug in skip or len(used) >= limit:
            continue
        used.add(slug)
        out.append(text[pos:m.start()])
        out.append(
            f'<span class="t" data-t="{slug}" tabindex="0" role="button" '
            f'aria-label="{_html.escape(m.group(0))}の説明を見る">{m.group(0)}</span>'
        )
        pos = m.end()

    out.append(text[pos:])
    return "".join(out)


class Annotator:
    """1ページぶんの注釈をまとめて扱う。"""

    def __init__(self, limit: int = DEFAULT_LIMIT, prefix: str = "",
                 skip: Optional[Set[str]] = None):
        self.data = load()
        self.terms = {t["slug"]: t for t in published(self.data)}
        self.matcher, self.lookup = _build_matcher(list(self.terms.values()))
        self.used: Set[str] = set()
        self.limit = limit
        self.prefix = prefix
        self.skip = skip or set()

    def __call__(self, text: str) -> str:
        return annotate(text, self.matcher, self.lookup, self.used,
                        self.limit, self.prefix, self.skip)

    def payload(self) -> str:
        """ページに埋め込む、使われた用語ぶんだけの説明データ。"""
        if not self.used:
            return ""
        data = {
            slug: {
                "n": self.terms[slug]["term"],
                "r": self.terms[slug].get("reading", ""),
                "s": self.terms[slug]["short"],
                "u": f"{self.prefix}terms/{slug}.html",
            }
            for slug in sorted(self.used) if slug in self.terms
        }
        return ('<script type="application/json" id="glossary-data">'
                + json.dumps(data, ensure_ascii=False) + "</script>\n")


# ---------------------------------------------------------------- UI 部品

TOOLTIP_CSS = """
  .t { color:var(--accent); border-bottom:1px dashed currentColor; cursor:help;
    font-weight:500; }
  .t:hover, .t:focus-visible { background:rgba(14,116,144,0.10); outline:none; border-radius:2px; }
  #tip { position:absolute; z-index:60; max-width:min(22rem,88vw); padding:0.85rem 1rem;
    background:var(--card-bg); border:1px solid var(--border); border-radius:8px;
    box-shadow:0 8px 28px rgba(15,23,42,0.16); font-size:0.84rem; line-height:1.8;
    opacity:0; visibility:hidden; transition:opacity .12s; pointer-events:none; }
  #tip.on { opacity:1; visibility:visible; pointer-events:auto; }
  #tip .tip-n { font-weight:700; display:block; margin-bottom:0.3rem; }
  #tip .tip-m { display:inline-block; margin-top:0.5rem; font-size:0.78rem;
    font-weight:600; color:var(--accent); text-decoration:none; }
  #sheet { position:fixed; left:0; right:0; bottom:0; z-index:70; padding:1.4rem 1.4rem 2rem;
    background:var(--card-bg); border-top:1px solid var(--border);
    border-radius:16px 16px 0 0; box-shadow:0 -8px 32px rgba(15,23,42,0.22);
    transform:translateY(102%); transition:transform .22s ease; }
  #sheet.on { transform:translateY(0); }
  #sheet .sheet-grip { width:36px; height:4px; border-radius:2px; background:var(--border);
    margin:0 auto 1rem; }
  #sheet .tip-n { font-size:1.05rem; font-weight:700; display:block; margin-bottom:0.5rem; }
  #sheet .tip-s { font-size:0.92rem; line-height:1.95; color:var(--text-muted); }
  #sheet .tip-m { display:block; margin-top:1.1rem; padding:0.75rem; text-align:center;
    background:var(--accent); color:#fff; border-radius:8px; font-size:0.88rem;
    font-weight:700; text-decoration:none; }
  #veil { position:fixed; inset:0; z-index:69; background:rgba(15,23,42,0.35);
    opacity:0; visibility:hidden; transition:opacity .22s; }
  #veil.on { opacity:1; visibility:visible; }
  @media (prefers-reduced-motion:reduce){ #sheet,#veil,#tip{transition:none} }
"""

TOOLTIP_JS = """
<script>
(function(){
  var el = document.getElementById('glossary-data');
  if (!el) return;
  var G; try { G = JSON.parse(el.textContent); } catch(e) { return; }

  // 指でも操作する端末ではシート、マウスがある端末ではポップアップにする
  var hoverable = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  var tip = document.createElement('div'); tip.id = 'tip';
  var veil = document.createElement('div'); veil.id = 'veil';
  var sheet = document.createElement('div'); sheet.id = 'sheet';
  sheet.innerHTML = '<div class="sheet-grip"></div><span class="tip-n"></span>'
    + '<div class="tip-s"></div><a class="tip-m" href="#">くわしい解説を読む →</a>';
  document.body.appendChild(tip);
  document.body.appendChild(veil);
  document.body.appendChild(sheet);

  function showTip(node, d){
    tip.innerHTML = '<span class="tip-n"></span><span class="tip-s"></span>'
      + '<a class="tip-m" href="#">くわしい解説 →</a>';
    tip.querySelector('.tip-n').textContent = d.r ? (d.n + '（' + d.r + '）') : d.n;
    tip.querySelector('.tip-s').textContent = d.s;
    tip.querySelector('.tip-m').href = d.u;
    tip.classList.add('on');
    var r = node.getBoundingClientRect();
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(Math.max(8, r.left + r.width/2 - w/2), window.innerWidth - w - 8);
    var top = r.top - h - 10;
    if (top < 8) top = r.bottom + 10;           // 上に入らなければ下に出す
    tip.style.left = (left + window.scrollX) + 'px';
    tip.style.top  = (top + window.scrollY) + 'px';
  }
  function hideTip(){ tip.classList.remove('on'); }

  function openSheet(d){
    sheet.querySelector('.tip-n').textContent = d.r ? (d.n + '（' + d.r + '）') : d.n;
    sheet.querySelector('.tip-s').textContent = d.s;
    sheet.querySelector('.tip-m').href = d.u;
    sheet.classList.add('on'); veil.classList.add('on');
  }
  function closeSheet(){ sheet.classList.remove('on'); veil.classList.remove('on'); }
  veil.addEventListener('click', closeSheet);

  var hideTimer;
  document.addEventListener('mouseover', function(e){
    if (!hoverable) return;
    var n = e.target.closest('.t'); if (!n) return;
    clearTimeout(hideTimer);
    var d = G[n.getAttribute('data-t')]; if (d) showTip(n, d);
  });
  document.addEventListener('mouseout', function(e){
    if (!hoverable) return;
    if (e.target.closest('.t') && !tip.contains(e.relatedTarget)) {
      hideTimer = setTimeout(hideTip, 180);
    }
  });
  tip.addEventListener('mouseenter', function(){ clearTimeout(hideTimer); });
  tip.addEventListener('mouseleave', hideTip);

  document.addEventListener('click', function(e){
    var n = e.target.closest('.t'); if (!n) return;
    var d = G[n.getAttribute('data-t')]; if (!d) return;
    e.preventDefault();
    if (hoverable) { location.href = d.u; } else { openSheet(d); }
  });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape') { hideTip(); closeSheet(); return; }
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var n = document.activeElement; if (!n || !n.classList.contains('t')) return;
    var d = G[n.getAttribute('data-t')]; if (!d) return;
    e.preventDefault();
    hoverable ? (location.href = d.u) : openSheet(d);
  });
})();
</script>
"""


def assets(annotator: "Annotator") -> str:
    """ページ末尾に差し込む、用語データとスクリプト。"""
    payload = annotator.payload()
    return (payload + TOOLTIP_JS) if payload else ""


# ---------------------------------------------------------------- 辞書ページ

GLOSSARY_PAGE_CSS = """
  .term-reading { margin-top:0.5rem; font-size:0.85rem; opacity:0.8; }
  .term-hero-cat { display:inline-block; margin-bottom:0.6rem; padding:3px 10px;
    border-radius:999px; background:rgba(255,255,255,0.14); font-size:0.72rem; font-weight:600; }
  .term-body { max-width:720px; margin:0 auto; }
  .term-easy { padding:1.4rem 1.6rem; background:var(--card-bg); border:1px solid var(--border);
    border-left:3px solid var(--accent); border-radius:8px; }
  .term-easy .lbl, .term-more .lbl { display:block; font-size:0.7rem; font-weight:700;
    letter-spacing:0.12em; color:var(--text-muted); margin-bottom:0.6rem; }
  .term-easy p { font-size:1.02rem; line-height:2.0; }
  .term-more { margin-top:2rem; }
  .term-more p { font-size:0.94rem; line-height:2.0; color:var(--text-muted); }
  .chips { display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:0.9rem; }
  .chips a { padding:0.4rem 0.9rem; background:var(--card-bg); border:1px solid var(--border);
    border-radius:999px; font-size:0.82rem; text-decoration:none; }
  .chips a:hover { border-color:var(--accent); color:var(--accent); }
  .seen { margin-top:0.9rem; display:flex; flex-direction:column; gap:0.4rem; }
  .seen a { font-size:0.85rem; text-decoration:none; color:var(--text-muted); }
  .seen a:hover { color:var(--accent); text-decoration:underline; }
  .term-index-group { max-width:760px; margin:0 auto 2rem; }
  .term-index-group h2 { font-size:0.75rem; font-weight:700; letter-spacing:0.12em;
    color:var(--text-muted); margin-bottom:0.8rem; }
  .term-list { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:0.7rem; }
  .term-list a { display:block; padding:0.85rem 1rem; background:var(--card-bg);
    border:1px solid var(--border); border-radius:8px; text-decoration:none; }
  .term-list a:hover { border-color:var(--accent); }
  .term-list .n { font-weight:700; font-size:0.92rem; }
  .term-list .s { margin-top:0.25rem; font-size:0.76rem; color:var(--text-muted);
    display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }

  .term-toolbar { max-width:760px; margin:0 auto 0.6rem; display:flex; gap:0.6rem;
    flex-wrap:wrap; align-items:center; }
  .term-search { flex:1 1 220px; min-width:0; padding:0.6rem 0.9rem; font-size:0.9rem;
    font-family:inherit; color:var(--text); background:var(--card-bg); border:1px solid var(--border);
    border-radius:8px; }
  .term-search:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  .term-sort { display:flex; gap:0.4rem; flex-wrap:wrap; }
  .term-sort button { font:inherit; font-size:0.8rem; padding:0.5rem 0.9rem; border-radius:999px;
    border:1px solid var(--border); background:var(--card-bg); color:var(--text); cursor:pointer; }
  .term-sort button[aria-pressed="true"] { background:var(--accent); border-color:var(--accent); color:#fff; }
  .term-sort button:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  .term-count { max-width:760px; margin:0 auto 1.6rem; font-size:0.78rem; color:var(--text-muted); }
  .term-empty { max-width:760px; margin:2rem auto; font-size:0.9rem; color:var(--text-muted); }
"""


def _digests_mentioning(slug: str, limit: int = 5) -> List[Dict]:
    """その用語が登場した過去のダイジェストを新しい順に返す。"""
    found = []
    marker = f'data-t="{slug}"'
    for path in sorted(REPO_DIR.glob("ai-news-*.html"), reverse=True):
        m = re.match(r"ai-news-(\d{4}-\d{2}-\d{2})\.html$", path.name)
        if not m:
            continue
        try:
            if marker in path.read_text(encoding="utf-8", errors="ignore"):
                d = m.group(1)
                found.append({"file": path.name, "date": d,
                              "label": f"{d[:4]}年{int(d[5:7])}月{int(d[8:10])}日"})
        except Exception:
            continue
        if len(found) >= limit:
            break
    return found


def build_term_page(term: Dict, all_terms: Dict[str, Dict], config: Dict) -> str:
    import monetize
    import site_theme

    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    name = site.get("name", "")
    slug = term["slug"]

    # 解説文の中の用語にもさらに説明を付ける（入れ子の学習導線）。自分自身は除く。
    ann = Annotator(limit=10, prefix="../", skip={slug})
    easy = ann(_html.escape(term["short"]))
    detail = ann(_html.escape(term.get("detail", "")))

    head = monetize.build_head_tags(
        config,
        page_url=f"{base}/terms/{slug}.html" if base else "",
        title=f"{term['term']}とは？ わかりやすく解説 | {name}",
        description=term["short"][:120],
    )
    head += ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "DefinedTerm",
        "name": term["term"], "description": term["short"],
        "inDefinedTermSet": f"{base}/terms/" if base else "",
    }, ensure_ascii=False) + "</script>\n")

    reading = term.get("reading", "")
    reading_html = (f'<p class="term-reading">読み方：{_html.escape(reading)}</p>'
                    if reading else "")

    related = "".join(
        f'    <a href="{r}.html">{_html.escape(all_terms[r]["term"])}</a>\n'
        for r in term.get("related", []) if r in all_terms
    )
    related_html = (f'  <div class="lbl" style="margin-top:2rem">関連する用語</div>\n'
                    f'  <div class="chips">\n{related}  </div>\n') if related else ""

    seen = _digests_mentioning(slug)
    seen_html = ""
    if seen:
        links = "".join(
            f'    <a href="../{s["file"]}">{s["label"]}のダイジェスト →</a>\n' for s in seen
        )
        seen_html = (f'  <div class="lbl" style="margin-top:2rem">この用語が出てきたニュース</div>\n'
                     f'  <div class="seen">\n{links}  </div>\n')

    offers = monetize.render_offer_block(
        monetize.select_offers(config, None, __import__("datetime").datetime.now(),
                               int(config.get("slots", {}).get("footer_offers", 0))),
        heading="この分野をちゃんと学びたい方へ",
    )

    body = f"""<div class="hero">
  <div class="hero-inner">
    <div class="crumbs"><a href="../">{_html.escape(name)}</a> ／ <a href="./">用語集</a></div>
    <span class="term-hero-cat">{_html.escape(term.get("category", ""))}</span>
    <h1>{_html.escape(term["term"])}とは？</h1>
    {reading_html}
  </div>
</div>

<main>
  <div class="term-body">
    <div class="term-easy">
      <span class="lbl">かんたんに言うと</span>
      <p>{easy}</p>
    </div>
    <div class="term-more">
      <span class="lbl">もう一歩くわしく</span>
      <p>{detail}</p>
    </div>
{related_html}{seen_html}  </div>
{offers}{monetize.render_cta(config)}
  <p style="max-width:720px;margin:2.5rem auto 0;font-size:0.85rem;">
    <a href="./" style="color:var(--accent);font-weight:600;">← 用語集の一覧にもどる</a>
  </p>
</main>

<footer>
  <strong>{_html.escape(name)}</strong> — {_html.escape(site.get("author", ""))}
  {site_theme.footer_links(config, prefix="../")}
</footer>
{assets(ann)}"""

    return site_theme.page_shell(
        f"{term['term']}とは？ わかりやすく解説 | {name}", head, body,
        extra_css=GLOSSARY_PAGE_CSS + TOOLTIP_CSS,
    )


TERM_SEARCH_JS = r"""
(function () {
  var DATA = JSON.parse(document.getElementById("termData").textContent);
  var main = document.getElementById("termMain");
  var search = document.getElementById("termSearch");
  var count = document.getElementById("termCount");
  var buttons = Array.prototype.slice.call(document.querySelectorAll(".term-sort button"));

  // 五十音の行（濁音・半濁音は清音の行にまとめる）。「五十音順」の並び替えで見出しに使う
  var GYOU = {};
  [["あいうえお","あ"],["かきくけこがぎぐげご","か"],["さしすせそざじずぜぞ","さ"],
   ["たちつてとだぢづでど","た"],["なにぬねの","な"],
   ["はひふへほばびぶべぼぱぴぷぺぽ","は"],["まみむめも","ま"],
   ["やゆよ","や"],["らりるれろ","ら"],["わをん","わ"]].forEach(function (pair) {
    for (var i = 0; i < pair[0].length; i++) GYOU[pair[0][i]] = pair[1];
  });
  function toHiragana(ch) {
    var c = (ch || "").charCodeAt(0);
    return c >= 0x30A1 && c <= 0x30F6 ? String.fromCharCode(c - 0x60) : ch;
  }
  function gyouOf(reading) {
    var ch = toHiragana((reading || "").charAt(0));
    return GYOU[ch] || "他";
  }

  var collatorJa = window.Intl ? new Intl.Collator("ja") : null;
  var collatorEn = window.Intl ? new Intl.Collator("en", { sensitivity: "base" }) : null;
  function cmpJa(a, b) { return collatorJa ? collatorJa.compare(a, b) : (a < b ? -1 : a > b ? 1 : 0); }
  function cmpEn(a, b) { return collatorEn ? collatorEn.compare(a, b) : (a < b ? -1 : a > b ? 1 : 0); }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function matches(t, q) {
    if (!q) return true;
    q = q.toLowerCase();
    if ((t.term || "").toLowerCase().indexOf(q) !== -1) return true;
    if ((t.short || "").toLowerCase().indexOf(q) !== -1) return true;
    if ((t.reading || "").toLowerCase().indexOf(q) !== -1) return true;
    return (t.aliases || []).some(function (a) { return a.toLowerCase().indexOf(q) !== -1; });
  }

  function groupsFor(mode, items) {
    var groups = [];
    if (mode === "category") {
      var order = [], byCat = {};
      items.forEach(function (t) {
        var cat = t.category || "その他";
        if (!byCat[cat]) { byCat[cat] = []; order.push(cat); }
        byCat[cat].push(t);
      });
      order.forEach(function (cat) {
        groups.push({ label: cat, items: byCat[cat].slice().sort(function (a, b) { return cmpJa(a.term, b.term); }) });
      });
    } else if (mode === "kana") {
      var ROWS = ["あ", "か", "さ", "た", "な", "は", "ま", "や", "ら", "わ", "他"];
      var byRow = {};
      items.slice().sort(function (a, b) { return cmpJa(a.reading || a.term, b.reading || b.term); })
        .forEach(function (t) {
          var row = gyouOf(t.reading || t.term);
          (byRow[row] = byRow[row] || []).push(t);
        });
      ROWS.forEach(function (row) { if (byRow[row]) groups.push({ label: row + "行", items: byRow[row] }); });
    } else {
      var byLetter = {}, order2 = [];
      items.slice().sort(function (a, b) { return cmpEn(a.term, b.term); })
        .forEach(function (t) {
          var ch = (t.term || "").charAt(0).toUpperCase();
          var key = /[A-Z]/.test(ch) ? ch : "その他";
          if (!byLetter[key]) { byLetter[key] = []; order2.push(key); }
          byLetter[key].push(t);
        });
      order2.sort(function (a, b) { return a === "その他" ? 1 : b === "その他" ? -1 : (a < b ? -1 : 1); });
      order2.forEach(function (key) { groups.push({ label: key, items: byLetter[key] }); });
    }
    return groups;
  }

  function render() {
    var q = search.value.trim();
    var mode = document.querySelector('.term-sort button[aria-pressed="true"]').getAttribute("data-sort");
    var filtered = DATA.filter(function (t) { return matches(t, q); });
    var groups = groupsFor(mode, filtered);
    if (!groups.length) {
      main.innerHTML = '<p class="term-empty">「' + esc(q) + '」に一致する用語が見つかりませんでした。</p>';
    } else {
      main.innerHTML = groups.map(function (g) {
        var cards = g.items.map(function (t) {
          return '<a href="' + t.slug + '.html"><div class="n">' + esc(t.term) +
                 '</div><div class="s">' + esc(t.short) + "</div></a>";
        }).join("");
        return '<div class="term-index-group"><h2>' + esc(g.label) +
               '</h2><div class="term-list">' + cards + "</div></div>";
      }).join("");
    }
    count.textContent = q ? filtered.length + " / " + DATA.length + " 語を表示" : DATA.length + " 語";
  }

  search.addEventListener("input", render);
  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      buttons.forEach(function (x) { x.setAttribute("aria-pressed", "false"); });
      b.setAttribute("aria-pressed", "true");
      render();
    });
  });
})();
"""


def build_index_page(terms: List[Dict], config: Dict) -> str:
    import monetize
    import site_theme

    site = config.get("site", {})
    base = site.get("base_url", "").rstrip("/")
    name = site.get("name", "")

    head = monetize.build_head_tags(
        config,
        page_url=f"{base}/terms/" if base else "",
        title=f"AI用語集 — {len(terms)}語をわかりやすく | {name}",
        description=("AIのニュースによく出てくる企業名・ツール名・専門用語を、"
                     "初心者にも中級者にもわかる言葉で解説した用語集です。"),
    ).replace('<meta property="og:type" content="article">',
              '<meta property="og:type" content="website">')

    groups: Dict[str, List[Dict]] = {}
    for t in terms:
        groups.setdefault(t.get("category", "その他"), []).append(t)

    sections = ""
    for cat, items in groups.items():
        cards = "".join(
            f'    <a href="{t["slug"]}.html">\n'
            f'      <div class="n">{_html.escape(t["term"])}</div>\n'
            f'      <div class="s">{_html.escape(t["short"])}</div>\n'
            "    </a>\n"
            for t in sorted(items, key=lambda x: x["term"].lower())
        )
        sections += (f'  <div class="term-index-group">\n    <h2>{_html.escape(cat)}</h2>\n'
                     f'    <div class="term-list">\n{cards}    </div>\n  </div>\n')

    term_payload = json.dumps(
        [{"slug": t["slug"], "term": t["term"], "short": t["short"],
          "category": t.get("category", "その他"), "reading": t.get("reading", ""),
          "aliases": t.get("aliases", [])} for t in terms],
        ensure_ascii=False)

    body = f"""<div class="hero">
  <div class="hero-inner">
    <div class="crumbs"><a href="../">{_html.escape(name)}</a></div>
    <h1>AI用語集</h1>
    <p>ニュースに出てくる企業名・ツール名・専門用語を {len(terms)} 語、やさしく解説しています。</p>
    <div class="top-nav">
      <a href="../">トップ</a>
      <a href="../archive.html">バックナンバー</a>
    </div>
    {site_theme.lang_switch(config)}
  </div>
</div>

<main>
  <div class="term-toolbar">
    <input type="search" id="termSearch" class="term-search"
           placeholder="用語を検索（例: LLM、GPU、著作権）" aria-label="用語を検索">
    <div class="term-sort" role="group" aria-label="並び替え">
      <button type="button" data-sort="category" aria-pressed="true">ジャンル別</button>
      <button type="button" data-sort="kana">五十音順</button>
      <button type="button" data-sort="alpha">アルファベット順</button>
    </div>
  </div>
  <p class="term-count" id="termCount" aria-live="polite">{len(terms)} 語</p>
  <div id="termMain">
{sections}  </div>
</main>

<footer>
  <strong>{_html.escape(name)}</strong> — {_html.escape(site.get("author", ""))}
  {site_theme.footer_links(config, prefix="../")}
</footer>
<script type="application/json" id="termData">{term_payload}</script>
<script>{TERM_SEARCH_JS}</script>"""

    return site_theme.page_shell(f"AI用語集 | {name}", head, body,
                                 extra_css=GLOSSARY_PAGE_CSS)


def build_all(config: Optional[Dict] = None, verbose: bool = True) -> List[Dict]:
    import monetize
    config = config if config is not None else monetize.load_config()

    terms = published()
    if not terms:
        return []

    TERMS_DIR.mkdir(exist_ok=True)
    index = {t["slug"]: t for t in terms}
    for t in terms:
        (TERMS_DIR / f"{t['slug']}.html").write_text(
            build_term_page(t, index, config), encoding="utf-8")
    (TERMS_DIR / "index.html").write_text(build_index_page(terms, config), encoding="utf-8")

    drafts = [t for t in load().get("terms", []) if t.get("status") != "published"]
    if verbose:
        print(f"✓ terms/ に用語ページ {len(terms)} 件"
              + (f"（下書き {len(drafts)} 件は未公開）" if drafts else ""))
    return terms


if __name__ == "__main__":
    build_all()
