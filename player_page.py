#!/usr/bin/env python3
"""
音声プレイヤー専用ページ（podcast/player.html）を、サイト本体と同じ見た目で生成する。

メールの「プレイヤーを開く」ボタンの飛び先。`?date=YYYY-MM-DD` で号を指定でき、
指定がなければ今日（日本時間）の号を開く。台本の表示・再生速度・スキップ・
キーボード操作は JavaScript 側で動く（音声ファイルと台本は同じフォルダにある）。

見た目は digest_page.py（日刊号ページ）の CSS をそのまま使い、
色・フォント・ヒーロー・フッターをサイト本体と揃える。持ち主の指示
「Webアプリの方のデザインがすごくいいのでそれを踏襲」による。
"""
import html as _html
from pathlib import Path

import digest_page
import site_theme

REPO_DIR = Path(__file__).parent
OUT_PATH = REPO_DIR / "podcast" / "player.html"

# 日刊号ページの CSS に、プレイヤー固有の部品だけ足す
PLAYER_CSS = """
  .player-wrap { max-width:760px; margin:0 auto; }
  .listen.player { padding:1.5rem 1.6rem 1.4rem; }
  .p-date { font-size:0.78rem; color:#64748b; letter-spacing:0.06em; }
  .p-title { margin-top:0.2rem; font-size:1.05rem; font-weight:700; color:#0b1f4d; }
  .p-head { display:flex; align-items:center; gap:1rem; }
  .p-head img { flex:none; width:84px; height:84px; border-radius:12px; box-shadow:0 4px 14px rgba(29,78,216,0.18); }
  .progress { margin-top:1.1rem; height:6px; background:#e2e8f0;
    border-radius:3px; cursor:pointer; overflow:hidden; }
  .progress-fill { height:100%; width:0; background:linear-gradient(90deg,#38bdf8,#1d4ed8); border-radius:3px; }
  .time-row { display:flex; justify-content:space-between; margin-top:0.4rem;
    font-size:0.72rem; color:#64748b; font-variant-numeric:tabular-nums; }
  .controls { display:flex; align-items:center; justify-content:center; gap:0.6rem;
    margin:1rem 0 0.4rem; }
  .ctl { background:none; border:none; color:#1e3a8a; cursor:pointer; padding:0.55rem;
    border-radius:50%; display:flex; flex-direction:column; align-items:center;
    -webkit-tap-highlight-color:transparent; }
  .ctl:hover { background:#eff6ff; }
  .ctl small { font-size:0.6rem; color:#64748b; margin-top:-2px; }
  .ctl.play { width:60px; height:60px; padding:0; justify-content:center;
    background:#1d4ed8; color:#fff; box-shadow:0 6px 18px rgba(29,78,216,0.35); }
  .ctl.play:hover { background:#2563eb; }
  .ctl svg { display:block; }
  .p-links { display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:1rem; }
  .p-links a { padding:0.35rem 0.8rem; border:1px solid #cbd5e1;
    border-radius:999px; font-size:0.74rem; color:#475569; text-decoration:none; }
  .p-links a:hover { background:#f1f5f9; }
  .follow { margin-top:1rem; text-align:center; }
  .follow-btn { display:inline-block; padding:0.5rem 1.6rem; border:0; border-radius:999px; cursor:pointer;
    background:#facc15; color:#0b1f4d; font:inherit; font-size:0.88rem; font-weight:800; letter-spacing:0.04em;
    box-shadow:0 3px 0 #ca8a04; -webkit-tap-highlight-color:transparent; }
  .follow-btn:active { transform:translateY(2px); box-shadow:0 1px 0 #ca8a04; }
  .follow-sheet { margin-top:0.7rem; display:grid; gap:0.5rem; text-align:left; }
  .follow-sheet[hidden] { display:none; }
  .follow-sheet a { display:block; padding:0.8rem 1rem; border-radius:10px; text-decoration:none;
    font-weight:700; font-size:0.92rem; text-align:center; }
  .follow-sheet a.sp { background:#1db954; color:#fff; }
  .follow-sheet a.ml { background:#fff; color:#1d4ed8; border:2px solid #1d4ed8; }
  .follow-sheet small { display:block; font-weight:500; font-size:0.72rem; opacity:0.85; margin-top:0.1rem; }
  details.script { max-width:760px; margin:1.5rem auto 0; background:var(--card-bg);
    border:1px solid var(--border); border-radius:8px; overflow:hidden; }
  details.script > summary { list-style:none; cursor:pointer; padding:1rem 1.3rem;
    font-weight:700; font-size:0.92rem; display:flex; align-items:center; gap:0.6rem; }
  details.script > summary::-webkit-details-marker { display:none; }
  details.script > summary::before { content:"▸"; font-size:0.8rem; color:var(--text-muted); }
  details.script[open] > summary::before { content:"▾"; }
  .turn { margin:0 1rem 0.8rem; padding:0.8rem 1rem; border-radius:6px; background:var(--bg);
    border-left:3px solid var(--border); font-size:0.9rem; line-height:1.9; }
  .turn .who { display:block; font-size:0.68rem; font-weight:700; letter-spacing:0.06em;
    color:var(--text-muted); margin-bottom:0.2rem; }
  .turn.terako { border-left-color:var(--accent); }
  .turn.mika { border-left-color:#db2777; }
  .turn.terako .who { color:var(--accent); }
  .turn.mika .who { color:#db2777; }
  .turn[data-t] { cursor:pointer; transition:background .25s, box-shadow .25s; }
  .turn[data-t]:hover { box-shadow:inset 0 0 0 1px var(--border); }
  .turn.now { background:#eff6ff; box-shadow:inset 0 0 0 2px #60a5fa; }
  .sync-note { margin:0 1.3rem 0.8rem; font-size:0.75rem; color:var(--text-muted); }
  .mini { position:fixed; left:50%; bottom:12px; transform:translate(-50%, 140%); z-index:50;
    width:min(760px, calc(100% - 24px)); box-sizing:border-box; display:flex; align-items:center; gap:0.8rem;
    padding:0.55rem 0.9rem; border-radius:999px; background:#fff; color:#0b1f4d; border:1px solid #dbe7fb;
    box-shadow:0 8px 28px rgba(15,23,42,0.18); transition:transform .25s; }
  .mini.show { transform:translate(-50%, 0); }
  .mini button { flex:none; width:40px; height:40px; border:0; border-radius:50%; background:#1d4ed8;
    color:#fff; display:flex; align-items:center; justify-content:center; cursor:pointer; padding:0; }
  .mini .m-bar { flex:1; height:4px; border-radius:2px; background:#e2e8f0; overflow:hidden; }
  .mini .m-fill { height:100%; width:0; background:#1d4ed8; }
  .mini .m-follow { flex:none; width:auto; height:auto; padding:0.45rem 0.8rem; border-radius:999px;
    background:#facc15; color:#0b1f4d; font:inherit; font-size:0.78rem; font-weight:800; }
  .mini .m-time { flex:none; font-size:0.78rem; font-variant-numeric:tabular-nums; }
  .status { padding:1rem 1.3rem; font-size:0.85rem; color:var(--text-muted); }
  .read-cta { max-width:760px; margin:1rem auto 0; display:block; padding:1rem 1.3rem;
    background:var(--card-bg); border:2px solid var(--accent); border-radius:8px;
    text-decoration:none; color:var(--text); }
  .read-cta strong { display:block; font-size:0.95rem; color:var(--accent); }
  .read-cta span { display:block; margin-top:0.2rem; font-size:0.78rem; color:var(--text-muted); line-height:1.7; }
  .kbd-help { max-width:760px; margin:1rem auto 0; font-size:0.72rem; color:var(--text-muted);
    text-align:center; }
  @media (max-width:640px){ .ctl.play{width:54px;height:54px} }
"""

