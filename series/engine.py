#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「世界一わかりやすい」シリーズ共用のページエンジン。

AIニュースとスマホニュースを1つの仕組みで作り、見た目と言葉は番組ごとの設定（series/shows/*.json）で分ける。
2026-10-05 藤崎さん「両方の機能を消さずにいいとこ取りで全部盛り込み、デザインはそれぞれに振り分ける。
聴くページと読むページも1枚に」。足し算で全部入れて、引き算は後から（同日）。

1回につき1枚のページ（聴く・読むを統合）:
  - 上：再生（大きな再生ボタン／10秒・30秒の早送りと戻し／再生バー／速さボタン／キーボード操作）
        と「文字で読む」ボタン。プレイヤーが画面の外に出たら、下に小さな再生バー
  - 本文：言葉に触れると説明（AIニュースの glossary.py の部品）。文を押すとそこから再生、
        再生中は今の文に色がついて、画面がついていく（自分でスクロールした直後は追いかけない）
  - 下：おさらい・情報のもと・「この番組を毎回聴く」（番組ごとの行き先）・バックナンバー・用語集
ほかに：バックナンバー、用語集（検索・並び替えつき）と言葉ごとの解説ページ、サイトの地図（sitemap）、robots、
古いURL（player.html・yomu.html）からの自動の移動ページ。

使い方は番組側のスクリプトから:
  from series import engine as E
  show = E.load_show("sumaho-news")
  E.write_episode(show, repo_dir, ep) / E.write_archive(...) / E.write_glossary(...) / E.write_sitemap(...)
"""
import html
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR.parent))
import glossary as G   # noqa: E402  AIニュースの用語の部品（線引き・浮かぶ説明・用語集の検索）

WEEK = "月火水木金土日"
esc = html.escape


def load_show(name: str) -> dict:
    return json.loads((ENGINE_DIR / "shows" / f"{name}.json").read_text(encoding="utf-8"))


def date_ja(d: str) -> str:
    y, m, dd = map(int, d.split("-"))
    return f"{m}月{dd}日（{WEEK[_date(y, m, dd).weekday()]}）"


# ─── 用語 ─────────────────────────────────────────────────
def load_terms(glossary_file: Path) -> dict:
    d = json.loads(Path(glossary_file).read_text(encoding="utf-8"))
    return {t["slug"]: t for t in d["terms"] if t.get("status", "published") == "published"}


class Annotator:
    """1ページぶんの注釈。AIニュースの annotate（各語1ページ1回）をそのまま使い、辞書だけ番組ごとに差し替える。"""

    def __init__(self, terms: dict, prefix: str, limit: int = 60):
        self.terms, self.prefix, self.limit = terms, prefix, limit
        self.matcher, self.lookup = G._build_matcher(list(terms.values()))
        self.used = set()

    def __call__(self, text: str) -> str:
        return G.annotate(esc(text), self.matcher, self.lookup, self.used, self.limit)

    def assets(self) -> str:
        if not self.used:
            return ""
        data = {s: {"n": self.terms[s]["term"], "r": self.terms[s].get("reading", ""),
                    "s": self.terms[s]["short"], "u": f"{self.prefix}terms/{s}.html"}
                for s in sorted(self.used)}
        return ('<script type="application/json" id="glossary-data">'
                + json.dumps(data, ensure_ascii=False) + "</script>\n" + G.TOOLTIP_JS)


# ─── 見た目 ───────────────────────────────────────────────
def _tokens(d: dict) -> str:
    return "".join(f"--{k.replace('_', '-')}:{v};" for k, v in d.items())


def theme_css(show: dict) -> str:
    th = show["theme"]
    return f"""
  :root {{ {_tokens(th['light'])} --card-bg:var(--card); --border:var(--line); --text:var(--ink); --text-muted:var(--ink2); }}
  @media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ {_tokens(th['dark'])} color-scheme:dark; }} }}
  :root[data-theme="dark"] {{ {_tokens(th['dark'])} color-scheme:dark; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ background:var(--bg); color:var(--ink); font-family:{th['font_family']}; font-size:{th['base_size']};
         line-height:1.85; -webkit-text-size-adjust:100%; }}
  a {{ color:var(--heading); }}
  header.top {{ background:var(--head); color:var(--head-ink); padding:20px 16px 18px; text-align:center; }}
  header.top a {{ color:var(--head-ink); text-decoration:none; }}
  header.top .sub {{ font-size:.8em; opacity:.85; }}
  header.top .name {{ font-size:1.3em; font-weight:700; line-height:1.3; }}
  header.top .when {{ margin-top:6px; font-size:.85em; }}
  main {{ max-width:680px; margin:0 auto; padding:18px 16px 110px; }}
  h1 {{ font-size:1.32em; line-height:1.45; text-wrap:balance; }}
  h2 {{ margin:32px 0 8px; font-size:1.16em; color:var(--heading); border-left:6px solid var(--mark); padding-left:10px; text-wrap:balance; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:16px; margin-top:16px; }}
  .lbl {{ display:inline-block; font-size:.72em; font-weight:700; color:#fff; background:var(--head); border-radius:6px; padding:0 8px; margin-top:6px; }}
  .card ul {{ padding-left:1.2em; }}
  .soft {{ background:var(--soft); border-radius:18px; padding:18px 16px; margin-top:30px; }}
  .soft h2 {{ margin:0 0 6px; border:0; padding:0; color:var(--ink); }}
  .soft ol {{ padding-left:1.4em; font-size:1.05em; font-weight:700; }}
  .soft .hw {{ margin-top:10px; font-size:.9em; }}
  .src {{ margin-top:26px; font-size:.8em; color:var(--ink2); }}
  .src ul {{ padding-left:1.2em; }}
  .links {{ margin-top:22px; font-size:.85em; display:flex; flex-wrap:wrap; gap:8px 18px; }}
  footer.foot {{ margin-top:28px; text-align:center; font-size:.85em; color:var(--ink2); }}
  footer.foot a {{ font-weight:700; }}
  .t {{ font-weight:700; }}
  #tip {{ font-size:{th['tip_size']} !important; line-height:1.8 !important; }}
  #sheet .tip-n {{ font-size:1.1em !important; }}
  #sheet .tip-s {{ font-size:.95em !important; color:var(--ink) !important; }}
  #sheet .tip-m {{ font-size:.95em !important; padding:14px !important; background:var(--head) !important; }}
  :focus-visible {{ outline:3px solid var(--mark); outline-offset:2px; }}
  @media (prefers-reduced-motion:reduce) {{ * {{ transition:none !important; scroll-behavior:auto !important; }} }}
"""


PLAYER_CSS = """
  .player { background:var(--card); border:2px solid var(--line); border-radius:20px; padding:16px; margin-top:16px; }
  .p-head { display:flex; gap:12px; align-items:center; }
  .p-head img { width:64px; height:64px; border-radius:12px; flex:none; }
  .p-head .ttl { font-weight:700; line-height:1.45; }
  .bigplay { display:flex; align-items:center; justify-content:center; gap:12px; width:100%; margin-top:14px; padding:16px;
             border:none; border-radius:16px; background:var(--btn); color:var(--btn-ink); font-size:1.2em; font-weight:700;
             font-family:inherit; cursor:pointer; }
  .bigplay svg { width:28px; height:28px; }
  .readbtn { display:flex; align-items:center; justify-content:center; gap:10px; width:100%; margin-top:10px; padding:13px;
             border:3px solid var(--head); border-radius:16px; background:var(--card); color:var(--heading); font-size:1.1em;
             font-weight:700; text-decoration:none; }
  .readbtn svg { width:24px; height:24px; }
  .progress { position:relative; height:12px; background:var(--line); border-radius:6px; margin-top:16px; cursor:pointer; touch-action:none; }
  .progress .fill { position:absolute; left:0; top:0; bottom:0; width:0; background:var(--btn); border-radius:6px; }
  .time-row { display:flex; justify-content:space-between; font-size:.78em; color:var(--ink2); margin-top:4px; font-variant-numeric:tabular-nums; }
  .skips { display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:8px; }
  .skips button { border:2px solid var(--line); background:var(--card); color:var(--ink); border-radius:12px; padding:6px 0;
                  font-family:inherit; cursor:pointer; line-height:1.3; }
  .skips button b { display:block; font-size:.9em; }
  .skips button small { display:block; font-size:.68em; color:var(--ink2); font-weight:700; }
  .speed { margin-top:12px; }
  .speed-k { display:flex; justify-content:space-between; font-size:.7em; color:var(--ink2); padding:0 2px; }
  .speed-row { display:flex; gap:6px; margin-top:2px; }
  .speed-row button { flex:1; border:2px solid var(--line); background:var(--card); color:var(--ink); border-radius:10px;
                      padding:8px 0; font-size:.85em; font-weight:700; font-family:inherit; cursor:pointer; }
  .speed-row button.on { background:var(--head); border-color:var(--head); color:#fff; }
  .kbd { margin-top:10px; font-size:.7em; color:var(--ink2); display:none; }
  @media (hover:hover) and (pointer:fine) { .kbd { display:block; } }
  .mini { position:fixed; left:0; right:0; bottom:0; z-index:50; background:var(--card); border-top:1px solid var(--line);
          box-shadow:0 -6px 20px rgba(0,0,0,.12); padding:10px 14px calc(10px + env(safe-area-inset-bottom, 0px));
          display:flex; gap:10px; align-items:center; transform:translateY(110%); transition:transform .2s; }
  .mini.show { transform:translateY(0); }
  .mini button { flex:none; border:none; border-radius:12px; font-family:inherit; font-weight:700; cursor:pointer; }
  .mini .m-play { width:52px; height:44px; background:var(--btn); color:var(--btn-ink); }
  .mini .m-play svg { width:24px; height:24px; }
  .mini .m-back { padding:0 10px; height:44px; background:var(--bg); color:var(--ink); font-size:.75em; border:1px solid var(--line); }
  .mini .m-bar { flex:1; height:8px; background:var(--line); border-radius:4px; overflow:hidden; }
  .mini .m-fill { height:100%; width:0; background:var(--btn); }
  .mini .m-time { flex:none; font-size:.72em; color:var(--ink2); font-variant-numeric:tabular-nums; }
  .read-h { scroll-margin-top:16px; }
  .read-hint { font-size:.82em; color:var(--ink2); background:var(--card); border:1px solid var(--line); border-radius:12px; padding:10px 14px; margin-top:8px; }
  .ln { border-radius:12px; padding:6px 10px; margin:6px -10px; cursor:pointer; transition:background .2s; }
  .ln.now { background:var(--now); }
  .ln .who { display:block; font-size:.68em; font-weight:700; color:var(--ink2); }
  .ln.partner { background:color-mix(in srgb, var(--soft) 55%, transparent); }
  .ln.partner.now { background:var(--now); }
  .follow { display:flex; align-items:center; justify-content:center; gap:10px; width:100%; margin-top:28px; padding:16px;
            border:none; border-radius:16px; background:var(--head); color:#fff; font-size:1.1em; font-weight:700;
            font-family:inherit; cursor:pointer; }
  .follow svg { width:24px; height:24px; }
  .follow.follow-top { margin-top:10px; padding:12px; font-size:1em; background:var(--card); color:var(--heading); border:2px dashed var(--head); }
  #fveil { position:fixed; inset:0; z-index:80; background:rgba(0,0,0,.4); display:none; }
  #fsheet { position:fixed; left:0; right:0; bottom:0; z-index:81; max-width:680px; margin:0 auto; background:var(--card);
            color:var(--ink); border-radius:18px 18px 0 0; padding:22px 18px calc(26px + env(safe-area-inset-bottom, 0px));
            box-shadow:0 -8px 30px rgba(0,0,0,.25); display:none; max-height:88vh; overflow:auto; }
  #fveil.on, #fsheet.on { display:block; }
  #fsheet h3 { font-size:1.15em; }
  #fsheet .way { margin-top:14px; padding:14px; border:1px solid var(--line); border-radius:14px; }
  #fsheet .way b { display:block; }
  #fsheet .way p { font-size:.9em; color:var(--ink2); margin-top:4px; line-height:1.7; }
  #fsheet .go { display:block; margin-top:10px; padding:13px; border-radius:12px; text-align:center; font-weight:700;
                text-decoration:none; color:#fff; background:var(--btn); }
  #fsheet .go.spotify { background:#1DB954; }
  #fsheet .small { margin-top:14px; font-size:.85em; color:var(--ink2); text-align:center; }
  #fsheet .small a { color:var(--ink2); }
  #fsheet .close { display:block; width:100%; margin-top:14px; padding:12px; border:1px solid var(--line); border-radius:12px;
                   background:transparent; color:var(--ink); font-size:.95em; font-family:inherit; cursor:pointer; }
"""

TERMS_CSS = """
  .easy { margin-top:18px; padding:16px; background:var(--card); border:1px solid var(--line); border-left:6px solid var(--mark); border-radius:12px; }
  .klbl { display:block; font-size:.74em; font-weight:700; color:var(--ink2); letter-spacing:.06em; }
  .detail { margin-top:22px; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; }
  .chips a { padding:6px 14px; background:var(--card); border:1px solid var(--line); border-radius:999px; color:var(--ink); text-decoration:none; font-size:.9em; }
  .seen { margin-top:8px; display:flex; flex-direction:column; gap:6px; }
  .term-toolbar { display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }
  .term-search { flex:1 1 220px; min-width:0; padding:12px 14px; font-size:1em; font-family:inherit; color:var(--ink);
                 background:var(--card); border:2px solid var(--line); border-radius:12px; }
  .term-sort { display:flex; gap:6px; flex-wrap:wrap; }
  .term-sort button { font:inherit; font-size:.8em; padding:8px 14px; border-radius:999px; border:2px solid var(--line);
                      background:var(--card); color:var(--ink); cursor:pointer; }
  .term-sort button[aria-pressed="true"] { background:var(--head); border-color:var(--head); color:#fff; }
  .term-count { margin-top:10px; font-size:.78em; color:var(--ink2); }
  .term-index-group { margin-top:22px; }
  .term-index-group h2 { margin-top:0; }
  .term-list { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:10px; margin-top:8px; }
  .term-list a { display:block; padding:12px 14px; background:var(--card); border:1px solid var(--line); border-radius:12px; text-decoration:none; color:var(--ink); }
  .term-list .n { font-weight:700; }
  .term-list .s { font-size:.8em; color:var(--ink2); line-height:1.6; }
  .term-empty { margin-top:20px; color:var(--ink2); }
  .arch a { display:block; padding:14px 16px; background:var(--card); border:1px solid var(--line); border-radius:14px; margin-top:10px;
            text-decoration:none; color:var(--ink); }
  .arch .d { font-size:.8em; color:var(--ink2); }
  .arch .ti { font-weight:700; line-height:1.5; }
"""

SVG_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
SVG_PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>'
SVG_READ = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M4 5h16v2H4zm0 4h16v2H4zm0 4h10v2H4zm0 4h16v2H4z"/></svg>'
SVG_HEART = ('<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3'
             'c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>')


# ─── ページの枠 ───────────────────────────────────────────
def head_tags(show: dict, *, url: str, title: str, desc: str, published: str = "", kind: str = "article") -> str:
    base = show["base_url"].rstrip("/")
    ld = {"@context": "https://schema.org", "@type": "PodcastEpisode" if kind == "episode" else "WebPage",
          "name": title, "description": desc, "url": url, "inLanguage": "ja",
          "author": {"@type": "Person", "name": show.get("by", "")},
          "partOfSeries": {"@type": "PodcastSeries", "name": show["name"], "url": base + "/"}}
    if published:
        ld["datePublished"] = published
    return (f'<meta name="description" content="{esc(desc)}">\n'
            f'<link rel="canonical" href="{esc(url)}">\n'
            f'<meta property="og:type" content="{"article" if kind == "episode" else "website"}">\n'
            f'<meta property="og:title" content="{esc(title)}">\n'
            f'<meta property="og:description" content="{esc(desc)}">\n'
            f'<meta property="og:url" content="{esc(url)}">\n'
            f'<meta property="og:site_name" content="{esc(show["name"])}">\n'
            f'<meta property="og:image" content="{esc(base)}/{show["cover"]}">\n'
            '<meta name="twitter:card" content="summary">\n'
            f'<link rel="alternate" type="application/rss+xml" title="{esc(show["name"])}" href="{esc(base)}/{show["podcast_feed"]}">\n'
            f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>\n')


def shell(show: dict, *, title: str, head: str, body: str, prefix: str, extra_css: str = "", tail: str = "") -> str:
    th = show["theme"]
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{esc(title)}</title>
{head}<link rel="icon" href="{prefix}{show['cover']}">
<link href="{th['font_url']}" rel="stylesheet">
<style>{G.TOOLTIP_CSS}{theme_css(show)}{extra_css}</style>
</head>
<body>
{body}
{tail}</body>
</html>
"""


def top_header(show: dict, prefix: str, when: str) -> str:
    lines = "<br>".join(esc(x) for x in show.get("name_lines", [show["name"]]))
    return (f'<header class="top"><a href="{prefix}"><div class="sub">{esc(show.get("brand_sub", ""))}</div>'
            f'<div class="name">{lines}</div></a><div class="when">{esc(when)}</div></header>')


def footer(show: dict) -> str:
    c = show.get("contact")
    if not c:
        return ""
    return f'<footer class="foot">{esc(c["text"])}<br><a href="{esc(c["url"])}">{esc(c["link"])}</a></footer>'


def follow_html(show: dict) -> str:
    f = show.get("follow")
    if not f:
        return ""
    ways = "".join(
        f'<div class="way"><b>{esc(o["label"])}</b><p>{esc(o.get("text", ""))}</p>'
        f'<a class="go {esc(o["kind"])}" href="{esc(o["url"])}">{esc(o["label"])}</a></div>' for o in f.get("options", []))
    sm = f.get("small")
    small = (f'<p class="small">{esc(sm["text"])} <a href="{esc(sm["url"])}">{esc(sm["link"])}</a></p>' if sm else "")
    return f"""
  <button class="follow" type="button">{SVG_HEART}<span>{esc(f['button'])}</span></button>
  <div id="fveil"></div>
  <div id="fsheet" role="dialog" aria-modal="true" aria-labelledby="fsheet-h">
    <h3 id="fsheet-h">{esc(f['title'])}</h3>{ways}{small}
    <button class="close" id="fclose" type="button">閉じる</button>
  </div>"""


# ─── プレイヤー ───────────────────────────────────────────
def player_html(show: dict, *, audio: str, title: str, cover: str, read_target: str = "#yomu", sub: str = "") -> str:
    p = show["player"]
    skips = p.get("skips", [10, 30])
    skip_btns = "".join(f'<button type="button" data-skip="{-s}"><b>{s}秒</b><small>もどる</small></button>' for s in sorted(skips, reverse=True)) + \
        "".join(f'<button type="button" data-skip="{s}"><b>{s}秒</b><small>すすむ</small></button>' for s in sorted(skips))
    speeds = "".join(f'<button type="button" data-r="{v}">{esc(lbl)}</button>' for v, lbl in p["speeds"])
    kbd = '<p class="kbd">キーボード：スペースで再生／停止、← → で10秒、J / L で30秒</p>' if p.get("keyboard") else ""
    return f"""
  <div class="player" id="player">
    <div class="p-head"><img src="{esc(cover)}" alt="" width="64" height="64"><div class="ttl">{esc(show['name'])}<br><small style="font-weight:500;color:var(--ink2)">{esc(sub)}</small></div></div>
    <button class="bigplay" id="play" type="button">{SVG_PLAY}<span>{esc(p['play_label'])}</span></button>
    <a class="readbtn" href="{read_target}" id="toread">{SVG_READ}<span>{esc(show['labels']['read'])}</span></a>
    {f'<button class="follow follow-top" type="button">{SVG_HEART}<span>{esc(show["follow"]["button"])}</span></button>' if show.get("follow") else ""}
    <div class="progress" id="progress" role="slider" aria-label="再生位置" tabindex="0"><div class="fill" id="fill"></div></div>
    <div class="time-row"><span id="cur">0:00</span><span id="dur">--:--</span></div>
    <div class="skips">{skip_btns}</div>
    <div class="speed"><div class="speed-k"><span>ゆっくり</span><span>聴く速さ</span><span>はやく</span></div>
      <div class="speed-row" id="speeds">{speeds}</div></div>
    {kbd}
  </div>
  <audio id="audio" src="{esc(audio)}" preload="metadata"></audio>
  <div class="mini" id="mini" aria-hidden="true">
    <button type="button" class="m-play" id="mplay" aria-label="再生／一時停止">{SVG_PLAY}</button>
    <button type="button" class="m-back" data-skip="-10">10秒もどる</button>
    <div class="m-bar"><div class="m-fill" id="mfill"></div></div>
    <span class="m-time" id="mtime">0:00</span>
  </div>"""


def player_js(show: dict) -> str:
    p = show["player"]
    cfg = json.dumps({"play": p["play_label"], "pause": p["pause_label"], "def": p["default_speed"],
                      "remember": bool(p.get("remember_speed")), "key": p.get("storage_key") or "",
                      "keyboard": bool(p.get("keyboard"))}, ensure_ascii=False)
    return """
<script>
(function(){
  var C = %s;
  var PLAY = '%s', PAUSE = '%s';
  var a = document.getElementById('audio'), play = document.getElementById('play'), mplay = document.getElementById('mplay');
  function fmt(s){ if (!isFinite(s)) return '--:--'; s = Math.floor(s); return Math.floor(s/60) + ':' + ('0' + s%%60).slice(-2); }
  function ui(){ var on = !a.paused;
    play.innerHTML = (on ? PAUSE : PLAY) + '<span>' + (on ? C.pause : C.play) + '</span>';
    mplay.innerHTML = on ? PAUSE : PLAY; }
  ui();
  function toggle(){ a.paused ? a.play() : a.pause(); }
  play.addEventListener('click', toggle); mplay.addEventListener('click', toggle);
  a.addEventListener('play', ui); a.addEventListener('pause', ui); a.addEventListener('ended', ui);
  function skip(s){ a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + s)); }
  document.querySelectorAll('[data-skip]').forEach(function(b){ b.addEventListener('click', function(){ skip(+b.dataset.skip); }); });
  var fill = document.getElementById('fill'), mfill = document.getElementById('mfill');
  a.addEventListener('loadedmetadata', function(){ document.getElementById('dur').textContent = fmt(a.duration); });
  a.addEventListener('timeupdate', function(){
    var r = a.duration ? a.currentTime / a.duration * 100 : 0;
    fill.style.width = r + '%%'; mfill.style.width = r + '%%';
    document.getElementById('cur').textContent = fmt(a.currentTime);
    document.getElementById('mtime').textContent = fmt(a.currentTime) + ' / ' + fmt(a.duration);
  });
  var prog = document.getElementById('progress');
  function seekAt(x){ var r = prog.getBoundingClientRect(); if (a.duration) a.currentTime = a.duration * Math.max(0, Math.min(1, (x - r.left) / r.width)); }
  prog.addEventListener('click', function(e){ seekAt(e.clientX); });
  prog.addEventListener('keydown', function(e){ if (e.key === 'ArrowLeft') skip(-10); if (e.key === 'ArrowRight') skip(10); });
  // 速さ：番組ごとの設定。覚える番組（AIニュース）は保存、毎回1倍の番組（スマホニュース）は保存しない
  var rate = C.def, sps = [].slice.call(document.querySelectorAll('#speeds button'));
  if (C.remember && C.key) { try { var s = localStorage.getItem(C.key); if (s && sps.some(function(b){ return b.dataset.r === s; })) rate = s; } catch(e) {} }
  function setRate(v){ rate = v; a.playbackRate = parseFloat(v); a.preservesPitch = true;
    sps.forEach(function(b){ b.classList.toggle('on', b.dataset.r === v); });
    if (C.remember && C.key) { try { localStorage.setItem(C.key, v); } catch(e) {} } }
  sps.forEach(function(b){ b.addEventListener('click', function(){ setRate(b.dataset.r); }); });
  setRate(rate);
  a.addEventListener('play', function(){ a.playbackRate = parseFloat(rate); });
  if (C.keyboard) document.addEventListener('keydown', function(e){
    if (/INPUT|TEXTAREA/.test(e.target.tagName) || e.metaKey || e.ctrlKey) return;
    if (e.key === ' ' || e.key === 'k') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowLeft') skip(-10); else if (e.key === 'ArrowRight') skip(10);
    else if (e.key === 'j') skip(-30); else if (e.key === 'l') skip(30);
  });
  // 大きなプレイヤーが画面の外に出たら、下に小さな再生バー
  var big = document.getElementById('player'), mini = document.getElementById('mini');
  function miniCheck(){ var out = big.getBoundingClientRect().bottom < 0; mini.classList.toggle('show', out); mini.setAttribute('aria-hidden', out ? 'false' : 'true'); }
  addEventListener('scroll', miniCheck, {passive:true}); miniCheck();
  // 本文：今の文に色をつけて画面がついていく。自分でスクロールした直後の8秒は追いかけない
  var lines = [].slice.call(document.querySelectorAll('.ln[data-t]')), now = null, userAt = 0;
  ['wheel','touchmove','keydown'].forEach(function(ev){ addEventListener(ev, function(){ userAt = Date.now(); }, {passive:true}); });
  function follow(force){
    var c = null;
    for (var i = 0; i < lines.length; i++) { if (+lines[i].dataset.t <= a.currentTime + 0.15) c = lines[i]; else break; }
    if (c === now && !force) return;
    if (now) now.classList.remove('now'); now = c; if (!now) return;
    now.classList.add('now');
    if (!a.paused && Date.now() - userAt > 8000) { var r = now.getBoundingClientRect();
      if (r.top < 60 || r.bottom > innerHeight - 90) scrollTo({ top: scrollY + r.top - innerHeight * 0.3, behavior: 'smooth' }); }
  }
  a.addEventListener('timeupdate', function(){ follow(false); });
  a.addEventListener('seeked', function(){ follow(true); });
  a.addEventListener('play', function(){ follow(true); });
  lines.forEach(function(l){ l.addEventListener('click', function(e){
    if (e.target.closest('.t') || e.target.closest('a')) return;      // 言葉の説明やリンクを押したときは再生しない
    userAt = 0; a.currentTime = +l.dataset.t; a.play(); }); });
  // 「この番組を毎回聴く」
  var fs = document.getElementById('fsheet'), fv = document.getElementById('fveil'), fbs = document.querySelectorAll('.follow');
  if (fs && fbs.length) { var op = function(){ fs.classList.add('on'); fv.classList.add('on'); }, cl = function(){ fs.classList.remove('on'); fv.classList.remove('on'); };
    fbs.forEach(function(b){ b.addEventListener('click', op); }); document.getElementById('fclose').addEventListener('click', cl); fv.addEventListener('click', cl);
    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') cl(); }); }
})();
</script>
""" % (cfg, SVG_PLAY, SVG_PAUSE)


# ─── 1回1枚のページ ───────────────────────────────────────
def episode_html(show: dict, ep: dict, terms: dict, prefix: str) -> str:
    """ep: date, number, title, audio, cover, items[{h}|{who,text,t}], news[], lesson, review[], homework, sources[{label,url}], desc"""
    L = show["labels"]
    ann = Annotator(terms, prefix=prefix, limit=show["glossary"].get("limit", 60))
    solo = show.get("solo")
    parts = []
    for it in ep["items"]:
        if "h" in it:
            parts.append(f"<h2>{esc(it['h'])}</h2>")
            continue
        role = show.get("speakers", {}).get(it.get("who", ""), "teacher")
        t = f' data-t="{it["t"]}"' if it.get("t") is not None else ""
        who = "" if solo else f'<span class="who">{esc(it.get("who", ""))}</span>'
        tag = "p" if solo else "div"
        parts.append(f'<{tag} class="ln {role}"{t}>{who}{ann(it["text"])}</{tag}>')
    contents = ""
    if ep.get("news") or ep.get("lesson"):
        contents = (f'<div class="card"><b>{esc(L["contents"])}</b>'
                    + (f'<br><span class="lbl">きっかけのニュース</span><ul>{"".join(f"<li>{esc(n)}</li>" for n in ep.get("news", []))}</ul>' if ep.get("news") else "")
                    + (f'<span class="lbl">今日のテーマ</span><ul><li>{esc(ep["lesson"])}</li></ul>' if ep.get("lesson") else "")
                    + "</div>")
    review = ""
    if ep.get("review"):
        review = (f'<div class="soft"><h2>{esc(L["review"])}</h2><ol>{"".join(f"<li>{esc(r)}</li>" for r in ep["review"])}</ol>'
                  + (f'<p class="hw"><b>{esc(L["homework"])}</b>　{esc(ep["homework"])}</p>' if ep.get("homework") else "") + "</div>")
    sources = ""
    if ep.get("sources"):
        sources = (f'<div class="src"><b>{esc(L["sources"])}</b><ul>'
                   + "".join(f'<li><a href="{esc(s["url"])}">{esc(s["label"])}</a></li>' for s in ep["sources"]) + "</ul></div>")
    when = f"{date_ja(ep['date'])}・{show['issue_word'].format(n=ep['number'])}"
    body = f"""{top_header(show, prefix, when)}
<main>
  <h1>{esc(ep['title'])}</h1>
{player_html(show, audio=ep['audio'], title=ep['title'], cover=ep['cover'], sub=when)}
  {contents}
  <h2 class="read-h" id="yomu">{esc(L['read'])}</h2>
  <p class="read-hint">{esc(show.get('read_hint', ''))}</p>
  <article>
{chr(10).join(parts)}
  </article>
  {review}
{follow_html(show)}
  {sources}
  <div class="links"><a href="{prefix}archive.html">{esc(L['archive'])}</a><a href="{prefix}terms/">{esc(show['glossary']['label'])}</a><a href="{prefix}">{esc(L['latest'])}</a></div>
  {footer(show)}
</main>"""
    base = show["base_url"].rstrip("/")
    url = f"{base}/episodes/{ep['date']}/"
    title = f"{ep['title']}｜{show['name']}"
    head = head_tags(show, url=url, title=title, desc=ep.get("desc") or ep["title"], published=ep["date"], kind="episode")
    return shell(show, title=title, head=head, body=body, prefix=prefix, extra_css=PLAYER_CSS,
                 tail=player_js(show) + ann.assets())


def redirect_html(to: str) -> str:
    return (f'<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><title>移動しました</title>'
            f'<meta http-equiv="refresh" content="0; url={esc(to)}"><link rel="canonical" href="{esc(to)}">'
            f'<script>location.replace({json.dumps(to)} + location.hash);</script></head>'
            f'<body><p><a href="{esc(to)}">新しいページへ移動します</a></p></body></html>\n')


# ─── バックナンバー・用語集・地図 ─────────────────────────
def archive_html(show: dict, eps: list) -> str:
    rows = "".join(f'<a href="episodes/{e["date"]}/"><div class="d">{date_ja(e["date"])}・{show["issue_word"].format(n=e["number"])}</div>'
                   f'<div class="ti">{esc(e["title"])}</div></a>' for e in eps)
    body = f"""{top_header(show, "", show["labels"]["archive"])}
<main><h1>{esc(show["labels"]["archive"])}</h1><p class="read-hint">{esc(show.get("schedule", ""))}に新しい回が出ます。</p>
<div class="arch">{rows}</div>
<div class="links"><a href="terms/">{esc(show['glossary']['label'])}</a><a href="./">{esc(show['labels']['latest'])}</a></div>
{footer(show)}</main>"""
    base = show["base_url"].rstrip("/")
    return shell(show, title=f"{show['labels']['archive']}｜{show['name']}",
                 head=head_tags(show, url=f"{base}/archive.html", title=f"{show['labels']['archive']}｜{show['name']}", desc=show["description"]),
                 body=body, prefix="", extra_css=TERMS_CSS)


def _mentions(repo: Path, slug: str) -> list:
    out = []
    for p in sorted((repo / "episodes").glob("*/index.html"), reverse=True):
        if f'data-t="{slug}"' in p.read_text(encoding="utf-8"):
            out.append(p.parent.name)
    return out[:8]


