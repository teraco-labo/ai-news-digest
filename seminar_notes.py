#!/usr/bin/env python3
"""
セミナー録画 → 文字起こし・議事録・タイムスタンプ付き要約 → そのまま AI に質問できる状態にする。

## なぜ作ったか

NotebookLM の YouTube ソースは「一般公開されていて、字幕があり、投稿から
72時間以上経っている動画」しか読み込めない。中身を自前で文字起こしする機能は無く、
YouTube が返す字幕データをそのまま取り込んでいるだけなので、

  - 限定公開（リンクを知っている人だけ）のセミナー録画
  - 字幕がまだ生成されていない、または字幕を切っている動画

は URL を貼っても弾かれる。社内セミナーの録画はほぼ全部これに当たる。

回避策は昔から決まっていて「文字起こしをテキストとして渡す」。
このスクリプトはその文字起こしを取ってくるところから、議事録・
タイムスタンプ付き要約・ネクストアクションを書くところまでをまとめてやる。

## 使い方

    # 録画から一式（文字起こし＋議事録）を作る
    python3 seminar_notes.py https://youtu.be/XXXXXXXXXXX --title "第3回 社内勉強会"
    python3 seminar_notes.py ./recording.m4a --title "Zoom録画（2026-08-27）"

    # Zoom のクラウド録画（Zoom自身の文字起こしを使うので追加費用ゼロ・話者名つき）
    python3 seminar_notes.py --zoom-list                 # どの録画か一覧で選ぶ
    python3 seminar_notes.py "<会議ID>" --title "第3回 社内勉強会"

    # 文字起こしが既にあるなら、それを渡すのが一番速い
    # （YouTubeの「文字起こしを表示」からコピーしたもの、Zoomの字幕ファイルなど）
    python3 seminar_notes.py ./transcript.txt --title "第3回 社内勉強会"

    # 限定公開でログインが要る場合はブラウザの Cookie を借りる
    python3 seminar_notes.py <URL> --cookies-from-browser chrome

    # できたものに質問する（NotebookLM の代わり）
    python3 seminar_notes.py --ask "MCP版とAPI版の違いは？"
    python3 seminar_notes.py --ask "料金の話はどこ？" --slug rakumubi-benkyokai

    # 作ったセミナーの一覧
    python3 seminar_notes.py --list

## 出力（seminars/<スラッグ>/ 以下）

    transcript.txt   タイムスタンプ付きの文字起こし。NotebookLM に
                     「テキストを貼り付け」で渡せばソースとして使える
    notes.md         議事録・タイムスタンプ付き要約・ネクストアクション・
                     参加者への配布メール文面
    meta.json        元URL・取得方法・長さなどの記録

セミナーの中身は社外に出せないことが多いので seminars/ は .gitignore 済み。

## 文字起こしの取り方（上から順に試す）

    0. Zoom のクラウド録画から、Zoom 自身が作った文字起こしを取得（話者名つき・無料）
    1. YouTube の字幕を API で取得（限定公開でも字幕さえあれば通る・無料）
    2. yt-dlp で自動生成字幕を取得（1が塞がれたとき用）
    3. 音声をダウンロードして Gemini で文字起こし（字幕が無い動画・ローカル音声）

0 は Zoom の3点セット（ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET）が
.env にあるときだけ動く。3 だけは API キー（GEMINI_API_KEY / 予備で OPENAI_API_KEY）が要る。

Zoom を最優先にしているのは、話者名が入るぶん議事録の質が上がるのと、
YouTube にアップし直す手間も音声から起こす費用もかからないため。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:  # .env に置いた鍵（Zoom・Gemini 等）を読む。無くても動く
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 出力先。既定はこのフォルダの seminars/（.gitignore 済み）。
# セミナーの中身は社外に出せないことが多いので、リポジトリの外に置きたい場合は
# .env に SEMINAR_NOTES_DIR=/Users/…/セミナー議事録 のように書けばそちらに出る。
SEMINAR_DIR = Path(
    os.environ.get("SEMINAR_NOTES_DIR")
    or (Path(__file__).resolve().parent / "seminars")
).expanduser()

# 日本語のセミナーを想定。無ければ英語、それも無ければ動画にある任意の字幕。
DEFAULT_LANGS = ["ja", "ja-JP", "ja-orig", "en", "en-US"]

CLI_MODEL = "opus"
API_MODEL = "claude-opus-5"
GEMINI_MODEL = "gemini-flash-latest"

# ローカル文字起こしのモデル。turbo は日本語の精度と速さのつり合いが一番よい。
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "turbo")


# ---------------------------------------------------------------------------
# 小道具
# ---------------------------------------------------------------------------

def _video_id(url: str) -> Optional[str]:
    """YouTube の各種URL形式から動画IDを取り出す。"""
    patterns = [
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtube\.com/(?:embed|shorts|live|v)/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    # ID だけを直接渡された場合
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()):
        return url.strip()
    return None


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _slugify(text: str) -> str:
    """タイトルをフォルダ名として使える形にする。

    日本語はそのまま残す（フォルダ名として問題ない）。記号・空白だけを整理し、
    何も残らなかった場合は呼び出し側が日付ベースの名前で補う。
    """
    s = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:60].lower()


def _hhmmss(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _run(cmd: List[str], timeout: int = 1800) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"コマンドが見つかりません: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "タイムアウトしました"


# ---------------------------------------------------------------------------
# 0. Zoom のクラウド録画から取る
#
# Zoom は録画と一緒に文字起こし（VTT）を自分で作っている。これが取れれば
# YouTube にアップし直す手間も、音声から起こし直す費用もかからない。
# しかも Zoom の文字起こしには**話者名が入る**ので、YouTube の自動字幕より
# 議事録の質が上がる（誰の発言かが分かるとネクストアクションの担当が埋まる）。
#
# 使うのは Zoom の「サーバー間 OAuth（Server-to-Server OAuth）」アプリ。
# 3点セット（アカウントID / クライアントID / クライアントシークレット）を
# .env に置く。無ければこの経路は静かに飛ばして、従来どおりの案内を出す。
# ---------------------------------------------------------------------------

ZOOM_API = "https://api.zoom.us/v2"

# Zoom の録画一覧は 1回の問い合わせで最大1か月ぶんしか返らないため、
# それより長い期間はこの幅で区切って繰り返し取りに行く。
ZOOM_WINDOW_DAYS = 30


def _zoom_creds() -> Optional[Tuple[str, str, str]]:
    """3点セットが揃っているときだけ返す。1つでも欠けたら使わない。"""
    account = os.environ.get("ZOOM_ACCOUNT_ID", "").strip()
    client = os.environ.get("ZOOM_CLIENT_ID", "").strip()
    secret = os.environ.get("ZOOM_CLIENT_SECRET", "").strip()
    if account and client and secret:
        return account, client, secret
    return None


def _zoom_setup_hint() -> None:
    print("   Zoom の設定がまだのようです。次のどちらかで進められます:")
    print("   (A) 設定なしで今すぐ: Zoom のウェブ画面で録画を開き、"
          "「音声文字起こし」の VTT ファイルをダウンロードして、そのファイルを渡す")
    print("   (B) 自動化する: Zoom の「サーバー間 OAuth」アプリを作り、"
          ".env に ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / ZOOM_CLIENT_SECRET を書く"
          "（→ SEMINAR_NOTES.md）")


def _zoom_token(verbose: bool = True) -> Optional[str]:
    creds = _zoom_creds()
    if not creds:
        return None
    account, client, secret = creds
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.post(
            "https://zoom.us/oauth/token",
            params={"grant_type": "account_credentials", "account_id": account},
            auth=(client, secret),
            timeout=60,
        )
        r.raise_for_status()
        token = r.json().get("access_token")
    except Exception as e:
        if verbose:
            print(f"   ⚠️  Zoom への接続に失敗しました: {e}")
            print("      .env の ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID / "
                  "ZOOM_CLIENT_SECRET を確認してください")
        return None
    return token or None


def _zoom_get(path: str, token: str, params: Optional[Dict] = None,
              verbose: bool = True) -> Optional[Dict]:
    try:
        import requests
        r = requests.get(f"{ZOOM_API}{path}",
                         headers={"Authorization": f"Bearer {token}"},
                         params=params or {}, timeout=120)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if verbose:
            print(f"   ⚠️  Zoom からの取得に失敗しました: {e}")
        return None


def _is_zoom(source: str) -> bool:
    return bool(re.search(r"(^|//|\.)zoom\.(us|com)/", source or ""))


def _zoom_key(source: str) -> Optional[str]:
    """URL や入力から会議のIDを取り出す。共有リンクからは取れない（Noneを返す）。"""
    if not source:
        return None
    from urllib.parse import unquote
    m = re.search(r"[?&]meeting_id=([^&]+)", source)
    if m:
        return unquote(m.group(1))
    m = re.search(r"/j/(\d{9,12})", source)
    if m:
        return m.group(1)
    plain = re.sub(r"[\s-]", "", source.strip())
    if plain.isdigit() and 9 <= len(plain) <= 12:
        return plain
    return None


def _zoom_path_key(key: str) -> str:
    """会議IDをURLに埋め込める形にする。

    数字だけの会議番号はそのまま。UUID は base64 なので `/` や `+` `=` を含み、
    そのまま URL に入れるとパスが割れて 404 になる。Zoom は二重エンコードした
    UUID を受け付けるので、数字以外はすべて二重エンコードする。
    """
    from urllib.parse import quote
    if key.isdigit():
        return key
    return quote(quote(key, safe=""), safe="")


def _zoom_list_meetings(token: str, days: int, verbose: bool = True) -> List[Dict]:
    """直近 days 日ぶんのクラウド録画を新しい順に返す。"""
    from datetime import date, timedelta
    meetings: List[Dict] = []
    end = date.today()
    remaining = max(days, 1)
    while remaining > 0:
        span = min(remaining, ZOOM_WINDOW_DAYS)
        start = end - timedelta(days=span)
        page_token = ""
        while True:
            params = {"from": start.isoformat(), "to": end.isoformat(), "page_size": 100}
            if page_token:
                params["next_page_token"] = page_token
            data = _zoom_get("/users/me/recordings", token, params, verbose)
            if not data:
                break
            meetings.extend(data.get("meetings", []))
            page_token = data.get("next_page_token") or ""
            if not page_token:
                break
        end = start - timedelta(days=1)
        remaining -= span + 1

    # 期間を区切って何度も問い合わせるので、同じ会議が二度入ることがある
    unique: Dict[str, Dict] = {}
    for m in meetings:
        unique.setdefault(str(m.get("uuid") or m.get("id")), m)
    result = list(unique.values())
    result.sort(key=lambda m: str(m.get("start_time", "")), reverse=True)
    return result


def _zoom_files(meeting: Dict) -> Tuple[Optional[Dict], Optional[Dict]]:
    """(文字起こしファイル, 音声ファイル) を選ぶ。文字起こしが最優先。"""
    transcript = None
    audio = None
    for f in meeting.get("recording_files", []):
        ftype = str(f.get("file_type", "")).upper()
        if ftype in ("TRANSCRIPT", "CC") and transcript is None:
            transcript = f
        elif ftype == "M4A" and audio is None:
            audio = f
    if transcript is None:
        # TRANSCRIPT が無ければ MP4 でも音声だけ取り出せる
        for f in meeting.get("recording_files", []):
            if str(f.get("file_type", "")).upper() == "MP4" and audio is None:
                audio = f
    return transcript, audio


def _zoom_download(file_obj: Dict, token: str, dest: Path, verbose: bool) -> Optional[Path]:
    url = file_obj.get("download_url")
    if not url:
        return None
    ext = str(file_obj.get("file_extension") or file_obj.get("file_type") or "dat").lower()
    out = dest / f"zoom.{ext}"
    try:
        import requests
        with requests.get(url, headers={"Authorization": f"Bearer {token}"},
                          stream=True, timeout=1800) as r:
            r.raise_for_status()
            with out.open("wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
    except Exception as e:
        if verbose:
            print(f"   ⚠️  Zoom からのダウンロードに失敗しました: {e}")
        return None
    return out


def _zoom_find_meeting(source: str, token: str, days: int, verbose: bool,
                       explicit: bool = False) -> Optional[Dict]:
    """会議IDが分かればそれで取り、共有リンクしか無ければ一覧から突き合わせる。"""
    key = _zoom_key(source)
    if not key and explicit and not _is_url(source):
        # `--zoom` で渡された UUID（`abc/def==` のような数字でない形）はそのまま使う
        key = source.strip()
    if key:
        data = _zoom_get(f"/meetings/{_zoom_path_key(key)}/recordings", token,
                         verbose=verbose)
        if data:
            return data
        if verbose:
            print(f"   その会議ID（{key}）の録画が見つかりませんでした。一覧から探します…")

    if verbose:
        print(f"   直近 {days} 日ぶんの録画から探しています…")
    meetings = _zoom_list_meetings(token, days, verbose)
    if _is_zoom(source):
        # 共有リンク（/rec/share/...）は会議IDを含まないので、share_url で突き合わせる
        wanted = source.split("?")[0].rstrip("/")
        for m in meetings:
            share = str(m.get("share_url", "")).split("?")[0].rstrip("/")
            if share and (share == wanted or wanted.startswith(share)):
                return m
    if verbose and meetings:
        print("   一致する録画が見つかりませんでした。"
              "`--zoom-list` で一覧を出して、会議IDを指定してください")
    return None


def _from_zoom(source: str, days: int, verbose: bool = True,
               explicit: bool = False, cloud_first: bool = False) -> Optional[Tuple[str, str]]:
    if verbose:
        print("① Zoom のクラウド録画を取得します…")
    token = _zoom_token(verbose)
    if not token:
        if verbose and not _zoom_creds():
            _zoom_setup_hint()
        return None

    meeting = _zoom_find_meeting(source, token, days, verbose, explicit)
    if not meeting:
        return None

    topic = str(meeting.get("topic", "")).strip()
    if verbose and topic:
        print(f"   録画が見つかりました: {topic}（{str(meeting.get('start_time',''))[:16]}）")

    transcript_file, audio_file = _zoom_files(meeting)

    with tempfile.TemporaryDirectory() as tmp:
        if transcript_file:
            if verbose:
                print("   Zoom が作った文字起こしを使います（話者名つき・追加費用なし）")
            path = _zoom_download(transcript_file, token, Path(tmp), verbose)
            if path:
                try:
                    segments = _parse_vtt(path)
                except Exception as e:
                    if verbose:
                        print(f"   ⚠️  文字起こしを読めませんでした: {e}")
                    segments = []
                if segments:
                    return _format_segments(segments), "Zoomの文字起こし（クラウド録画）"

        if audio_file:
            if verbose:
                print("   Zoom側の文字起こしが無いので、録画の音声から起こします")
            path = _zoom_download(audio_file, token, Path(tmp), verbose)
            if path:
                text = _transcribe(path, cloud_first, verbose)
                if text:
                    return text, "Zoom録画の音声からの文字起こし"

    if verbose:
        print("   ⚠️  この録画から使える文字起こしも音声も取れませんでした")
    return None


def zoom_list(days: int = 30) -> int:
    """クラウド録画の一覧を出す。持ち主に「どれ？」と聞くための材料。"""
    token = _zoom_token()
    if not token:
        if not _zoom_creds():
            _zoom_setup_hint()
        return 1

    meetings = _zoom_list_meetings(token, days)
    if not meetings:
        print(f"直近 {days} 日ぶんのクラウド録画はありませんでした。")
        return 0

    print(f"📼 直近 {days} 日ぶんのクラウド録画（新しい順）\n")
    for m in meetings:
        transcript_file, _ = _zoom_files(m)
        mark = "文字起こしあり" if transcript_file else "文字起こしなし（音声から起こします）"
        minutes = m.get("duration") or 0
        print(f"  {str(m.get('start_time',''))[:16].replace('T',' ')}  "
              f"{str(m.get('topic','（無題）')).strip()}")
        print(f"     {minutes}分 / {mark} / 会議ID: {m.get('uuid') or m.get('id')}")
    print("\n議事録にするとき:")
    print('   python3 seminar_notes.py --zoom "<会議ID>" --title "<セミナー名>"')
    return 0


# ---------------------------------------------------------------------------
# 1. YouTube の字幕を API で取る
# ---------------------------------------------------------------------------

def _from_transcript_api(vid: str, langs: List[str], verbose: bool) -> Optional[List[Dict]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        if verbose:
            print("   youtube-transcript-api が未インストールなのでスキップします")
        return None

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(vid, languages=langs)
    except Exception as e:
        if verbose:
            print(f"   字幕APIでは取れませんでした: {type(e).__name__}")
        return None

    # ライブラリのバージョンによって戻り値の形が違うので両対応にする
    try:
        raw = fetched.to_raw_data()
    except AttributeError:
        raw = [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched]

    segments = [
        {"start": float(r.get("start", 0)), "text": str(r.get("text", "")).strip()}
        for r in raw
        if str(r.get("text", "")).strip()
    ]
    return segments or None


# ---------------------------------------------------------------------------
# 2. yt-dlp で自動生成字幕を取る
# ---------------------------------------------------------------------------

def _ytdlp_base(cookies: Optional[str], cookies_from_browser: Optional[str]) -> Optional[List[str]]:
    exe = shutil.which("yt-dlp")
    if not exe:
        return None
    cmd = [exe, "--no-warnings", "--no-progress"]
    if cookies:
        cmd += ["--cookies", cookies]
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    return cmd


def _parse_json3(path: Path) -> List[Dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs).strip()
        if not text or text == "\n":
            continue
        segments.append({"start": float(ev.get("tStartMs", 0)) / 1000.0, "text": text})
    return segments


def _parse_vtt(path: Path) -> List[Dict]:
    """VTT を読む。自動生成字幕は同じ行が転がり続けるので重複を落とす。"""
    # 「0:01:23.456」だけでなく「01:23.456」（時間の桁が無い形）も受ける。
    # whisper のローカル出力は1時間未満だと時の桁を省く。
    time_re = re.compile(r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{3})\s+-->\s+")
    segments: List[Dict] = []
    start = None
    buf: List[str] = []

    def flush():
        nonlocal start, buf
        if start is None:
            buf = []
            return
        text = " ".join(buf).strip()
        text = re.sub(r"<[^>]+>", "", text)          # <c> や <00:00:01.000> を除去
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text and (not segments or segments[-1]["text"] != text):
            segments.append({"start": start, "text": text})
        start, buf = None, []

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = time_re.search(line)
        if m:
            flush()
            parts = m.group(1).split(":")
            if len(parts) == 3:
                h, mi, rest = parts
            else:
                h, (mi, rest) = "0", parts
            sec = float(rest.replace(",", "."))
            start = int(h) * 3600 + int(mi) * 60 + sec
        elif (line.strip() and not line.strip().isdigit()
              and not line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))):
            # Zoom の VTT は字幕ごとに通し番号の行が入る。拾うと発言に数字が混ざる
            buf.append(line.strip())
    flush()

    # 自動生成字幕は前の行を含んだまま次の行が出るので、包含関係の重複を畳む
    deduped: List[Dict] = []
    for seg in segments:
        if deduped and seg["text"].startswith(deduped[-1]["text"]):
            deduped[-1] = seg
        else:
            deduped.append(seg)
    return deduped


def _from_ytdlp_subs(url: str, langs: List[str], cookies: Optional[str],
                     browser: Optional[str], verbose: bool) -> Optional[List[Dict]]:
    base = _ytdlp_base(cookies, browser)
    if not base:
        if verbose:
            print("   yt-dlp が未インストールなのでスキップします")
        return None

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sub"
        for fmt, parser in (("json3", _parse_json3), ("vtt", _parse_vtt)):
            code, _, err = _run(base + [
                "--skip-download", "--write-subs", "--write-auto-subs",
                "--sub-langs", ",".join(langs) + ",-live_chat",
                "--sub-format", fmt,
                "-o", str(out), url,
            ], timeout=300)
            files = sorted(Path(tmp).glob(f"*.{fmt}"))
            if files:
                # 希望言語の順に優先して選ぶ
                pick = files[0]
                for lang in langs:
                    hit = [f for f in files if f".{lang}." in f.name]
                    if hit:
                        pick = hit[0]
                        break
                try:
                    segments = parser(pick)
                except Exception as e:
                    if verbose:
                        print(f"   字幕ファイルを読めませんでした（{fmt}）: {e}")
                    continue
                if segments:
                    return segments
            elif verbose and code != 0:
                print(f"   yt-dlp が字幕を取れませんでした（{fmt}）: {err.strip()[:200]}")
    return None


# ---------------------------------------------------------------------------
# 3. 音声を落として文字起こしする
# ---------------------------------------------------------------------------

def _download_audio(url: str, dest: Path, cookies: Optional[str],
                    browser: Optional[str], verbose: bool) -> Optional[Path]:
    base = _ytdlp_base(cookies, browser)
    if not base:
        print("   ⚠️  yt-dlp が必要です（pip install yt-dlp）")
        return None
    if verbose:
        print("   音声をダウンロードしています…")
    out = dest / "audio.%(ext)s"
    code, _, err = _run(base + ["-f", "bestaudio/best", "-o", str(out), url], timeout=3600)
    if code != 0:
        print(f"   ⚠️  音声のダウンロードに失敗しました: {err.strip()[:300]}")
        return None
    files = [p for p in dest.iterdir() if p.stem == "audio"]
    return files[0] if files else None


_TRANSCRIBE_PROMPT = """この音声はセミナー・勉強会の録画です。話されている内容を一字一句、日本語で文字起こししてください。

