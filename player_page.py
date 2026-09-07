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
  .p-date { font-size:0.78rem; color:#94a3b8; letter-spacing:0.06em; }
  .p-title { margin-top:0.2rem; font-size:1.05rem; font-weight:700; color:#fff; }
  .progress { margin-top:1.1rem; height:6px; background:rgba(255,255,255,0.15);
    border-radius:3px; cursor:pointer; overflow:hidden; }
  .progress-fill { height:100%; width:0; background:#22d3ee; border-radius:3px; }
  .time-row { display:flex; justify-content:space-between; margin-top:0.4rem;
    font-size:0.72rem; color:#94a3b8; font-variant-numeric:tabular-nums; }
  .controls { display:flex; align-items:center; justify-content:center; gap:0.6rem;
    margin:1rem 0 0.4rem; }
  .ctl { background:none; border:none; color:#e2e8f0; cursor:pointer; padding:0.55rem;
    border-radius:50%; display:flex; flex-direction:column; align-items:center;
    -webkit-tap-highlight-color:transparent; }
  .ctl:hover { background:rgba(255,255,255,0.1); }
  .ctl small { font-size:0.6rem; color:#94a3b8; margin-top:-2px; }
  .ctl.play { width:60px; height:60px; padding:0; justify-content:center;
    background:#22d3ee; color:#0f172a; box-shadow:0 4px 18px rgba(34,211,238,0.35); }
  .ctl.play:hover { background:#67e8f9; }
  .ctl svg { display:block; }
  .p-links { display:flex; flex-wrap:wrap; gap:0.5rem; margin-top:1rem; }
  .p-links a { padding:0.35rem 0.8rem; border:1px solid rgba(255,255,255,0.25);
    border-radius:999px; font-size:0.74rem; color:#e2e8f0; text-decoration:none; }
  .p-links a:hover { background:rgba(255,255,255,0.12); }
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
    site = config.get("site", {})
    name = site.get("name", "世界一わかりやすいAIニュース")
    esc = _html.escape
    speeds = [("0.75", "0.75×"), ("1", "1×"), ("1.25", "1.25×"),
              ("1.5", "1.5×"), ("2", "2×"), ("2.5", "2.5×")]
    speed_btns = "".join(
        f'<button type="button" class="speed-btn" data-speed="{v}">{label}</button>'
        for v, label in speeds
    )
    mail = site_theme.newsletter_links(config)["signup_url"]
    mail_link = f'<a href="{esc(mail)}" target="_blank" rel="noopener">メールで毎朝受け取る</a>' if mail else ""
    spotify = (config.get("podcast", {}).get("spotify_url") or "").strip()
    spotify_link = f'<a href="{esc(spotify)}" target="_blank" rel="noopener">Spotify で聴く</a>' if spotify else ""

    body = f"""<div class="hero">
  <div class="hero-inner">
    <div class="crumbs"><a href="../">{esc(name)}</a></div>
    <h1>🎧 音声版 <span id="hDate"></span></h1>
    <p>対話形式・ながら聴き向け。てらこ先生とミカが、今日のAIニュースをやさしく解説します。</p>
    <div class="top-nav">
      <a href="../">トップ</a>
      <a id="newsLink" href="../">この号を読む</a>
      <a href="../archive.html">バックナンバー</a>
      <a href="../terms/">AI用語集</a>
    </div>
  </div>
</div>

<main>
  <div class="player-wrap">
    <div class="listen player">
      <div class="p-date" id="pDate">読み込み中…</div>
      <div class="p-title">{esc(name)}</div>
      <audio id="audio" preload="metadata"></audio>
      <div class="progress" id="progress"><div class="progress-fill" id="fill"></div></div>
      <div class="time-row"><span id="cur">0:00</span><span id="dur">--:--</span></div>
      <div class="controls">
        <button type="button" class="ctl" id="b30" aria-label="30秒戻る">{_SVG_BACK}<small>30</small></button>
        <button type="button" class="ctl" id="b10" aria-label="10秒戻る">{_SVG_BACK}<small>10</small></button>
        <button type="button" class="ctl play" id="play" aria-label="再生">
          <span id="icPlay">{_SVG_PLAY}</span><span id="icPause" hidden>{_SVG_PAUSE}</span>
        </button>
        <button type="button" class="ctl" id="f10" aria-label="10秒進む">{_SVG_FWD}<small>10</small></button>
        <button type="button" class="ctl" id="f30" aria-label="30秒進む">{_SVG_FWD}<small>30</small></button>
      </div>
      <div class="speed-row"><span class="speed-label">再生速度</span>{speed_btns}</div>
      <div class="p-links">
        <a id="mp3Link" href="#">音声ファイルを開く</a>
        {mail_link}
        {spotify_link}
        <a href="feed.xml">ポッドキャストアプリ用アドレス</a>
      </div>
    </div>

    <a class="read-cta" id="readLink" href="../">
      <strong>この号を、専門用語の解説つきで読む →</strong>
      <span>記事では、企業名・モデル名・専門用語ぜんぶに注釈がつきます。聴いてわからなかった言葉は、こちらで確認できます。</span>
    </a>

    <details class="script" id="scriptBox">
      <summary>台本を読む</summary>
      <div id="scriptBody" class="status">読み込み中…</div>
    </details>
    <div class="kbd-help">キーボード：スペースで再生／停止、← → で10秒、J / L で30秒</div>
  </div>
</main>

<footer>
  <strong>{esc(name)}</strong> — 音声版<br>
  毎朝6時に自動生成・自動配信しています。
  {site_theme.footer_links(config, prefix="../")}
  {site_theme.footer_brand(config)}
</footer>

<script>
(function(){{
  var WD = ['日','月','火','水','木','金','土'];
  function pick(){{
    var p = new URLSearchParams(location.search).get('date');
    if (p && /^\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(p)) return p;
    if (/^#\\d{{4}}-\\d{{2}}-\\d{{2}}$/.test(location.hash)) return location.hash.slice(1);
    var now = new Date(Date.now() + 9*3600*1000);
    return now.toISOString().slice(0,10);
  }}
  var iso = pick(), d = new Date(iso + 'T00:00:00+09:00');
  var label = d.getFullYear() + '年' + (d.getMonth()+1) + '月' + d.getDate() + '日（' + WD[d.getDay()] + '）';
  document.getElementById('hDate').textContent = label;
  document.getElementById('pDate').textContent = label + ' の号';
  document.title = label + ' 音声版 | {esc(name)}';
  document.getElementById('newsLink').href = '../ai-news-' + iso + '.html';
  document.getElementById('readLink').href = '../ai-news-' + iso + '.html';
  document.getElementById('mp3Link').href = 'ai-news-' + iso + '.mp3';

  var a = document.getElementById('audio');
  a.src = 'ai-news-' + iso + '.mp3';
  var play = document.getElementById('play'), icP = document.getElementById('icPlay'), icQ = document.getElementById('icPause');
  function ui(on){{ icP.hidden = on; icQ.hidden = !on; play.setAttribute('aria-label', on ? '一時停止' : '再生'); }}
  play.addEventListener('click', function(){{ a.paused ? a.play() : a.pause(); }});
  a.addEventListener('play', function(){{ ui(true); }});
  a.addEventListener('pause', function(){{ ui(false); }});
  a.addEventListener('ended', function(){{ ui(false); }});
  a.addEventListener('error', function(){{
    document.getElementById('pDate').textContent = label + ' の音声はまだありません（毎朝6時ごろ公開）';
  }});

  function skip(s){{ a.currentTime = Math.max(0, Math.min(a.duration || 0, a.currentTime + s)); }}
  document.getElementById('b30').onclick = function(){{ skip(-30); }};
  document.getElementById('b10').onclick = function(){{ skip(-10); }};
  document.getElementById('f10').onclick = function(){{ skip(10); }};
  document.getElementById('f30').onclick = function(){{ skip(30); }};

  var fill = document.getElementById('fill'), cur = document.getElementById('cur'), dur = document.getElementById('dur');
  function fmt(s){{ if (!isFinite(s)) return '--:--'; s = Math.floor(s); return Math.floor(s/60) + ':' + ('0' + s%60).slice(-2); }}
  a.addEventListener('loadedmetadata', function(){{ dur.textContent = fmt(a.duration); }});
  a.addEventListener('timeupdate', function(){{
    fill.style.width = (a.duration ? a.currentTime / a.duration * 100 : 0) + '%';
    cur.textContent = fmt(a.currentTime);
  }});
  document.getElementById('progress').addEventListener('click', function(e){{
    var r = this.getBoundingClientRect();
    if (a.duration) a.currentTime = a.duration * Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  }});

  // 再生速度：記事ページ内のプレイヤーと同じ保存キーを使い、どのページでも同じ速度になる
  var btns = document.querySelectorAll('.speed-btn'), saved = '1';
  try {{ saved = localStorage.getItem('wk-speed') || '1'; }} catch(e) {{}}
  function apply(v){{
    a.playbackRate = parseFloat(v); saved = v;
    btns.forEach(function(b){{ b.classList.toggle('on', b.dataset.speed === v); }});
    try {{ localStorage.setItem('wk-speed', v); }} catch(e) {{}}
  }}
  apply(saved);
  a.addEventListener('play', function(){{ a.playbackRate = parseFloat(saved); }});
  btns.forEach(function(b){{ b.addEventListener('click', function(){{ apply(b.dataset.speed); }}); }});

  document.addEventListener('keydown', function(e){{
    if (/INPUT|TEXTAREA/.test(e.target.tagName)) return;
    if (e.key === ' ' || e.key === 'k') {{ e.preventDefault(); a.paused ? a.play() : a.pause(); }}
    else if (e.key === 'ArrowLeft') skip(-10);
    else if (e.key === 'ArrowRight') skip(10);
    else if (e.key === 'j') skip(-30);
    else if (e.key === 'l') skip(30);
  }});

  function esc(s){{ return s.replace(/[&<>"']/g, function(c){{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]; }}); }}
  fetch('script-' + iso + '.txt').then(function(r){{ return r.ok ? r.text() : Promise.reject(); }}).then(function(t){{
    var out = [];
    t.split('\\n').forEach(function(line){{
      var m = line.match(/^\\[(てらこ先生|ミカ)\\]\\s*(.+)$/);
      if (m) out.push('<div class="turn ' + (m[1] === 'てらこ先生' ? 'terako' : 'mika') + '"><span class="who">' + m[1] + '</span>' + esc(m[2]) + '</div>');
    }});
    document.getElementById('scriptBody').className = '';
    document.getElementById('scriptBody').innerHTML = out.length ? out.join('') : '<div class="status">この号の台本はまだありません。</div>';
  }}).catch(function(){{
    document.getElementById('scriptBody').innerHTML = '<div class="status">台本を読み込めませんでした。</div>';
  }});
}})();
</script>"""

    return site_theme.page_shell(
        f"音声版 | {name}", "", body,
        extra_css=digest_page.DIGEST_CSS + PLAYER_CSS,
    )


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
