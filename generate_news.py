#!/usr/bin/env python3

import os
import re
import json
import sys
from datetime import datetime, timedelta, timezone

# JST = UTC+9
# GitHub Actions の cron は UTC 21:00（= JST 翌朝 06:00）に走るため、
# datetime.now() を UTC のままで使うと日付が前日扱いになる。
# 必ず JST 基準で「今日」を判定する。
JST = timezone(timedelta(hours=9))
from pathlib import Path
from typing import List, Dict, Optional
import subprocess
import requests
import xml.etree.ElementTree as ET

# Load environment variables (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

REPO_DIR = Path(__file__).parent

# 収益化レイヤー（未設定でも no-op なので、失敗しても本体は止めない）
try:
    import monetize
    import seo_builder
    import social_kit
    import curate
    import digest_page
    MONETIZE_AVAILABLE = True
    SITE_URL = monetize.site_url()
    PODCAST_URL = monetize.podcast_url()
except Exception as _e:
    print(f"⚠️  収益化モジュールの読み込みに失敗しました（ダイジェスト生成は続行）: {_e}")
    MONETIZE_AVAILABLE = False
    SITE_URL = "https://teraco-labo.github.io/ai-news-digest"
    PODCAST_URL = SITE_URL

CATEGORIES = ["model", "research", "business", "policy", "tools"]
CATEGORIES_JA = {
    "model": "モデル",
    "research": "研究",
    "business": "ビジネス",
    "policy": "ポリシー",
    "tools": "ツール",
}
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


def parse_pub_date(pub_str: str) -> Optional[datetime]:
    """
    RSS pubDate（RFC 2822）または Atom published（ISO 8601）を
    UTC ナイーブ datetime に変換する。失敗時は None を返す。
    """
    if not pub_str:
        return None
    pub_str = pub_str.strip()
    # RFC 2822: "Mon, 12 May 2026 06:00:00 +0000"
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_str)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        pass
    # ISO 8601: "2026-05-12T06:00:00Z" / "2026-05-12T06:00:00+00:00"
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(pub_str[:19], fmt)
        except Exception:
            pass
    # 日付のみ: "2026-05-12"
    try:
        return datetime.strptime(pub_str[:10], "%Y-%m-%d")
    except Exception:
        return None