def term_html(show: dict, t: dict, terms: dict, titles: dict, repo: Path) -> str:
    ann = Annotator({k: v for k, v in terms.items() if k != t["slug"]}, prefix="../", limit=10)
    name = t["term"] + (f"（{t['reading']}）" if t.get("reading") else "")
    rel = "".join(f'<a href="{r}.html">{esc(terms[r]["term"])}</a>' for r in t.get("related", []) if r in terms)
    seen = "".join(f'<a href="../episodes/{d}/">{date_ja(d)}　{esc(titles.get(d, ""))}</a>' for d in _mentions(repo, t["slug"]))
    body = f"""{top_header(show, "../", "ことばの解説")}
<main><h1>{esc(name)}</h1>
  <div class="easy"><span class="klbl">ひとことで言うと</span><p>{esc(t['short'])}</p></div>
  <div class="detail"><span class="klbl">もう少しくわしく</span><p>{ann(t.get('detail') or t['short'])}</p></div>
  {f'<div class="detail"><span class="klbl">いっしょに知りたい言葉</span><div class="chips">{rel}</div></div>' if rel else ''}
  {f'<div class="detail"><span class="klbl">この言葉が出てきた回</span><div class="seen">{seen}</div></div>' if seen else ''}
  <div class="links"><a href="./">{esc(show['glossary']['label'])}へ</a><a href="../">{esc(show['labels']['latest'])}</a></div>
  {footer(show)}</main>"""
    base = show["base_url"].rstrip("/")
    title = f"{t['term']}とは｜{show['name']}"
    return shell(show, title=title, head=head_tags(show, url=f"{base}/terms/{t['slug']}.html", title=title, desc=t["short"]),
                 body=body, prefix="../", extra_css=TERMS_CSS, tail=ann.assets())


