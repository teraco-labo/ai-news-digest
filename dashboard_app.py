#!/usr/bin/env python3
"""AI News Digest ローカルダッシュボード"""

import subprocess
import json
import os
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

REPO_DIR = Path(__file__).parent
PODCAST_DIR = REPO_DIR / "podcast"
PREFS_FILE = REPO_DIR / "user_preferences.json"
try:
    from monetize import site_url as _site_url
    BASE_URL = _site_url()
except Exception:
    BASE_URL = "https://teraco-labo.github.io/ai-news-digest"
GH_TOKEN = os.getenv("GH_TOKEN", "")
PORT = 8920


def get_latest_news_date():
    """最新のニュースHTMLの日付を取得"""
    files = sorted(REPO_DIR.glob("ai-news-????-??-??.html"), reverse=True)
    if files:
        return files[0].stem.replace("ai-news-", "")
    return datetime.now().strftime("%Y-%m-%d")


def get_episodes():
    """エピソード一覧を取得（ローカル優先、なければ GitHub Pages から）"""
    ep_file = PODCAST_DIR / "episodes.json"
    if ep_file.exists():
        with open(ep_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # リモートから取得
    import urllib.request
    try:
        url = f"{BASE_URL}/podcast/episodes.json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return []


def trigger_github_actions():
    """GitHub Actions を手動トリガー"""
    result = subprocess.run(
        ["gh", "workflow", "run", "Generate AI News Digest",
         "--repo", "teraco-labo/ai-news-digest"],
        env={**os.environ, "GH_TOKEN": GH_TOKEN},
        capture_output=True, text=True
    )
    return result.returncode == 0


def load_user_preferences():
    """ユーザー評価データを読み込む"""
    if PREFS_FILE.exists():
        try:
            with open(PREFS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"rated_articles": {}}
    return {"rated_articles": {}}


def save_user_preferences(prefs):
    """ユーザー評価データを保存"""
    with open(PREFS_FILE, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


def rate_article(article_id: str, rating: int):
    """記事の評価を保存"""
    prefs = load_user_preferences()
    if "rated_articles" not in prefs:
        prefs["rated_articles"] = {}
    prefs["rated_articles"][article_id] = {
        "rating": rating,
        "timestamp": datetime.now().isoformat()
    }
    save_user_preferences(prefs)


def extract_articles_from_html(html_file: Path):
    """HTMLファイルから記事データを抽出"""
    import re

    try:
        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()

        articles = []
        # 記事パターンをマッチング
        pattern = r'<article class="card (\w+)">.*?<div class="card-title-ja">(.+?)</div>.*?<div class="card-body">(.+?)</div>'

        for match in re.finditer(pattern, content, re.DOTALL):
            category, title, summary = match.groups()
            article_id = f"{html_file.stem}_{len(articles)}"
            articles.append({
                "id": article_id,
                "category": category,
                "title": title.strip(),
                "summary": summary.strip()[:150]
            })

        return articles
    except:
        return []


def build_dashboard_html():
    latest_date = get_latest_news_date()
    latest_html_file = REPO_DIR / f"ai-news-{latest_date}.html"
    episodes = get_episodes()
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    # ユーザー評価を読み込む
    prefs = load_user_preferences()
    rated = prefs.get("rated_articles", {})

    # API コストダッシュボードを生成
    try:
        from api_dashboard import generate_api_dashboard_html
        api_dashboard_html = generate_api_dashboard_html()
    except:
        api_dashboard_html = ""

    # ニュースリンクHTML生成
    news_files = sorted([x.name for x in REPO_DIR.glob("ai-news-????-??-??.html")], reverse=True)[:5]
    news_links = []
    for fname in news_files:
        date_part = Path(fname).stem.replace("ai-news-", "")
        news_links.append(
            f'<a class="news-link" href="{BASE_URL}/ai-news-{date_part}.html" target="_blank">'
            f'<span>📄</span><div><div>{date_part}</div>'
            f'<div class="news-date">AI News Digest</div></div></a>'
        )
    news_links_html = "".join(news_links) if news_links else '<p class="no-data">まだニュースがありません</p>'

    # 最新の記事を抽出
    latest_articles = extract_articles_from_html(latest_html_file) if latest_html_file.exists() else []

    # 記事カードHTML生成
    articles_html = ""
    cat_colors = {
        "research": "#6d28d9",
        "business": "#065f46",
        "policy": "#92400e",
        "tools": "#0e7490"
    }
    cat_names = {
        "research": "研究",
        "business": "ビジネス",
        "policy": "ポリシー",
        "tools": "ツール"
    }

    for article in latest_articles[:8]:
        article_id = article["id"]
        rating = rated.get(article_id, {}).get("rating", 0)
        color = cat_colors.get(article["category"], "#1d4ed8")
        cat_name = cat_names.get(article["category"], "その他")

        stars_html = ""
        for i in range(1, 6):
            filled = "★" if i <= rating else "☆"
            stars_html += f'<span class="star" onclick="rateArticle(\'{article_id}\', {i})" style="cursor: pointer; color: {color};">{filled}</span>'

        articles_html += f"""
        <div class="article-card">
          <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 0.5rem;">
            <span style="background: {color}; color: white; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">{cat_name}</span>
            <div class="star-rating">{stars_html}</div>
          </div>
          <div style="font-weight: 600; margin-bottom: 0.5rem; color: #e2e8f0;">{article['title'][:60]}</div>
          <div style="font-size: 0.85rem; color: #94a3b8; margin-bottom: 0.5rem;">{article['summary']}</div>
        </div>"""

    articles_section = f"""
  <!-- 最新ニュースプレビュー -->
  <div class="card">
    <div class="card-title">📰 最新ニュース（{latest_date}）</div>
    <div style="display: grid; gap: 0.75rem;">{articles_html if articles_html else '<p class="no-data">記事がありません</p>'}</div>
  </div>""" if articles_html else ""

    # エピソードカードHTML
    ep_cards = ""
    for ep in episodes[:5]:
        date = ep.get("date", "")
        title = ep.get("title", "")
        duration = ep.get("duration", "")
        audio_url = ep.get("url", "")
        ep_cards += f"""
        <div class="ep-card">
          <div class="ep-meta">{date} · {duration}</div>
          <div class="ep-title">{title}</div>
          <audio controls preload="none">
            <source src="{audio_url}" type="audio/mpeg">
          </audio>
        </div>"""

    if not ep_cards:
        ep_cards = '<p class="no-data">まだエピソードがありません</p>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI News Digest — ダッシュボード</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Helvetica Neue', 'Hiragino Sans', sans-serif;
    background: #0f172a;
    color: #e2e8f0;
    min-height: 100vh;
  }}
  header {{
    background: #1e293b;
    padding: 1.5rem 2rem;
    border-bottom: 1px solid #334155;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .logo {{ font-size: 1.3rem; font-weight: 700; color: #60a5fa; }}
  .updated {{ font-size: 0.8rem; color: #64748b; }}
  main {{ max-width: 900px; margin: 2rem auto; padding: 0 1.5rem; display: grid; gap: 1.5rem; }}

  /* カード共通 */
  .card {{
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1.5rem;
  }}
  .card-title {{
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: #60a5fa;
    text-transform: uppercase;
    margin-bottom: 1rem;
  }}

  /* ニュース */
  .news-link {{
    display: flex;
    align-items: center;
    gap: 1rem;
    background: #0f172a;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    text-decoration: none;
    color: #e2e8f0;
    font-size: 1rem;
    font-weight: 500;
    margin-bottom: 0.75rem;
    border: 1px solid #334155;
    transition: border-color 0.2s;
  }}
  .news-link:hover {{ border-color: #60a5fa; }}
  .news-date {{ font-size: 0.8rem; color: #64748b; }}

  /* 記事カード */
  .article-card {{
    background: #0f172a;
    border-radius: 8px;
    padding: 1rem;
    border: 1px solid #334155;
    transition: border-color 0.2s;
  }}
  .article-card:hover {{ border-color: #60a5fa; }}
  .star-rating {{
    font-size: 1.2rem;
    letter-spacing: 0.2rem;
  }}

  /* ポッドキャスト */
  .ep-card {{
    background: #0f172a;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.75rem;
    border: 1px solid #334155;
  }}
  .ep-meta {{ font-size: 0.75rem; color: #64748b; margin-bottom: 0.3rem; }}
  .ep-title {{ font-size: 0.95rem; font-weight: 500; margin-bottom: 0.75rem; }}
  audio {{ width: 100%; height: 36px; }}

  /* ボタン */
  .btn {{
    display: inline-block;
    padding: 0.6rem 1.4rem;
    border-radius: 8px;
    font-size: 0.875rem;
    font-weight: 600;
    cursor: pointer;
    border: none;
    text-decoration: none;
    transition: opacity 0.2s;
  }}
  .btn:hover {{ opacity: 0.85; }}
  .btn-primary {{ background: #1d4ed8; color: #fff; }}
  .btn-secondary {{ background: #334155; color: #e2e8f0; }}
  .btn-green {{ background: #065f46; color: #fff; }}
  .actions {{ display: flex; gap: 0.75rem; flex-wrap: wrap; }}

  .no-data {{ color: #64748b; font-size: 0.875rem; }}
  .rss-url {{ font-size: 0.8rem; color: #60a5fa; word-break: break-all; margin-top: 0.5rem; }}

  /* API料金・管理リンク */
  .link-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; }}
  .link-item {{
    display: flex; align-items: center; gap: 0.75rem;
    background: #0f172a; border: 1px solid #334155; border-radius: 8px;
    padding: 0.875rem 1rem; text-decoration: none; color: #e2e8f0;
    transition: border-color 0.2s;
  }}
  .link-item:hover {{ border-color: #60a5fa; }}
  .link-icon {{ font-size: 1.4rem; flex-shrink: 0; }}
  .link-name {{ font-size: 0.875rem; font-weight: 600; margin-bottom: 0.2rem; }}
  .link-desc {{ font-size: 0.75rem; color: #64748b; }}
</style>
</head>
<body>
<header>
  <div class="logo">🗞 AI News Digest</div>
  <div class="updated">最終確認: {now}</div>
</header>
<main>

  <!-- クイックアクション -->
  <div class="card">
    <div class="card-title">⚡ クイックアクション</div>
    <div class="actions">
      <a href="{BASE_URL}/ai-news-{latest_date}.html" target="_blank" class="btn btn-primary">📰 最新ニュースを開く</a>
      <a href="{BASE_URL}/podcast/feed.xml" target="_blank" class="btn btn-secondary">📡 RSS フィード</a>
      <button class="btn btn-green" onclick="runActions()">🔄 今すぐニュースを生成</button>
    </div>
  </div>

{articles_section}

  <!-- 最新ニュース -->
  <div class="card">
    <div class="card-title">📰 最近のニュース</div>
    {news_links_html}
  </div>

  <!-- ポッドキャスト -->
  <div class="card">
    <div class="card-title">🎙 ポッドキャスト</div>
    {ep_cards}
    <div class="rss-url">RSS: {BASE_URL}/podcast/feed.xml</div>
  </div>

  {api_dashboard_html}

  <!-- 管理リンク -->
  <div class="card">
    <div class="card-title">🔗 管理ページ &amp; リンク</div>
    <div class="link-grid">
      <a href="https://console.anthropic.com/settings/usage" target="_blank" class="link-item">
        <div class="link-icon">🟠</div>
        <div>
          <div class="link-name">Anthropic (Claude)</div>
          <div class="link-desc">ニュース分類・台本生成 / 月150円目安</div>
        </div>
      </a>
      <a href="https://console.cloud.google.com/apis/api/texttospeech.googleapis.com/metrics?project=gen-lang-client-0725014665" target="_blank" class="link-item">
        <div class="link-icon">🔵</div>
        <div>
          <div class="link-name">Google Cloud TTS</div>
          <div class="link-desc">音声生成 / 月300〜400円目安</div>
        </div>
      </a>
      <a href="https://console.cloud.google.com/billing?project=gen-lang-client-0725014665" target="_blank" class="link-item">
        <div class="link-icon">💳</div>
        <div>
          <div class="link-name">Google Cloud 請求</div>
          <div class="link-desc">Google全体の費用確認</div>
        </div>
      </a>
      <a href="https://creators.spotify.com/pod/show/0kuCanHapeNX2ALHYvzbf3/home" target="_blank" class="link-item">
        <div class="link-icon">🎵</div>
        <div>
          <div class="link-name">Spotify for Creators</div>
          <div class="link-desc">てらこAIニュースダイジェスト 管理画面</div>
        </div>
      </a>
      <a href="https://github.com/teraco-labo/ai-news-digest/actions" target="_blank" class="link-item">
        <div class="link-icon">⚙️</div>
        <div>
          <div class="link-name">GitHub Actions</div>
          <div class="link-desc">自動生成ワークフローのログ</div>
        </div>
      </a>
      <a href=BASE_URL target="_blank" class="link-item">
        <div class="link-icon">🌐</div>
        <div>
          <div class="link-name">公開サイト</div>
          <div class="link-desc">GitHub Pages</div>
        </div>
      </a>
    </div>
  </div>

</main>

<script>
function runActions() {{
  if (!confirm('今すぐGitHub Actionsを実行してニュースを生成しますか？')) return;
  fetch('/trigger', {{method: 'POST'}})
    .then(r => r.json())
    .then(d => alert(d.ok ? '✅ 実行開始しました！5〜10分後に確認してください' : '❌ 実行失敗: ' + d.error));
}}

function rateArticle(articleId, rating) {{
  fetch('/rate', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{articleId, rating}})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.ok) {{
      // 星を即座に更新
      const stars = document.querySelectorAll(`[data-article-id="{'{articleId}'}"] .star`);
      stars.forEach((s, i) => {{
        s.textContent = i < rating ? '★' : '☆';
      }});
    }}
  }})
  .catch(e => console.error('Rating failed:', e));
}}
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # ログを抑制

    def do_GET(self):
        html = build_dashboard_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        if self.path == "/trigger":
            ok = trigger_github_actions()
            response_body = json.dumps({"ok": ok}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response_body)

        elif self.path == "/rate":
            try:
                data = json.loads(body)
                article_id = data.get("articleId", "")
                rating = data.get("rating", 0)

                if article_id and 1 <= rating <= 5:
                    rate_article(article_id, rating)
                    response_body = json.dumps({"ok": True, "message": "評価を保存しました"}).encode()
                else:
                    response_body = json.dumps({"ok": False, "message": "不正なデータ"}).encode()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response_body)
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())


if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), Handler)
    print(f"✅ ダッシュボード起動: http://localhost:{PORT}")
    server.serve_forever()