ルール:
- 1行につき「[h:mm:ss] 発言内容」の形式で出力する（先頭は0:00から）
- おおよそ15〜30秒ごとに1行に区切る
- 話者が変わったところは行を分ける。誰が話しているか分かる場合は「[0:12:34] 講師: …」のように名前や役割を添える
- 要約・省略はしない。言い直しやフィラー（えー、あの）は適度に整えてよいが、内容は落とさない
- 文字起こし以外の前置きや説明は一切出力しない
"""


def _transcribe_whisper(path: Path, verbose: bool) -> Optional[str]:
    """Mac の中だけで文字起こしする（openai-whisper）。

    鍵も費用も要らず、**音声が Mac から外に出ない**。セミナーの中身は社外に
    出せないことが多いので、これを既定にしている。代償は時間で、録画の
    再生時間とだいたい同じくらいかかる（1時間の録画で1時間弱）。
    急ぐときは GEMINI_API_KEY を入れて --cloud-transcribe を使う。
    """
    exe = shutil.which("whisper")
    if not exe:
        if verbose:
            print("   ローカルの whisper が入っていないのでスキップします"
                  "（brew install openai-whisper で入る）")
        return None

    if verbose:
        minutes = _media_minutes(path)
        est = f"およそ{max(int(minutes * 0.9), 1)}分" if minutes else "しばらく"
        print(f"   Mac の中で文字起こしします（費用ゼロ・音声は外に出ません / {est}かかります）")

    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = _run([
            exe, str(path),
            "--model", WHISPER_MODEL,
            "--language", "ja",
            "--output_format", "vtt",
            "--output_dir", tmp,
            "--device", "cpu",     # MPS(GPU) は長時間の録画で落ちることがある
            "--verbose", "False",
        ], timeout=6 * 3600)
        if code != 0:
            print(f"   ⚠️  ローカルの文字起こしに失敗しました: {err.strip()[-300:]}")
            return None
        vtts = sorted(Path(tmp).glob("*.vtt"))
        if not vtts:
            print("   ⚠️  文字起こしの結果が見つかりませんでした")
            return None
        segments = _parse_vtt(vtts[0])
    return _format_segments(segments) if segments else None


def _media_minutes(path: Path) -> Optional[float]:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    code, out, _ = _run([exe, "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(path)], timeout=120)
    try:
        return float(out.strip()) / 60.0 if code == 0 else None
    except ValueError:
        return None


def _transcribe_gemini(path: Path, verbose: bool) -> Optional[str]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from google import genai as google_genai
        from google.genai import types as genai_types
    except ImportError:
        if verbose:
            print("   google-genai が未インストールなのでスキップします")
        return None

    if verbose:
        print(f"   Gemini で文字起こし中…（{path.stat().st_size / 1_000_000:.0f} MB）")
    try:
        client = google_genai.Client(api_key=api_key)
        uploaded = client.files.upload(file=str(path))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[uploaded, _TRANSCRIBE_PROMPT],
            config=genai_types.GenerateContentConfig(temperature=0.0, max_output_tokens=65536),
        )
        text = (response.text or "").strip()
    except Exception as e:
        print(f"   ⚠️  Gemini での文字起こしに失敗しました: {e}")
        return None
    return text or None


def _transcribe_openai(path: Path, verbose: bool) -> Optional[str]:
    """予備。Whisper API は1ファイル25MBまでなので長時間の録画には向かない。"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    size_mb = path.stat().st_size / 1_000_000
    if size_mb > 24:
        print(f"   ⚠️  音声が {size_mb:.0f} MB あり Whisper API の上限（25MB）を超えます。"
              "GEMINI_API_KEY を設定するか、音声を分割してください")
        return None
    try:
        import requests
    except ImportError:
        return None

    if verbose:
        print("   OpenAI で文字起こし中…")
    try:
        with path.open("rb") as f:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (path.name, f)},
                data={"model": "whisper-1", "response_format": "verbose_json",
                      "language": "ja"},
                timeout=1800,
            )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"   ⚠️  OpenAI での文字起こしに失敗しました: {e}")
        return None

    lines = [f"[{_hhmmss(s.get('start', 0))}] {str(s.get('text', '')).strip()}"
             for s in data.get("segments", []) if str(s.get("text", "")).strip()]
    return "\n".join(lines) if lines else (data.get("text") or None)


