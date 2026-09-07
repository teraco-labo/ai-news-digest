#!/usr/bin/env python3
"""
世界一わかりやすいAIニュース — 音声生成
edge-tts (Microsoft Neural voices) を使用。APIキー・費用不要。
"""

import asyncio
import json
import re
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from typing import Dict, List

REPO_DIR    = Path(__file__).parent
PODCAST_DIR = REPO_DIR / "podcast"

CATEGORIES_JA = {
    "model":    "モデル・リリース",
    "research": "研究・技術",
    "business": "ビジネス・産業",
    "policy":   "政策・倫理",
    "tools":    "ツール・開発",
}

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

VOICE    = "ja-JP-NanamiNeural"
# 公開URLは monetize_config.json で一元管理する（アカウント移管・独自ドメイン対応）
try:
    from monetize import podcast_url as _podcast_url
    BASE_URL = _podcast_url()
except Exception:
    BASE_URL = "https://teraco-labo.github.io/ai-news-digest"
COVER_URL = f"{BASE_URL}/podcast/cover.jpg"
PODCAST_EMAIL = "fujisaki@teraco-labo.com"

# カテゴリごとの最大記事数（合計 14 件程度を Gemini に渡す）
# 重要度順で選ばれ、最終的に Gemini が9〜11件を選んで15分前後に深掘りする
MAX_PER_CATEGORY = {
    "model":    3,
    "research": 3,
    "business": 3,
    "policy":   2,
    "tools":    3,
}

# 記事間のつなぎフレーズ（ローテーション）
_TRANSITIONS = [
    "次のニュースです。",
    "続いてこちら。",
    "次のトピックです。",
    "もう一件ご紹介します。",
    "次のニュースに参ります。",
]

# ---------------------------------------------------------------------------
# TTS 発音改善：略語・固有名詞をカタカナに変換
# ---------------------------------------------------------------------------
_TTS_REPLACEMENTS = [
    # --- 運営元まわりの読み（辞書登録）---
    # 番組名は「世界一わかりやすいAIニュース」で日本語なので変換は不要。
    # Teraco News はフッターの署名にだけ使う通称。万一読み上げに混ざっても
    # 変な読みにならないよう登録しておく。
    # 長い表記から先に置換すること（"Teraco" 単体を先に処理すると
    # "Teraco News" が壊れるため、必ずこの順序を守る）。
    ("Teraco Voice", "テラコボイス"),   # 本人の声クローンの製品名（2026-09-05 登録）
    ("TERACO VOICE", "テラコボイス"),
    ("TeracoVoice",  "テラコボイス"),
    ("Teraco News", "テラコニュース"),
    ("TERACO NEWS", "テラコニュース"),
    ("TeracoNews",  "テラコニュース"),
    ("TERACO.LABO", "テラコラボ"),
    ("Teraco",      "テラコ"),
    ("TERACO",      "テラコ"),
    ("ChatGPT",   "チャットジーピーティー"),
    ("GPT-4o",    "ジーピーティーフォーオー"),
    ("GPT-4",     "ジーピーティーフォー"),
    ("GPT-5.5",   "ジーピーティーファイブポイントファイブ"),
    ("GPT-5",     "ジーピーティーファイブ"),
    ("GPT-o3",    "ジーピーティーオースリー"),
    ("GPT-o4",    "ジーピーティーオーフォー"),
    ("GPT",       "ジーピーティー"),
    ("LLMs",      "エルエルエム"),
    ("LLM",       "エルエルエム"),
    ("xAI",       "エックスエーアイ"),
    ("OpenAI",    "オープンエーアイ"),
    ("AGI",       "エージーアイ"),
    ("APIs",      "エーピーアイ"),
    ("API",       "エーピーアイ"),
    ("DeepSeek",  "ディープシーク"),
    ("GitHub",    "ギットハブ"),
    ("AWS",       "エーダブリューエス"),
    ("TSMC",      "ティーエスエムシー"),
    ("SpaceX",    "スペースエックス"),
    ("CEO",       "シーイーオー"),
    ("CTO",       "シーティーオー"),
    ("CFO",       "シーエフオー"),
    ("IPO",       "アイピーオー"),
    ("EU",        "ヨーロッパ連合"),
    ("FCC",       "米国連邦通信委員会"),
    ("SDK",       "エスディーケー"),
    ("RLHF",      "アールエルエイチエフ"),
    ("SOTA",      "最先端"),
]


def preprocess_for_tts(text: str) -> str:
    """TTS 読み上げ用にテキストを前処理する。"""
    if not text:
        return text
    for pattern, replacement in _TTS_REPLACEMENTS:
        text = text.replace(pattern, replacement)
    # 英数字と日本語の境界にスペース挿入（NanamiNeural が自然に読むため）
    text = re.sub(r"([A-Za-z0-9])([ぁ-んァ-ン一-龯])", r"\1 \2", text)
    text = re.sub(r"([ぁ-んァ-ン一-龯])([A-Z])", r"\1 \2", text)
    return text