def fetch_rss_news(date: datetime) -> List[Dict]:
    """Fetch AI news from free RSS feeds (no API key required)."""
    RSS_SOURCES = [
        ("TechCrunch AI",   "https://techcrunch.com/category/artificial-intelligence/feed/"),
        ("VentureBeat AI",  "https://venturebeat.com/category/ai/feed/"),
        ("The Verge AI",    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
        ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
        ("Wired AI",        "https://www.wired.com/feed/tag/ai/latest/rss"),
        ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/index"),
    ]

    # Keywords to filter general feeds (Ars Technica etc.)
    AI_KEYWORDS = [
        "ai", "artificial intelligence", "machine learning", "llm", "gpt", "claude",
        "gemini", "openai", "anthropic", "neural", "deep learning", "generative",
        "chatbot", "language model", "llama", "mistral", "deepseek", "chatgpt",
    ]

    all_articles: List[Dict] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AINewsBot/1.0)"}

    # ---- 直近 24 時間のカットオフ（UTC ナイーブ）----
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff_utc = now_utc - timedelta(hours=24)
    print(f"  📅 24h フィルター: {cutoff_utc.strftime('%Y-%m-%d %H:%M')} UTC 以降のみ取得")

    for source_name, url in RSS_SOURCES:
        try:
            resp = requests.get(url, timeout=15, headers=headers)
            if resp.status_code != 200:
                print(f"⚠️  {source_name}: HTTP {resp.status_code}")
                continue

            root = ET.fromstring(resp.content)

            # Support both RSS 2.0 (<item>) and Atom (<entry>)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//atom:entry", ns)

            count = 0
            skipped_old = 0
            for item in items:
                title = (
                    item.findtext("title") or
                    item.findtext("atom:title", namespaces=ns) or ""
                ).strip()

                desc = (
                    item.findtext("description") or
                    item.findtext("atom:summary", namespaces=ns) or ""
                ).strip()
                # Strip HTML tags from description
                import re
                desc = re.sub(r"<[^>]+>", "", desc)[:600]

                link_elem = item.find("link")
                link = ""
                if link_elem is not None:
                    link = link_elem.text or link_elem.get("href", "")
                if not link:
                    link = item.findtext("atom:link", namespaces=ns) or ""

                pub_raw = (
                    item.findtext("pubDate") or
                    item.findtext("atom:published", namespaces=ns) or ""
                )
                pub_date_str = pub_raw[:10]  # YYYY-MM-DD（表示用）

                if not title or not link:
                    continue

                # ---- 24 時間フィルター（厳格）----
                pub_dt = parse_pub_date(pub_raw)
                if pub_dt is not None and pub_dt < cutoff_utc:
                    skipped_old += 1
                    continue

                # AI relevance filter for general feeds
                text_lower = (title + " " + desc).lower()
                if source_name == "Ars Technica":
                    if not any(kw in text_lower for kw in AI_KEYWORDS):
                        continue

                all_articles.append({
                    "title": title,
                    "description": desc,
                    "source": {"name": source_name},
                    "publishedAt": pub_date_str,
                    "url": link,
                })
                count += 1
                if count >= 10:
                    break

            old_note = f", {skipped_old}件は24h超で除外" if skipped_old else ""
            print(f"✓ {source_name}: {count} articles{old_note}")

        except Exception as e:
            print(f"⚠️  {source_name}: {e}")

    # ---- リアルタイム情報源を追加（X / Hacker News）----
    try:
        all_articles.extend(fetch_x_news(cutoff_utc))
    except Exception as e:
        print(f"⚠️  X 取得エラー: {e}")
    try:
        all_articles.extend(fetch_hackernews(cutoff_utc))
    except Exception as e:
        print(f"⚠️  Hacker News 取得エラー: {e}")

    # Deduplicate by normalised title prefix
    seen: set = set()
    unique: List[Dict] = []
    for a in all_articles:
        key = a["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(a)

    print(f"✓ Total: {len(unique)} unique articles from all sources")
    return unique[:60]


def fetch_x_news(cutoff_utc: datetime) -> List[Dict]:
    """
    X（旧Twitter）のAI主要アカウントの投稿を Nitter 経由で取得する（無料・APIキー不要）。
    Nitter インスタンスは不安定なため複数を順に試し、全滅したらスキップする。
    """
    # 監視するAI主要アカウント（公式・キーパーソン・発信頻度の高い識者）
    X_ACCOUNTS = [
        "OpenAI", "AnthropicAI", "GoogleDeepMind", "GoogleAI",
        "sama", "demishassabis", "AndrewYNg", "ylecun",
        "karpathy", "DrJimFan", "alexandr_wang", "_akhaliq",
        "rowancheung", "OfficialLoganK",
    ]
    # X は個々のアカウントの投稿頻度が低いため、本文より広い48時間枠で拾う
    x_cutoff = cutoff_utc - timedelta(hours=24)
    # Nitter インスタンス（生きているものを順に試す）
    NITTER_INSTANCES = [
        "https://nitter.net",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AINewsBot/1.0)"}

    # 生きている Nitter インスタンスを1つ選ぶ
    active_instance = None
    for inst in NITTER_INSTANCES:
        try:
            r = requests.get(f"{inst}/OpenAI/rss", timeout=8, headers=headers)
            if r.status_code == 200 and b"<item>" in r.content:
                active_instance = inst
                break
        except Exception:
            continue

    if not active_instance:
        print("⚠️  X (Nitter): 利用可能なインスタンスなし → X はスキップ")
        return []

    print(f"  🐦 X (Nitter): {active_instance} を使用")
    results: List[Dict] = []

    for account in X_ACCOUNTS:
        try:
            resp = requests.get(f"{active_instance}/{account}/rss",
                                timeout=10, headers=headers)
            if resp.status_code != 200:
                continue
            root = ET.fromstring(resp.content)
            count = 0
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                if not title:
                    continue
                # リツイート・リプライは除外（ノイズ削減）
                if title.startswith("RT by ") or title.startswith("R to "):
                    continue
                pub_dt = parse_pub_date(item.findtext("pubDate") or "")
                if pub_dt is not None and pub_dt < x_cutoff:
                    continue
                link = (item.findtext("link") or "").replace(
                    active_instance, "https://x.com").split("#")[0]
                desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "")[:400]
                results.append({
                    "title": title[:200],
                    "description": desc,
                    "source": {"name": f"X / @{account}"},
                    "publishedAt": (item.findtext("pubDate") or "")[:10],
                    "url": link,
                    # X はリアルタイム性が高いので重要度をやや高めに設定
                    "importance": 3,
                })
                count += 1
                if count >= 3:   # 1アカウントあたり最大3件
                    break
        except Exception:
            continue

    print(f"✓ X (Nitter): {len(results)} posts from {len(X_ACCOUNTS)} accounts")
    return results