def _transcribe(path: Path, cloud_first: bool, verbose: bool) -> Optional[str]:
    """文字起こしの担当を選ぶ。

    既定は Mac の中の whisper。鍵が要らず、費用もかからず、なにより
    **セミナーの音声を外に出さない**。社外に出せない録画が多いので既定にしている。
    速さが要るときだけ --cloud-transcribe でクラウド（Gemini）を先に使う。
    """
    if cloud_first:
        return (_transcribe_gemini(path, verbose)
                or _transcribe_openai(path, verbose)
                or _transcribe_whisper(path, verbose))
    return (_transcribe_whisper(path, verbose)
            or _transcribe_gemini(path, verbose)
            or _transcribe_openai(path, verbose))


def _from_audio(source: str, cookies: Optional[str], browser: Optional[str],
                verbose: bool, cloud_first: bool = False) -> Optional[str]:
    """URL でも手元のファイルでも、音声から文字起こし済みテキストを返す。"""
    if not _is_url(source):
        path = Path(source).expanduser().resolve()
        if not path.exists():
            print(f"   ⚠️  ファイルが見つかりません: {path}")
            return None
        if path.suffix.lower() in TEXT_SUFFIXES:
            # テキストは既に fetch_transcript で扱っている。ここに来たなら中身が空。
            print(f"   ⚠️  文字起こしファイルが空か、読み取れませんでした: {path}")
            return None
        return _transcribe(path, cloud_first, verbose)

    with tempfile.TemporaryDirectory() as tmp:
        path = _download_audio(source, Path(tmp), cookies, browser, verbose)
        if not path:
            return None
        return _transcribe(path, cloud_first, verbose)