_SVG_PLAY = '<svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><polygon points="7,4 21,12 7,20"/></svg>'
_SVG_PAUSE = ('<svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor">'
              '<rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>')
_SVG_BACK = ('<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round"><polyline points="1 4 1 10 7 10"/>'
             '<path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>')
_SVG_FWD = _SVG_BACK.replace('<svg ', '<svg style="transform:scaleX(-1)" ')


def build(config: dict) -> str:
    """2026-10-05 から、聴く・読むは記事のページ1枚に統合した（シリーズ共用エンジン）。
    player.html は、メールや過去のリンクから来た人を、その日の記事のページ（の音声の位置）へ移すだけのページ。
    ?date=YYYY-MM-DD か #YYYY-MM-DD があればその号、無ければトップ（最新号）へ。"""
    name = _html.escape(config.get("site", {}).get("name", "世界一わかりやすいAIニュース"))
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>音声版 | {name}</title><meta name="robots" content="noindex">
<script>
(function(){{
  var p = new URLSearchParams(location.search).get('date') || location.hash.slice(1);
  var to = /^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(p || '') ? '../ai-news-' + p + '.html#listen' : '../#listen';
  location.replace(to);
}})();
</script>
<noscript><meta http-equiv="refresh" content="0; url=../"></noscript>
</head><body><p><a href="../">{name} の最新号へ</a></p></body></html>
"""


def write(config: dict, verbose: bool = True) -> int:
    html = build(config)
    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    if verbose:
        print(f"✓ podcast/player.html ({len(html):,} bytes)")
    return len(html)


if __name__ == "__main__":
    import monetize
    write(monetize.load_config())