def fetch_hackernews(cutoff_utc: datetime) -> List[Dict]:
    """
    Hacker News から直近24時間の高ポイントAI記事を取得する（Algolia API・無料）。
    ポイント数が「一般ユーザーの関心の高さ」を示す良い指標になる。
    """
    import time as _time
    cutoff_ts = int(_time.mktime(cutoff_utc.timetuple()))
    queries = ["AI", "LLM", "OpenAI", "Anthropic", "machine learning"]
    seen_ids: set = set()
    results: List[Dict] = []

    for q in queries:
        try:
            url = (
                "https://hn.algolia.com/api/v1/search_by_date"
                f"?query={requests.utils.quote(q)}&tags=story"
                f"&numericFilters=points%3E80,created_at_i%3E{cutoff_ts}"
                "&hitsPerPage=10"
            )
            resp = requests.get(url, timeout=12)
            if resp.status_code != 200:
                continue
            for hit in resp.json().get("hits", []):
                oid = hit.get("objectID")
                if oid in seen_ids:
                    continue
                seen_ids.add(oid)
                title = (hit.get("title") or "").strip()
                points = hit.get("points", 0)
                if not title:
                    continue
                hn_url = f"https://news.ycombinator.com/item?id={oid}"
                results.append({
                    "title": title,
                    "description": f"Hacker News で{points}ポイント獲得。コミュニティで注目を集めている話題。",
                    "source": {"name": "Hacker News"},
                    "publishedAt": (hit.get("created_at") or "")[:10],
                    "url": hit.get("url") or hn_url,
                    # ポイント数で重要度を段階付け
                    "importance": 3 if points >= 200 else 2,
                })
        except Exception:
            continue

    # ポイント順で上位のみ
    print(f"✓ Hacker News: {len(results)} stories (points>80, 24h)")
    return results


def categorize_by_keywords(title: str, description: str) -> str:
    """Keyword-based AI news categorization (no API required)."""
    text = ((title or "") + " " + (description or "")).lower()

    scores = {
        "model": sum(1 for kw in [
            "model", "gpt", "claude", "gemini", "llama", "mistral", "deepseek",
            "weights", "training", "fine-tuning", "parameter", "architecture",
            "transformer", "chatgpt", "copilot", "multimodal", "language model",
            "release", "launched", "announced new", "version",
        ] if kw in text),
        "research": sum(1 for kw in [
            "research", "paper", "study", "university", "findings", "discovers",
            "breakthrough", "arxiv", "benchmark", "dataset", "efficiency",
            "scientists", "published", "journal", "algorithm", "method",
        ] if kw in text),
        "business": sum(1 for kw in [
            "funding", "investment", "company", "startup", "acquisition",
            "partnership", "market", "revenue", "valuation", "billion", "million",
            "ceo", "ipo", "venture", "enterprise", "deal", "merger", "raises",
        ] if kw in text),
        "policy": sum(1 for kw in [
            "policy", "regulation", "government", "law", "ethics", "safety",
            "governance", "congress", "senate", "eu", "ban", "restriction",
            "rights", "privacy", "risk", "compliance", "act", "legislation",
        ] if kw in text),
        "tools": sum(1 for kw in [
            "tool", "platform", "api", "software", "plugin", "library",
            "framework", "sdk", "integration", "app", "feature", "update",
            "deploy", "open source", "github", "developer", "open-source",
        ] if kw in text),
    }

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "research"