# ---------------------------------------------------------------------------
# 文字起こしの取得（全体）
# ---------------------------------------------------------------------------

TEXT_SUFFIXES = {".txt", ".md", ".vtt", ".srt", ".json3", ".json"}


def _from_text_file(path: Path, verbose: bool) -> Optional[str]:
    """すでに手元にある文字起こしを読み込む。

    YouTube の「文字起こしを表示」からコピーしたテキスト、Zoom や Teams が
    書き出した字幕ファイルなど、文字起こしが既にある場合はそれが一番速い。
    録画を取りに行けない環境でも、これなら議事録まで進められる。
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".vtt":
            return _format_segments(_parse_vtt(path))
        if suffix in (".json3", ".json"):
            return _format_segments(_parse_json3(path))
        if suffix == ".srt":
            return _format_segments(_parse_srt(path))
        return path.read_text(encoding="utf-8").strip() or None
    except Exception as e:
        if verbose:
            print(f"   ⚠️  文字起こしファイルを読めませんでした: {e}")
        return None


def _parse_srt(path: Path) -> List[Dict]:
    time_re = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s+-->")
    segments: List[Dict] = []
    start: Optional[float] = None
    buf: List[str] = []

    def flush():
        nonlocal start, buf
        text = " ".join(buf).strip()
        if start is not None and text:
            segments.append({"start": start, "text": text})
        start, buf = None, []

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = time_re.search(line)
        if m:
            flush()
            h, mi, sec, ms = (int(g) for g in m.groups())
            start = h * 3600 + mi * 60 + sec + ms / 1000.0
        elif line.strip() and not line.strip().isdigit():
            buf.append(line.strip())
    flush()
    return segments


def fetch_transcript(source: str, langs: List[str], cookies: Optional[str],
                     browser: Optional[str], force_audio: bool,
                     zoom: bool = False, zoom_days: int = 30,
                     cloud_first: bool = False,
                     verbose: bool = True) -> Optional[Tuple[str, str]]:
    """(文字起こしテキスト, 取得方法) を返す。取れなければ None。"""
    is_zoom_source = zoom or _is_zoom(source)
    if (is_zoom_source or _zoom_key(source)) and _zoom_creds():
        got = _from_zoom(source, zoom_days, verbose, explicit=zoom,
                         cloud_first=cloud_first)
        if got:
            return got
        if is_zoom_source:
            # Zoom の録画だと分かっている入力を、ファイル名や動画URLとして
            # 扱い直しても混乱するだけなので、ここで止める
            return None
    elif is_zoom_source:
        if verbose:
            print("① Zoom のクラウド録画を取得します…")
            _zoom_setup_hint()
        return None

    if not _is_url(source):
        path = Path(source).expanduser().resolve()
        if path.suffix.lower() in TEXT_SUFFIXES and path.exists():
            if verbose:
                print("① 手元の文字起こしを読み込みます…")
            text = _from_text_file(path, verbose)
            if text:
                return text, "手元の文字起こしファイル"

    if _is_url(source) and not force_audio:
        vid = _video_id(source)
        if vid:
            if verbose:
                print("① YouTube の字幕を取得します…")
            segments = _from_transcript_api(vid, langs, verbose)
            if segments:
                return _format_segments(segments), "YouTubeの字幕（字幕API）"

            if verbose:
                print("② yt-dlp で自動生成字幕を取得します…")
            segments = _from_ytdlp_subs(source, langs, cookies, browser, verbose)
            if segments:
                return _format_segments(segments), "YouTubeの自動生成字幕（yt-dlp）"

    if verbose:
        print("③ 音声から文字起こしします…")
    text = _from_audio(source, cookies, browser, verbose, cloud_first)
    if text:
        method = "クラウドでの文字起こし" if cloud_first else "Macの中での文字起こし（whisper）"
        return text, method
    return None


# 「藤崎 秀一: こんにちは」の頭の部分。数字を含む語は時刻（10:30）なので話者とみなさない。
_SPEAKER_RE = re.compile(r"^([^\d:：]{1,24})[:：]\s")


def _speaker_of(text: str) -> Optional[str]:
    m = _SPEAKER_RE.match(text.strip())
    return m.group(1).strip() if m else None


def _format_segments(segments: List[Dict]) -> str:
    """バラバラの字幕を、読める粒度（およそ30秒）にまとめる。

    話者名が入っている文字起こし（Zoom など）では、話者が変わったところで必ず
    行を分ける。誰の発言かが分かると、議事録のネクストアクションに担当者が入る。
    """
    lines: List[str] = []
    chunk_start: Optional[float] = None
    chunk_speaker: Optional[str] = None
    buf: List[str] = []

    def flush():
        nonlocal chunk_start, chunk_speaker, buf
        if buf and chunk_start is not None:
            lines.append(f"[{_hhmmss(chunk_start)}] {' '.join(buf)}")
        chunk_start, chunk_speaker, buf = None, None, []

    for seg in segments:
        text = seg["text"].replace("\n", " ").strip()
        speaker = _speaker_of(text)
        if chunk_start is not None and speaker and speaker != chunk_speaker:
            flush()
        if chunk_start is None:
            chunk_start = seg["start"]
            chunk_speaker = speaker
        buf.append(text)
        if seg["start"] - chunk_start >= 30:
            flush()
    flush()
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude を呼ぶ（サブスク枠の CLI を優先し、API を予備にする）
# ---------------------------------------------------------------------------

def ask_claude(system: str, user: str, max_tokens: int = 16000,
               purpose: str = "セミナー議事録", verbose: bool = True) -> Optional[str]:
    text = _claude_via_cli(system, user, verbose)
    if text:
        return text
    return _claude_via_api(system, user, max_tokens, purpose, verbose)


def _claude_via_cli(system: str, user: str, verbose: bool) -> Optional[str]:
    exe = shutil.which("claude")
    if not exe:
        return None

    # Claude Code は ANTHROPIC_API_KEY を OAuth トークンより優先してしまう。
    # 失効した API キーが環境に残っていると 401 で落ちるので外して渡す。
    env = os.environ.copy()
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        for k in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            env.pop(k, None)

    try:
        proc = subprocess.run(
            [exe, "-p", "--output-format", "json", "--model", CLI_MODEL],
            input=system + "\n\n---\n\n" + user,
            capture_output=True, text=True, timeout=1800, env=env,
        )
    except Exception as e:
        if verbose:
            print(f"   ⚠️  Claude Code CLI の実行に失敗しました: {e}")
        return None

    if proc.returncode != 0:
        if verbose:
            print(f"   ⚠️  Claude Code CLI がエラーを返しました（exit {proc.returncode}）")
        return None

    try:
        wrapper = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.stdout.strip() or None
    if wrapper.get("is_error"):
        if verbose:
            print(f"   ⚠️  Claude Code CLI が失敗を報告しました: {str(wrapper.get('result'))[:200]}")
        return None
    return str(wrapper.get("result", "")).strip() or None


def _claude_via_api(system: str, user: str, max_tokens: int, purpose: str,
                    verbose: bool) -> Optional[str]:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        if verbose:
            print("   ⚠️  Claude Code CLI も ANTHROPIC_API_KEY も使えません")
        return None
    try:
        import anthropic
    except ImportError:
        if verbose:
            print("   ⚠️  anthropic パッケージが見つかりません（pip install anthropic）")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=API_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = next(b.text for b in response.content if b.type == "text")
    except Exception as e:
        print(f"   ⚠️  Claude API の呼び出しに失敗しました: {e}")
        return None

    try:
        import api_cost_calculator
        api_cost_calculator.record_anthropic_usage(
            model=API_MODEL,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            purpose=purpose,
        )
    except Exception:
        pass
    return text.strip()


# ---------------------------------------------------------------------------
# 議事録を書く
# ---------------------------------------------------------------------------

NOTES_SYSTEM = """あなたは日本のIT企業で議事録を担当する編集者です。
セミナー・勉強会の録画の文字起こしを渡されるので、参加者と欠席者の両方が読んで
すぐ動ける資料にまとめます。