def terms_index_html(show: dict, terms: dict) -> str:
    g = show["glossary"]
    data = json.dumps([{"slug": t["slug"], "term": t["term"], "short": t["short"], "category": t.get("category", "その他"),
                        "reading": t.get("reading", ""), "aliases": t.get("aliases", [])} for t in terms.values()], ensure_ascii=False)
    body = f"""{top_header(show, "../", f"ことば {len(terms)}語")}
<main><h1>{esc(g['label'])}</h1><p class="read-hint">{esc(g.get('index_lead', ''))}</p>
  <div class="term-toolbar">
    <input type="search" id="termSearch" class="term-search" placeholder="{esc(g.get('search_placeholder', ''))}" aria-label="言葉をさがす">
    <div class="term-sort" role="group" aria-label="並び替え">
      <button type="button" data-sort="category" aria-pressed="true">ジャンル別</button>
      <button type="button" data-sort="kana">五十音順</button>
      <button type="button" data-sort="alpha">アルファベット順</button>
    </div>
  </div>
  <p class="term-count" id="termCount" aria-live="polite">{len(terms)} 語</p>
  <div id="termMain"></div>
  <div class="links"><a href="../archive.html">{esc(show['labels']['archive'])}</a><a href="../">{esc(show['labels']['latest'])}</a></div>
  {footer(show)}</main>
<script type="application/json" id="termData">{data}</script>
<script>{G.TERM_SEARCH_JS}</script>
<script>document.getElementById('termSearch').dispatchEvent(new Event('input'));</script>"""
    base = show["base_url"].rstrip("/")
    title = f"{g['label']}｜{show['name']}"
    return shell(show, title=title, head=head_tags(show, url=f"{base}/terms/", title=title, desc=g.get("index_lead", "")),
                 body=body, prefix="../", extra_css=TERMS_CSS)


def sitemap_xml(show: dict, paths: list) -> str:
    base = show["base_url"].rstrip("/")
    urls = "".join(f"  <url><loc>{esc(base)}/{p}</loc></url>\n" for p in paths)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'


def robots_txt(show: dict) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {show['base_url'].rstrip('/')}/sitemap.xml\n"