def translate_ja(text: str) -> str:
    """Translate English text to Japanese using Google Translate public endpoint (no API key)."""
    if not text:
        return text
    try:
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "ja", "dt": "t", "q": text},
            timeout=8,
        )
        data = resp.json()
        return "".join(seg[0] for seg in data[0] if seg[0])
    except Exception:
        return text  # fall back to original on error


def categorize_articles(articles: List[Dict]) -> Dict[str, List[Dict]]:
    """Categorize articles by keyword matching and translate to Japanese. No paid API."""
    result: Dict[str, List[Dict]] = {cat: [] for cat in CATEGORIES}

    for article in articles:
        title = article.get("title", "")
        description = article.get("description", "")
        source = article.get("source", {}).get("name", "Unknown")
        url = article.get("url", "")

        if not title or not url:
            continue

        category = categorize_by_keywords(title, description)

        title_ja = translate_ja(title)
        summary_ja = translate_ja(description[:500]) if description else "詳細は記事をご覧ください。"

        entry = {
            "category": category,
            "title_ja": title_ja,
            "title_en": title,
            "summary": summary_ja,
            # 英語原文も保持する。ポッドキャスト台本生成では機械翻訳ではなく
            # この原文を Gemini に渡し、自然な日本語に噛み砕かせる（翻訳調を防ぐ）
            "summary_en": (description or "")[:500],
            "source": source,
            "date": article.get("publishedAt", "")[:10],
            "url": url,
            # 取得元が設定した importance を尊重（X=3, HN=2〜3, 通常RSS=2）
            "importance": article.get("importance", 2),
        }
        result[category].append(entry)
        print(f"✓ [{category}] {title_ja[:60]}")

    total = sum(len(v) for v in result.values())
    print(f"✓ {total} articles categorised")
    return result


def generate_html(articles_by_category: Dict[str, List[Dict]], target_date: datetime,
                  overview: Optional[List[str]] = None,
                  podcast_available: bool = False) -> str:
    """ダイジェストHTMLを生成する。

    旧実装は過去の HTML を読み込んで文字列置換していたが、構造が固定され
    記事が何件あっても同じグリッドに敷き詰められる作りだった。
    描画は digest_page.py に移し、重要度順・要点先出しのレイアウトにしている。
    """
    import digest_page
    return digest_page.render(
        articles_by_category, target_date,
        overview=overview, podcast_available=podcast_available,
    )


def save_html(html_content: str, date: datetime) -> Path:
    """Save HTML to file."""
    date_str = date.strftime("%Y-%m-%d")
    output_file = REPO_DIR / f"ai-news-{date_str}.html"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✓ Saved: {output_file}")
    return output_file