## 守ること

- 文字起こしに出てこないことは書かない。推測で補わない。
  聞き取れていない箇所は「（聞き取り不能）」と書く。
- タイムスタンプは文字起こしの [h:mm:ss] をそのまま使う。作らない。
- 文体は敬体（です・ます）で統一する。
- 固有名詞（製品名・ツール名・会社名・人名）は正確に。自信が無い表記は
  「〜（表記要確認）」と添える。
- ネクストアクションは「誰が・何を・いつまでに」が分かる形で書く。
  録画の中で担当や期限が決まっていない場合は「担当未定」「期限未定」と正直に書く。

## 出力形式

Markdown で、下の見出し構成のとおりに出力する。前置き・あとがき・
「以下にまとめました」のような一言は書かない。見出しから始める。

## タイムスタンプ付き要約

「前半｜セットアップ」のように話の区切りで小見出し（###）を立て、その下に
「0:00　開始前」「1:56　あいさつ・参加確認」のように1行ずつ、そのまま並べる。
表にもコードブロック（```）にもしないこと。メールに貼って読むものなので、
飾りが付くとかえって読みにくい。項目名は10〜20文字程度の名詞句にする。
行数は文字起こしにあるタイムスタンプの数に合わせる。数を揃えるために
存在しない時刻を作らないこと。逆に、行数が少ないことへの言い訳も書かないこと。

## 議事録

話し合われた内容を項目立ててまとめる。決まったこと・出た質問と回答・
保留になったことが分かるように書く。

## ツールの使い方

**この回でツールやサービスの操作説明があった場合だけ、この見出しを作る。**
雑談や報告だけの回では、この見出しごと省略してよい（無いものを埋めない）。

あとから動画を見返さずに手を動かせる粒度で書く。読む人は録画を見ていない、
あるいは見たが手順を覚えていない人。具体的には:

- セットアップ・導入は番号付きの手順にする。各手順の末尾に、動画の該当箇所の
  タイムスタンプを `（8:25）` のように添える。詰まったらそこへ飛べるようにするため
- 画面のどこを押すか、どのメニューか、何を入力するかを、録画で言われたとおりに書く
- 設定値・ファイル名・コマンド・URL・プラン名・金額は、**言われたまま正確に**書き写す。
  丸めない、言い換えない。ここを要約すると資料として使えなくなる
- 「ここでよく間違える」「ここは飛ばしていい」といった注意が出てきたら、
  該当手順の下に「⚠️」付きで残す
- 複数のやり方（例: 版・プラン・モードの違い）が説明されたなら、
  表で並べて違いが一目で分かるようにする
- 質疑で出た「こうしたい時はどうするか」も、操作の話ならここにまとめる

## 決まったこと

箇条書き。無ければ「特にありません」と書く。

## ネクストアクション

- [ ] 担当：やること（期限）

の形の箇条書き。

## 参加者への配布メール文面

そのままコピーして送れる本文。冒頭に一言、続けて議事録URL・録画URL・
タイムスタンプ付き要約の順に並べる。URL は差し込み用に
「（議事録URLをここに）」のようなプレースホルダにする（録画URLが分かっている場合はそれを使う）。
"""


def build_notes(title: str, transcript: str, source: str, focus: str = "",
                verbose: bool = True) -> Optional[str]:
    if verbose:
        print("④ 議事録・要約を作成しています…")
    focus_block = (
        f"# この回で特に厚く書いてほしいところ\n{focus}\n\n"
        "上の指示は、決められた見出し構成の中で反映してください。"
        "見出しを増やしたり順番を変えたりはしないこと。\n\n"
    ) if focus.strip() else ""
    user = (
        f"# セミナー名\n{title}\n\n"
        f"# 録画URL\n{source if _is_url(source) else '（ローカル録画）'}\n\n"
        f"{focus_block}"
        f"# 文字起こし\n\n{transcript}"
    )
    return ask_claude(NOTES_SYSTEM, user, max_tokens=16000,
                      purpose="セミナー議事録の作成", verbose=verbose)


# ---------------------------------------------------------------------------
# 質問する
# ---------------------------------------------------------------------------

QA_SYSTEM = """あなたはセミナーの内容に詳しいアシスタントです。
渡された文字起こしだけを根拠に、日本語で質問に答えます。

- 文字起こしに書かれていないことは「録画の中では触れられていません」と答える。
  推測で埋めない。
- 答えの根拠になった箇所のタイムスタンプを必ず [h:mm:ss] の形で示す。
- 長くならないように。要点を先に書き、必要なら補足を続ける。
"""


def answer(slug: str, question: str, verbose: bool = True) -> Optional[str]:
    d = SEMINAR_DIR / slug
    transcript_path = d / "transcript.txt"
    if not transcript_path.exists():
        print(f"⚠️  文字起こしが見つかりません: {transcript_path}")
        return None
    meta = {}
    if (d / "meta.json").exists():
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))

    user = (
        f"# セミナー名\n{meta.get('title', slug)}\n\n"
        f"# 文字起こし\n\n{transcript_path.read_text(encoding='utf-8')}\n\n"
        f"# 質問\n{question}"
    )
    return ask_claude(QA_SYSTEM, user, max_tokens=4000,
                      purpose="セミナー内容への質問", verbose=verbose)


# ---------------------------------------------------------------------------
# 保存 / 一覧
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 読むためのHTMLを書き出す
#
# notes.md はそのままでも読めるが、タイムスタンプが本文に埋もれて
# 「何分のところか」が拾いにくい。会が増えるほど読み返す機会が増えるので、
# 読む用の1枚を必ず添える。画面の明暗どちらでも読めるようにしてある。
# ---------------------------------------------------------------------------

_NOTES_STYLE = """
:root{--bg:#F6F7F9;--paper:#fff;--ink:#15181D;--ink2:#4A5260;--ink3:#79828F;
--line:#E2E6EB;--accent:#2F5D8A;--accent-bg:#E8EFF7;--ts:#8A6A2F;--ts-bg:#F5EEDF;color-scheme:light}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0F1216;--paper:#171B21;
--ink:#ECEFF3;--ink2:#B0B9C4;--ink3:#7F8896;--line:#282E37;--accent:#8FB4DC;--accent-bg:#182432;
--ts:#D6B072;--ts-bg:#2B2416;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Hiragino Sans","Yu Gothic",system-ui,sans-serif;line-height:1.9;font-size:15px}
main{max-width:820px;margin:0 auto;padding:32px 22px 80px}
h1{font-size:26px;line-height:1.4;margin:0 0 28px;padding-bottom:14px;border-bottom:2px solid var(--line)}
h2{font-size:20px;margin:40px 0 14px;padding:10px 14px;background:var(--accent-bg);
color:var(--accent);border-radius:3px}
h3{font-size:16px;margin:28px 0 10px;color:var(--ink);border-left:3px solid var(--accent);padding-left:10px}
h4{font-size:14px;margin:20px 0 8px;color:var(--ink2)}
p,li{color:var(--ink2)}
li{margin:5px 0}
strong{color:var(--ink)}
ul{padding-left:1.4em}
li.todo,li.done{list-style:none;margin-left:-1.4em;padding-left:1.9em;position:relative}
li.todo::before,li.done::before{position:absolute;left:0;top:.1em;width:1.15em;height:1.15em;
border:1.5px solid var(--ink3);border-radius:3px;content:"";display:block}
li.done::before{content:"✓";border-color:var(--accent);color:var(--accent);
text-align:center;line-height:1.05em;font-weight:700}
.ts{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:.86em;
color:var(--ts);background:var(--ts-bg);padding:1px 5px;border-radius:3px;white-space:nowrap}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:13.5px;
background:var(--paper);border:1px solid var(--line);border-radius:3px;overflow:hidden}
th,td{text-align:left;padding:10px 13px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--bg);color:var(--ink3);font-size:12.5px;white-space:nowrap}
tr:last-child td{border-bottom:0}
code{background:var(--bg);padding:1px 5px;border-radius:2px;font-size:.9em}
hr{border:0;border-top:1px solid var(--line);margin:32px 0}
.wrap-table{overflow-x:auto}
"""


def write_html(md_path: Path, out_path: Path) -> Optional[Path]:
    """議事録の Markdown を、そのまま読める1枚のHTMLにする。"""
    try:
        import markdown as _markdown
    except ImportError:
        return None  # 無くても議事録そのものは出来ているので黙って諦める

    import html as _html
    text = md_path.read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip() or md_path.stem
    try:
        body = _markdown.markdown(
            text, extensions=["tables", "sane_lists", "nl2br"], output_format="html5"
        )
    except Exception:
        return None

    # 「- [ ]」はMarkdownでは箇条書きになるだけなので、四角に見せる
    body = body.replace("<li>[ ] ", '<li class="todo">').replace("<li>[x] ", '<li class="done">')
    # 時刻（0:00 / 12:34 / 1:02:03）を拾いやすくする
    body = re.sub(r"(?<![\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?![\d:])", r'<span class="ts">\1</span>', body)

    out_path.write_text(
        "<!doctype html><html lang=ja><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{_html.escape(title)}</title><style>{_NOTES_STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>",
        encoding="utf-8",
    )
    return out_path


def write_index() -> Optional[Path]:
    """溜まった議事録の目次を1枚のHTMLにする。

    会が増えるほど「あの話はどの回か」が分からなくなる。ファイルが溜まる
    だけでは知識にならないので、新しい順に並べた入口を必ず更新する。
    """
    if not SEMINAR_DIR.exists():
        return None
    import html as _html

    rows = []
    for d in SEMINAR_DIR.iterdir():
        meta_file = d / "meta.json"
        if not d.is_dir() or not meta_file.exists():
            continue
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append((d.name, meta))
    if not rows:
        return None

    # 並べ替えは「開催日」が最優先。作成日は処理した日なので、あとから
    # 古い録画を読み込むと順番が狂う。開催日が無い回はフォルダ名で補う。
    def sort_key(row):
        slug, meta = row
        return (str(meta.get("held_on") or "")
                or str(meta.get("created_at", ""))[:10]
                or slug)
    rows.sort(key=sort_key, reverse=True)

    items = []
    for slug, meta in rows:
        title = _html.escape(str(meta.get("title", slug)))
        created = str(meta.get("held_on") or str(meta.get("created_at", ""))[:10])
        method = _html.escape(str(meta.get("method", "")))
        chars = meta.get("chars") or 0
        has_notes = (SEMINAR_DIR / slug / "notes.html").exists()
        link = f"{slug}/notes.html" if has_notes else f"{slug}/transcript.txt"
        label = "議事録を読む" if has_notes else "文字起こしのみ"
        items.append(
            f'<li><a href="{_html.escape(link)}"><span class="d">{created}</span>'
            f'<span class="t">{title}</span></a>'
            f'<span class="m">{label} ／ {chars:,}字 ／ {method}</span></li>'
        )

    style = """
:root{--bg:#F6F7F9;--paper:#fff;--ink:#15181D;--ink2:#4A5260;--ink3:#79828F;
--line:#E2E6EB;--accent:#2F5D8A;color-scheme:light}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0F1216;--paper:#171B21;
--ink:#ECEFF3;--ink2:#B0B9C4;--ink3:#7F8896;--line:#282E37;--accent:#8FB4DC;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Hiragino Sans","Yu Gothic",system-ui,sans-serif;line-height:1.8;font-size:15px}
main{max-width:760px;margin:0 auto;padding:36px 22px 80px}
h1{font-size:24px;margin:0 0 6px}
.lead{color:var(--ink3);font-size:13.5px;margin:0 0 28px}
ul{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:10px}
li{background:var(--paper);border:1px solid var(--line);border-radius:4px;padding:14px 16px}
li a{text-decoration:none;display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
.d{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;color:var(--ink3);white-space:nowrap}
.t{font-size:16px;font-weight:700;color:var(--accent)}
li a:hover .t{text-decoration:underline}
.m{display:block;margin-top:5px;font-size:12px;color:var(--ink3)}
"""
    out = SEMINAR_DIR / "index.html"
    out.write_text(
        "<!doctype html><html lang=ja><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>議事録の目次</title><style>{style}</style></head><body><main>"
        f"<h1>議事録の目次</h1><p class=lead>新しい順。{len(rows)}件たまっています。</p>"
        f"<ul>{''.join(items)}</ul></main></body></html>",
        encoding="utf-8",
    )
    return out


def _resolve_slug(explicit: Optional[str], title: str) -> str:
    if explicit:
        return explicit
    slug = _slugify(title)
    stamp = datetime.now().strftime("%Y-%m-%d")
    return f"{stamp}-{slug}" if slug else f"seminar-{stamp}"


def latest_slug() -> Optional[str]:
    if not SEMINAR_DIR.exists():
        return None
    dirs = [d for d in SEMINAR_DIR.iterdir() if (d / "transcript.txt").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime).name


def list_seminars() -> None:
    if not SEMINAR_DIR.exists() or not any(SEMINAR_DIR.iterdir()):
        print("まだセミナーがありません。")
        print("  python3 seminar_notes.py <録画URL または音声ファイル> --title \"セミナー名\"")
        return
    print("保存済みのセミナー:\n")
    for d in sorted(SEMINAR_DIR.iterdir()):
        if not (d / "transcript.txt").exists():
            continue
        meta = {}
        if (d / "meta.json").exists():
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            except Exception:
                pass
        chars = len((d / "transcript.txt").read_text(encoding="utf-8"))
        notes = "議事録あり" if (d / "notes.md").exists() else "議事録なし"
        print(f"  {d.name}")
        print(f"    {meta.get('title', '(タイトル未設定)')} / {chars:,}字 / {notes}")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="セミナー録画から文字起こし・議事録を作り、内容に質問できるようにする",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("## 使い方")[1].split("## 出力")[0] if "## 使い方" in __doc__ else "",
    )
    parser.add_argument("source", nargs="?",
                        help="録画のURL（YouTube / Zoom）、Zoom の会議ID、音声・動画ファイル、"
                             "または文字起こし済みのテキスト（.txt/.vtt/.srt）")
    parser.add_argument("--title", default="", help="セミナー名（議事録の見出しに使う）")
    parser.add_argument("--slug", help="保存先フォルダ名。省略時は日付＋タイトルから作る")
    parser.add_argument("--lang", default="", help="字幕の言語を指定（例: ja）")
    parser.add_argument("--cookies", help="Cookie ファイル（限定公開・要ログインの動画用）")
    parser.add_argument("--cookies-from-browser", help="ブラウザから Cookie を借りる（chrome / firefox 等）")
    parser.add_argument("--audio", action="store_true", help="字幕を使わず音声から文字起こしする")
    parser.add_argument("--cloud-transcribe", action="store_true",
                        help="文字起こしをクラウド（Gemini）で行う。速いが鍵と費用が要り、"
                             "音声が外に出る。既定は Mac の中で処理する")
    parser.add_argument("--focus", default="",
                        help="議事録で厚く書いてほしいところ（例: \"ツールの使い方を手順まで詳しく\"）")
    parser.add_argument("--no-notes", action="store_true", help="文字起こしだけ作って議事録は作らない")
    parser.add_argument("--ask", metavar="質問", help="保存済みのセミナーに質問する")
    parser.add_argument("--list", action="store_true", help="保存済みのセミナー一覧")
    parser.add_argument("--index", action="store_true",
                        help="溜まった議事録の目次（index.html）を作り直す")
    parser.add_argument("--zoom", action="store_true",
                        help="ソースを Zoom のクラウド録画として扱う（会議IDを渡すとき）")
    parser.add_argument("--zoom-list", action="store_true",
                        help="Zoom のクラウド録画の一覧を出す")
    parser.add_argument("--zoom-days", type=int, default=30,
                        help="Zoom の録画をさかのぼる日数（既定30日）")
    args = parser.parse_args()

    if args.list:
        list_seminars()
        return 0

    if args.index:
        out = write_index()
        print(f"📇 目次を作りました: {out}" if out else "⚠️  まだ議事録がありません")
        return 0

    if args.zoom_list:
        return zoom_list(args.zoom_days)

    if args.ask:
        slug = args.slug or latest_slug()
        if not slug:
            print("⚠️  まだセミナーが登録されていません。先に録画を読み込んでください。")
            return 1
        print(f"📖 {slug} に質問します\n")
        result = answer(slug, args.ask)
        if not result:
            return 1
        print(result)
        return 0

    if not args.source:
        parser.print_help()
        return 1

    title = args.title or (args.source if not _is_url(args.source) else "セミナー録画")
    langs = [args.lang] + DEFAULT_LANGS if args.lang else DEFAULT_LANGS

    print(f"🎥 {title}")
    print(f"   ソース: {args.source}\n")

    got = fetch_transcript(args.source, langs, args.cookies,
                           args.cookies_from_browser, args.audio,
                           zoom=args.zoom, zoom_days=args.zoom_days,
                           cloud_first=args.cloud_transcribe)
    if not got:
        print("\n⚠️  文字起こしを取得できませんでした。次のどれかを試してください:")
        print("   - 限定公開でログインが要る場合: --cookies-from-browser chrome")
        print("   - 字幕が無い動画: --audio（Mac の中で文字起こしします。費用ゼロ）")
        print("   - Zoom のクラウド録画: --zoom-list で一覧を出して会議IDを指定する")
        print("   - 手元に録画ファイルがあるなら、URL の代わりにファイルを渡す")
        return 1

    transcript, method = got
    print(f"   ✅ 文字起こしを取得しました（{method} / {len(transcript):,}字）\n")

    slug = _resolve_slug(args.slug, title)
    outdir = SEMINAR_DIR / slug
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "transcript.txt").write_text(transcript, encoding="utf-8")
    # 開催日はスラッグ先頭の日付から拾う（例: 2026-08-31-...）。
    # 作成日＝処理した日なので、古い録画を後から読み込むと目次の順番が狂う。
    held = re.match(r"(\d{4}-\d{2}-\d{2})", slug)
    (outdir / "meta.json").write_text(json.dumps({
        "title": title,
        "source": args.source,
        "method": method,
        "chars": len(transcript),
        "held_on": held.group(1) if held else None,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_notes:
        notes = build_notes(title, transcript, args.source, args.focus)
        if notes:
            md = outdir / "notes.md"
            md.write_text(f"# {title}\n\n{notes}\n", encoding="utf-8")
            write_html(md, outdir / "notes.html")
            write_index()
            print("   ✅ 議事録を作成しました\n")
        else:
            print("   ⚠️  議事録の作成は失敗しましたが、文字起こしは保存済みです\n")

    print(f"📁 {outdir}")
    print(f"   transcript.txt … NotebookLM に「テキストを貼り付け」で渡せます")
    if (outdir / "notes.md").exists():
        print(f"   notes.md       … 議事録・タイムスタンプ付き要約・配布メール文面")
    print(f"\n💬 質問する:")
    print(f"   python3 seminar_notes.py --ask \"知りたいこと\" --slug {slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