def clean_text(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", text)
    for k, v in {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
                 "&#8217;": "'", "&#8220;": "「", "&#8221;": "」",
                 "&#8230;": "…", "\xa0": " "}.items():
        text = text.replace(k, v)
    return text.strip()


# ---------------------------------------------------------------------------
# 重要記事の選定（カテゴリごとに上位 N 件）
# ---------------------------------------------------------------------------

def select_top_articles(articles_by_category: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    selected: Dict[str, List[Dict]] = {}
    for cat, articles in articles_by_category.items():
        max_n = MAX_PER_CATEGORY.get(cat, 2)
        sorted_arts = sorted(articles, key=lambda a: a.get("importance", 2), reverse=True)
        selected[cat] = sorted_arts[:max_n]
    return selected


# ---------------------------------------------------------------------------
# Script builder
# ---------------------------------------------------------------------------

def build_script(articles_by_category: Dict[str, List[Dict]], date: datetime) -> str:
    date_str = date.strftime("%Y年%m月%d日")
    weekday  = WEEKDAYS_JA[date.weekday()]

    selected    = select_top_articles(articles_by_category)
    total       = sum(len(v) for v in selected.values())
    trans_index = 0

    lines: List[str] = []

    # ---- オープニング ----
    lines.append(
        f"世界一わかりやすいAIニュース。"
        f"{date_str}、{weekday}曜日版をお届けします。"
        f"本日は特に注目の{total}件をピックアップし、内容まで詳しく解説します。"
        f"ではさっそく参りましょう。"
    )
    lines.append("")

    article_num = 0
    first_in_category = True

    for category, cat_name in CATEGORIES_JA.items():
        articles = selected.get(category, [])
        if not articles:
            continue

        # カテゴリ見出し
        lines.append(f"■ {cat_name}のコーナーです。")
        lines.append("")
        first_in_category = True

        for article in articles:
            article_num += 1

            # ---- 記事間のつなぎ（最初の記事はスキップ）----
            if not first_in_category:
                transition = _TRANSITIONS[trans_index % len(_TRANSITIONS)]
                trans_index += 1
                lines.append(transition)
                lines.append("")
            first_in_category = False

            # フィールド取得・クリーニング
            title   = preprocess_for_tts(clean_text(
                article.get("title_ja") or article.get("title_en") or ""
            ))
            summary = preprocess_for_tts(clean_text(article.get("summary") or ""))
            source  = preprocess_for_tts(clean_text(article.get("source") or ""))

            if summary in ("Read the full article for details.", "詳細は記事をご覧ください。"):
                summary = ""

            # 番号＋タイトル
            title_clean = title.rstrip("。．.")
            lines.append(f"{article_num}つ目。{title_clean}。")

            if source:
                lines.append(f"（{source} より）")

            if summary:
                if len(summary) > 500:
                    summary = summary[:497] + "…"
                lines.append(summary)

            lines.append("")

        # カテゴリ間のブリッジ
        lines.append("")

    # ---- クロージング ----
    lines.append(
        f"以上、本日の注目 {total}件をお届けしました。"
        "世界一わかりやすいAIニュース、また明日もお楽しみに。"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audio generation (edge-tts, async)
# ---------------------------------------------------------------------------

async def _generate_async(script: str, output_path: Path) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(script, VOICE)
    await communicate.save(str(output_path))


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# RSS feed（Spotify / Apple Podcasts 対応フォーマット）
# ---------------------------------------------------------------------------

def _rfc2822(date_str: str) -> str:
    """'YYYY-MM-DD' → RFC 2822 形式（Spotify の pubDate に必要）。"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # 毎朝 JST 06:00 (= UTC 21:00 前日) に設定
        import calendar, time
        ts = calendar.timegm(dt.timetuple()) + 21 * 3600  # UTC 21:00 前日 → 簡易
        return formatdate(ts, usegmt=True)
    except Exception:
        return formatdate(usegmt=True)


def _hms(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, s   = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"



def _episode_description(ep: Dict) -> str:
    """エピソードの説明欄（概要欄）。音声だけ聴いた人を、用語解説つきの記事へ案内する。
    この番組の強みは「記事中の専門用語にぜんぶ注釈がつく」ことなので、必ずリンクを置く。"""
    date = ep.get("date", "")
    article = f"{BASE_URL}/ai-news-{date}.html"
    player  = f"{BASE_URL}/podcast/player.html?date={date}"
    text = (f"{ep.get('title','')}。"
            f" 今日の内容は、専門用語の解説つきの記事でも読めます → {article}"
            f" ／ 台本つき音声プレイヤー → {player}")
    try:
        import monetize, site_theme
        mail = site_theme.newsletter_links(monetize.load_config())["signup_url"]
        if mail:
            text += f" ／ メールで毎朝受け取る（無料）→ {mail}"
    except Exception:
        pass
    return text.replace("&", "&amp;").replace("<", "&lt;")

def _feed_ready(episodes: List[Dict], today: str) -> List[Dict]:
    """Spotify などに配る feed.xml に載せてよい回だけを返す。

    当日の回は、本人の声（Teraco Voice）への差し替えが済むまで載せない。
    Spotify は同じURLの音声を取り直さないため、先に載せると edge-tts 版が
    そのまま残ってしまう（2026-09-05 に実際に起きた）。
    日付が変わった回は、差し替えが済んでいなくても載せる（Mac が寝ていた日の保険）。
    """
    voices_file = PODCAST_DIR / "voices.json"
    try:
        voices = json.loads(voices_file.read_text(encoding="utf-8"))
    except Exception:
        voices = {}
    out = []
    for e in episodes:
        d = e.get("date", "")
        if d != today or voices.get(d, {}).get("teraco"):
            out.append(e)
    return out


def update_feed(date: datetime, audio_file: Path) -> None:
    """episodes.json と Spotify/Apple 対応 feed.xml を更新する。"""
    PODCAST_DIR.mkdir(exist_ok=True)
    episodes_file = PODCAST_DIR / "episodes.json"

    episodes: List[Dict] = []
    if episodes_file.exists():
        try:
            episodes = json.loads(episodes_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    date_str   = date.strftime("%Y-%m-%d")
    audio_url  = f"{BASE_URL}/podcast/{audio_file.name}"
    size_bytes = audio_file.stat().st_size

    # ffprobe で正確な duration を取得（ビットレートが可変でも正しい値）
    duration_sec = 0
    try:
        import subprocess, shutil
        if shutil.which("ffprobe"):
            r = subprocess.run([
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_file),
            ], capture_output=True, text=True, timeout=10)
            if r.returncode == 0 and r.stdout.strip():
                duration_sec = int(float(r.stdout.strip()))
    except Exception:
        pass
    # フォールバック: 80kbps として概算
    if not duration_sec:
        duration_sec = size_bytes // 10000

    # 同じ日を作り直したとき（Teraco Voice への差し替えなど）は番号を据え置く。
    # 以前は「既存数+1」を先に計算していたため、作り直すたびに番号が1つ進んでいた
    existing = next((e for e in episodes if e.get("date") == date_str), None)
    episodes = [e for e in episodes if e.get("date") != date_str]
    # 新しい日は「これまでの最大番号+1」。以前の「件数+1」は一覧を60件で切っているため
    # 61で止まったままだった（2026-09-05 に発見。当面は番号がそこから続く）
    _nums = [int(e.get("episode_num") or 0) for e in episodes]
    ep_num = existing.get("episode_num") if existing and existing.get("episode_num") else (max(_nums) + 1 if _nums else 1)
    episodes.insert(0, {
        "date":        date_str,
        "title":       f"世界一わかりやすいAIニュース - {date_str}",
        "url":         audio_url,
        "size":        size_bytes,
        "duration":    duration_sec,
        "episode_num": ep_num,
    })
    # Spotify は size=0 / duration=0 のアイテムでパースに失敗する。
    # 必ず実体のある音声を持つエピソードのみフィードに含める。
    def _has_valid_audio(e: Dict) -> bool:
        try:
            return int(e.get("size", 0)) > 0 and int(e.get("duration", 0)) > 0
        except (TypeError, ValueError):
            return False
    episodes = [e for e in episodes if _has_valid_audio(e)]
    episodes = episodes[:60]

    episodes_file.write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- feed.xml に載せる回を選ぶ ----
    # Spotify は一度取り込んだ音声を、同じURLで中身を差し替えても取り直さない。
    # 朝はクラウドが edge-tts 版を作り、そのあと Mac が本人の声（Teraco Voice）に
    # 差し替えるので、当日分をすぐフィードに載せると Spotify には edge-tts 版が残る。
    # そこで「本人の声になった回」だけを載せる。ただし Mac が寝ていた日に配信が
    # 途切れないよう、日付が変わった回は声にかかわらず載せる（保険）。
    feed_episodes = _feed_ready(episodes, date_str)

    # ---- feed.xml ----
    items_xml = ""
    for i, ep in enumerate(feed_episodes):
        ep_ep_num = ep.get("episode_num", len(feed_episodes) - i)
        dur_hms   = _hms(ep.get("duration", 0))
        pub       = _rfc2822(ep.get("date", ""))
        items_xml += f"""
  <item>
    <title>{ep['title']}</title>
    <itunes:title>{ep['title']}</itunes:title>
    <description>{_episode_description(ep)}</description>
    <itunes:summary>{_episode_description(ep)}</itunes:summary>
    <author>{PODCAST_EMAIL}</author>
    <itunes:author>世界一わかりやすいAIニュース</itunes:author>
    <itunes:episode>{ep_ep_num}</itunes:episode>
    <itunes:episodeType>full</itunes:episodeType>
    <itunes:duration>{dur_hms}</itunes:duration>
    <itunes:explicit>false</itunes:explicit>
    <enclosure url="{ep['url']}" length="{ep.get('size', 0)}" type="audio/mpeg"/>
    <pubDate>{pub}</pubDate>
    <guid isPermaLink="false">{ep['url']}</guid>
  </item>"""

    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel>
  <title>世界一わかりやすいAIニュース</title>
  <itunes:title>世界一わかりやすいAIニュース</itunes:title>
  <description>毎朝6時配信。AIの最新ニュースを厳選してわかりやすくお届けします。</description>
  <itunes:summary>毎朝6時配信。AIの最新ニュースを厳選してわかりやすくお届けします。</itunes:summary>
  <link>{BASE_URL}</link>
  <language>ja</language>
  <author>{PODCAST_EMAIL} (てらこ先生)</author>
  <managingEditor>{PODCAST_EMAIL} (てらこ先生)</managingEditor>
  <copyright>てらこ先生</copyright>
  <itunes:author>てらこ先生</itunes:author>
  <itunes:owner>
    <itunes:name>てらこ先生</itunes:name>
    <itunes:email>{PODCAST_EMAIL}</itunes:email>
  </itunes:owner>
  <image>
    <url>{COVER_URL}</url>
    <title>世界一わかりやすいAIニュース</title>
    <link>{BASE_URL}</link>
  </image>
  <itunes:image href="{COVER_URL}"/>
  <itunes:explicit>false</itunes:explicit>
  <itunes:type>episodic</itunes:type>
  <itunes:category text="Technology">
    <itunes:category text="Tech News"/>
  </itunes:category>
  {items_xml}
</channel>
</rss>"""

    (PODCAST_DIR / "feed.xml").write_text(feed_xml, encoding="utf-8")
    print(f"  ✓ RSS feed: {len(episodes)} episodes")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_podcast(articles_by_category: Dict[str, List[Dict]], date: datetime) -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("⚠️  edge-tts not found. Run: pip install edge-tts")
        return False

    PODCAST_DIR.mkdir(exist_ok=True)
    date_str = date.strftime("%Y-%m-%d")

    # 1. 原稿生成
    print("  原稿を作成中...")
    script     = build_script(articles_by_category, date)
    char_count = len(script)
    est_min    = char_count // 250
    print(f"  原稿: {char_count} 文字 (推定約{est_min}分)")

    script_file = PODCAST_DIR / f"script-{date_str}.txt"
    script_file.write_text(script, encoding="utf-8")

    # 2. 音声生成
    output_file = PODCAST_DIR / f"ai-news-{date_str}.mp3"
    print(f"  音声生成中 ({VOICE})…")
    _run(_generate_async(script, output_file))

    size_mb = output_file.stat().st_size / 1_048_576
    print(f"  ✓ {output_file.name} ({size_mb:.1f} MB)")
    print(f"  📁 ローカルパス: {output_file.resolve()}")
    print(f"  🌐 公開URL: {BASE_URL}/podcast/{output_file.name}")

    # 3. RSS 更新
    update_feed(date, output_file)

    return True


# ---------------------------------------------------------------------------
# ローカルテスト用
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    date = datetime.strptime(sys.argv[1], "%Y-%m-%d") if len(sys.argv) > 1 else datetime.now()
    test_data: Dict[str, List[Dict]] = {
        "model": [
            {"title_ja": "オープンエーアイ、推論能力が向上した新モデルを発表",
             "title_en": "OpenAI releases GPT-5 with improved reasoning",
             "summary": "オープンエーアイは、複数ステップの推論とコーディングタスクで大幅な改善を遂げた最新モデルを発表しました。従来比で推論精度が40%向上しており、医療診断や法律文書の解析にも活用できるとしています。",
             "source": "TechCrunch", "importance": 3},
        ],
        "business": [
            {"title_ja": "アンソロピック、評価額9000億ドルで新たな資金調達へ",
             "title_en": "Anthropic raises $50B at $900B valuation",
             "summary": "エーアイ安全企業のアンソロピックが、評価額9000億ドルで新たな資金調達ラウンドを検討していることが明らかになりました。",
             "source": "VentureBeat", "importance": 2},
        ],
    }
    success = generate_podcast(test_data, date)
    print("✅ Done" if success else "❌ Failed")