def send_email_draft(email_html: str, target_date: datetime) -> bool:
    """Send email draft to user via Gmail API or SMTP."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    email_to = "fujisaki@teraco-labo.com"
    date_str = target_date.strftime("%Y年%m月%d日")

    try:
        # Try Gmail API first (for local/interactive mode)
        try:
            # Using Gmail MCP - only works in interactive sessions
            import requests
            gmail_api_url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
            # This would require OAuth2 token setup
        except Exception:
            pass

        # Fallback: Use SMTP via Gmail
        gmail_user = os.getenv("GMAIL_ADDRESS")
        gmail_pass = os.getenv("GMAIL_APP_PASSWORD")

        if not gmail_user or not gmail_pass:
            print(f"⚠️  Gmail credentials not configured.")
            print(f"   Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD to enable email delivery.")
            return False

        # Create email message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"世界一わかりやすいAIニュース - {date_str}"
        msg["From"] = gmail_user
        msg["To"] = email_to
        # 標準の配信停止ヘッダー（メールクライアントの「配信停止」ボタンに対応）
        msg["List-Unsubscribe"] = (
            f"<mailto:{gmail_user}?subject=配信停止希望>"
        )
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        # Attach HTML content
        part = MIMEText(email_html, "html", "utf-8")
        msg.attach(part)

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(gmail_user, gmail_pass)
            server.sendmail(gmail_user, [email_to], msg.as_string())

        print(f"✓ Email sent to: {email_to}")
        return True

    except smtplib.SMTPAuthenticationError:
        print(f"❌ Email auth failed: Invalid credentials")
        return False
    except smtplib.SMTPException as e:
        print(f"❌ Email send error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


def update_index_html(date: datetime):
    """Update index.html to redirect to latest digest (only if date is newer)."""
    import re as _re
    date_str = date.strftime("%Y-%m-%d")
    latest_file = f"ai-news-{date_str}.html"
    index_path = REPO_DIR / "index.html"

    # Check current redirect date — don't regress to an older date
    if index_path.exists():
        current = index_path.read_text(encoding="utf-8")
        m = _re.search(r"ai-news-(\d{4}-\d{2}-\d{2})\.html", current)
        if m and m.group(1) >= date_str:
            print(f"⏭  index.html already points to {m.group(1)} (≥ {date_str}), skipping")
            return

    index_html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url={latest_file}">
  <title>世界一わかりやすいAIニュース</title>
</head>
<body>
  Redirecting to <a href="{latest_file}">latest digest</a>...
</body>
</html>
"""

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"✓ Updated index.html → {latest_file}")


def build_email_html(categorized: Dict[str, List[Dict]], date: datetime, include_recommendations: bool = True, podcast_available: bool = True) -> str:
    """Build HTML email content with styled articles."""
    date_str = date.strftime("%Y年%m月%d日")
    weekday = WEEKDAYS_JA[date.weekday()]

    # Import recommendation engine
    try:
        from recommendation_engine import analyze_user_preferences, generate_recommendations, add_recommendations_to_email
        use_recommendations = include_recommendations
    except:
        use_recommendations = False

    email_html = (
        """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  body { font-family: 'Hiragino Sans', 'Helvetica Neue', sans-serif; max-width: 600px; margin: 0; padding: 20px; background: #f5f5f5; }
  .container { background: white; border-radius: 8px; padding: 30px; }
  .header { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #60a5fa; padding: 20px; border-radius: 8px; margin-bottom: 30px; text-align: center; }
  .header h1 { margin: 0; font-size: 24px; }
  .header p { margin: 5px 0 0 0; font-size: 12px; color: #94a3b8; }
  .section { margin-bottom: 30px; }
  .section-title { font-size: 16px; font-weight: bold; color: #1e293b; margin-bottom: 15px; padding-bottom: 8px; border-bottom: 2px solid #e2e8f0; }
  .article { margin-bottom: 15px; padding: 12px; background: #f8fafc; border-left: 3px solid #60a5fa; border-radius: 4px; }
  .article-title { font-weight: bold; color: #1e293b; margin-bottom: 5px; font-size: 14px; }
  .article-summary { font-size: 13px; color: #475569; line-height: 1.5; margin-bottom: 5px; }
  .article-source { font-size: 11px; color: #64748b; }
  .footer { text-align: center; margin-top: 30px; padding-top: 20px; border-top: 1px solid #e2e8f0; color: #64748b; font-size: 12px; }
  .podcast-box { background: #f0f4f8; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
  .podcast-box h3 { margin: 0 0 10px 0; color: #1e293b; font-size: 14px; }
  .podcast-box a { color: #60a5fa; text-decoration: none; font-size: 12px; }
  .category-model { border-left-color: #1d4ed8; }
  .category-research { border-left-color: #6d28d9; }
  .category-business { border-left-color: #065f46; }
  .category-policy { border-left-color: #92400e; }
  .category-tools { border-left-color: #0e7490; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>世界一わかりやすいAIニュース</h1>
    <p>"""
        + date_str
        + """（"""
        + weekday
        + """）</p>
  </div>

  <p>おはようございます！</p>
  <p>世界一わかりやすいAIニュース、本日の最新情報をお届けします。</p>
  <!-- PODCAST_PLACEHOLDER -->
"""
    )

    # Build podcast box (inserted at top, before articles)
    date_iso = date.strftime("%Y-%m-%d")
    total_articles = sum(len(v) for v in categorized.values())

    if podcast_available:
        # プレイヤーページ（速度調整・スキップ・台本表示付き）
        player_url = f"{PODCAST_URL}/podcast/player.html?date={date_iso}"
        audio_url  = f"{PODCAST_URL}/podcast/ai-news-{date_iso}.mp3"
        podcast_box = (
            '\n  <div class="podcast-box">\n'
            '    <h3>🎙️ 本日の音声ダイジェスト（重要ニュースを詳しく解説）</h3>\n'
            f'    <p>厳選ニュースを音声でお届けします。通勤・家事のお供に。</p>\n'
            f'    <p style="margin:12px 0;">\n'
            f'      <a href="{player_url}" style="background:#0f172a;color:#60a5fa;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;display:inline-block;">▶ プレイヤーを開く（速度調整・台本付き）</a>\n'
            f'    </p>\n'
            f'    <p style="font-size:12px;color:#475569;margin:6px 0;">\n'
            f'      🎧 <a href="{audio_url}" style="color:#60a5fa;">MP3を直接再生</a>'
            f' &nbsp;·&nbsp; 💾 <a href="{audio_url}" download style="color:#60a5fa;">ダウンロード</a>'
            f'    </p>\n'
            '    <p style="font-size:11px;color:#64748b;">\n'
            f'      <a href="{PODCAST_URL}/podcast/feed.xml" style="color:#94a3b8;">📡 RSSフィード（Spotify登録用）</a>\n'
            '    </p>\n'
            '  </div>\n\n'
        )
    else:
        # ポッドキャスト生成失敗時：MP3 リンクを出さない（リンク切れ防止）
        podcast_box = (
            '\n  <div class="podcast-box" style="background:#fef3c7;border-left:4px solid #f59e0b;">\n'
            '    <h3>🎙️ 本日の音声ダイジェスト</h3>\n'
            '    <p style="color:#78350f;">本日はニュース件数が少なく、音声版の生成をスキップしました。下記のテキスト版をご覧ください。</p>\n'
            '    <p style="font-size:11px;color:#92400e;">\n'
            f'      <a href="{PODCAST_URL}/podcast/feed.xml" style="color:#92400e;">📡 過去エピソード（RSS / Spotify）</a>\n'
            '    </p>\n'
            '  </div>\n\n'
        )
    email_html = email_html.replace("  <!-- PODCAST_PLACEHOLDER -->\n", podcast_box)

    # Add articles by category
    category_colors = {
        "research": "#6d28d9",
        "business": "#065f46",
        "policy": "#92400e",
        "tools": "#0e7490"
    }

    for category in CATEGORIES:
        if category not in categorized or not categorized[category]:
            continue

        articles = categorized[category]
        cat_display = CATEGORIES_JA.get(category, category.upper())
        color = category_colors.get(category, "#1d4ed8")

        email_html += f'\n  <div class="section">\n    <div class="section-title">【{cat_display}】 ({len(articles)}件)</div>\n'

        for i, article in enumerate(articles, 1):
            title_ja = article.get('title_ja', '')
            summary = article.get('summary', '')[:200]
            source = article.get('source', 'Unknown')
            url = article.get('url', '')
            translate_url = f"https://translate.google.com/translate?hl=ja&sl=auto&tl=ja&u={requests.utils.quote(url, safe='')}" if url else ''
            email_html += f'    <div class="article category-{category}">\n'
            email_html += f'      <div class="article-title">{i}. {title_ja}</div>\n'
            email_html += f'      <div class="article-summary">{summary}</div>\n'
            email_html += f'      <div class="article-source">{source}'
            if url:
                email_html += f' &nbsp;·&nbsp; <a href="{url}" style="color:#60a5fa;">元記事</a>'
            if translate_url:
                email_html += f' &nbsp;·&nbsp; <a href="{translate_url}" style="color:#818cf8;">🇯🇵 日本語で読む</a>'
            email_html += '</div>\n'
            email_html += f'    </div>\n'

        email_html += "  </div>\n"

    unsubscribe_mailto = (
        "mailto:fujisaki@teraco-labo.com"
        "?subject=配信停止希望"
        "&body=このメールをそのまま送信すると、世界一わかりやすいAIニュースの配信を停止します。"
    )
    email_html += '  <div class="footer">\n'
    email_html += f'    <p>世界一わかりやすいAIニュース | <a href="{SITE_URL}" style="color: #60a5fa; text-decoration: none;">サイトを見る</a></p>\n'
    email_html += (
        '    <p style="margin-top:10px;font-size:11px;color:#94a3b8;">\n'
        '      このメールは「世界一わかりやすいAIニュース」の購読者にお届けしています。<br>\n'
        f'      配信を停止したい場合は <a href="{unsubscribe_mailto}" style="color:#94a3b8;text-decoration:underline;">こちらから配信停止</a> してください。\n'
        '    </p>\n'
    )
    email_html += '  </div>\n'
    email_html += '</div>\n'
    email_html += '</body>\n'
    email_html += '</html>'

    # Add recommendations if enabled
    if use_recommendations:
        try:
            user_analysis = analyze_user_preferences(categorized)
            recommendations = generate_recommendations(user_analysis)
            email_html = add_recommendations_to_email(email_html, recommendations)
        except Exception as e:
            print(f"⚠️  Recommendation engine error: {e}")

    return email_html


def save_email_html(email_html: str, date: datetime) -> Path:
    """Save email HTML to file for manual sending."""
    date_str = date.strftime("%Y-%m-%d")
    email_file = REPO_DIR / f".email-draft-{date_str}.html"

    with open(email_file, "w", encoding="utf-8") as f:
        f.write(email_html)

    return email_file


def commit_and_push(date: datetime):
    """Commit and push changes to GitHub."""
    date_str = date.strftime("%Y-%m-%d")

    try:
        os.chdir(REPO_DIR)

        # Git operations
        # 実行中のブランチに対して pull/push する。main 固定だと、開発ブランチでの
        # テスト実行時に main へ rebase しようとして衝突し、成果物が push されない。
        branch = os.getenv("GITHUB_REF_NAME", "")
        if not branch:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True,
            ).stdout.strip() or "main"

        subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"feat: AI News Digest {date_str}"],
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "pull", "--rebase", "origin", branch],
                       check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", f"HEAD:{branch}"],
                       check=True, capture_output=True)

        print(f"✓ Git push completed")

    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git error: {e.stderr.decode()}")


def main():
    """Main execution."""
    # Parse command line arguments
    # 必ず JST 基準で「今日」を判定する (GitHub Actions は UTC で動くため)
    target_date = datetime.now(JST).replace(tzinfo=None)
    if len(sys.argv) > 2 and sys.argv[1] == "--date":
        try:
            target_date = datetime.strptime(sys.argv[2], "%Y-%m-%d")
        except ValueError:
            print("Invalid date format. Use YYYY-MM-DD")
            sys.exit(1)

    print(f"\n📰 Generating AI News Digest for {target_date.strftime('%Y-%m-%d')}")

    # Step 1: Fetch articles from free RSS feeds
    print("\n1️⃣  Fetching articles from RSS feeds...")
    articles = fetch_rss_news(target_date)

    if not articles:
        print("❌ No articles fetched. Exiting.")
        return

    # Step 2: 掲載する記事を選び、日本語で書き直す（Claude）
    print("\n2️⃣  Curating articles...")
    overview: List[str] = []
    categorized = None
    if MONETIZE_AVAILABLE:
        curated = curate.curate(articles)
        if curated:
            categorized = curated["categorized"]
            overview = curated["overview"]

    if categorized is None:
        # キュレーションが使えない場合は従来のキーワード分類にフォールバックする
        print("   キーワード分類にフォールバックします")
        categorized = categorize_articles(articles)

    total = sum(len(v) for v in categorized.values())
    if total == 0:
        print("❌ No articles successfully categorized. Exiting.")
        return

    # Step 3: Generate podcast (edge-tts, free)
    print("\n3️⃣  Generating podcast...")
    podcast_ok = False
    try:
        from generate_podcast_dialogue import generate_podcast
        podcast_ok = bool(generate_podcast(categorized, target_date))
    except Exception as e:
        print(f"⚠️  Podcast generation error: {e}")

    # MP3 が物理的に存在しているかを最終チェック
    expected_mp3 = REPO_DIR / "podcast" / f"ai-news-{target_date.strftime('%Y-%m-%d')}.mp3"
    if not (expected_mp3.exists() and expected_mp3.stat().st_size > 0):
        if podcast_ok:
            print(f"⚠️  MP3 が見つからないため podcast_ok=False に修正: {expected_mp3.name}")
        podcast_ok = False

    print(f"   ポッドキャスト: {'✓ 生成成功' if podcast_ok else '✗ 生成失敗（メールではリンクを省略）'}")

    # Step 4: HTMLを組み立てて保存（音声の有無が確定してから描画する）
    print("\n4️⃣  Generating HTML...")
    html_content = generate_html(categorized, target_date,
                                 overview=overview, podcast_available=podcast_ok)

    # SEOメタ（OGP/canonical/JSON-LD）とアフィリエイト枠を後付けで注入する。
    # 案件URLが未設定なら何も差し込まれないため、設定前でも安全に動く。
    if MONETIZE_AVAILABLE:
        try:
            html_content = monetize.apply_to_digest(html_content, categorized, target_date)
        except Exception as e:
            print(f"⚠️  収益化レイヤーの注入をスキップしました: {e}")

    output_file = save_html(html_content, target_date)

    # Step 5: Build email HTML（送信はpush後）
    print("\n5️⃣  Building email HTML...")
    email_html = build_email_html(categorized, target_date, podcast_available=podcast_ok)
    email_file = save_email_html(email_html, target_date)
    print(f"✓ Email draft saved: {email_file.name}")

    # Step 6: サイト全体を再構築（トップ / アーカイブ / 解説記事 / sitemap / RSS）
    print("\n6️⃣  Building site (index / archive / articles / sitemap / feed)...")
    if MONETIZE_AVAILABLE:
        try:
            seo_builder.build_all()
        except Exception as e:
            print(f"⚠️  サイトビルドに失敗しました: {e}")
            update_index_html(target_date)  # 最低限リダイレクトだけは維持する
    else:
        update_index_html(target_date)

    # SNS投稿キット（コピペ用。自動投稿はしない）
    if MONETIZE_AVAILABLE:
        try:
            social_kit.write_kit(categorized, target_date)
        except Exception as e:
            print(f"⚠️  SNS投稿キットの生成をスキップしました: {e}")

    # Step 7: Commit and push（メール送信より先に実行）
    pushed = False
    if os.getenv("GITHUB_TOKEN"):
        print("\n7️⃣  Committing and pushing...")
        commit_and_push(target_date)
        pushed = True
    else:
        print("\n⚠️  GITHUB_TOKEN not set. Skipping git operations.")

    # Step 8: メール送信（push 後、GitHub Pages デプロイ待機してから送信）
    print("\n8️⃣  Sending email...")
    # 開発ブランチでのテスト実行時はメールを送らない。
    # Pages は main からしか配信されないため、リンク切れのメールが届いてしまう。
    branch = os.getenv("GITHUB_REF_NAME", "")
    if branch and branch not in ("main", "master"):
        print(f"   テスト実行（ブランチ: {branch}）のためメール送信をスキップします")
        print(f"   ドラフトは {email_file.name} に保存済みです")
        email_sent = True
    else:
        if pushed:
            # GitHub Pages のデプロイ完了を待つ（通常 1〜2 分）
            import time
            wait_sec = 90
            print(f"   GitHub Pages デプロイ待機中…（{wait_sec}秒）")
            time.sleep(wait_sec)
        email_sent = send_email_draft(email_html, target_date)
    if not email_sent:
        print(f"⚠️  Email draft ready at: {email_file.name}")
        print(f"   GMAIL_ADDRESS と GMAIL_APP_PASSWORD を設定すると自動送信されます。")

    print(f"\n✅ Success! Generated: {output_file.name}")


if __name__ == "__main__":
    main()
