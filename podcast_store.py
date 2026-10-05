#!/usr/bin/env python3
"""
ポッドキャスト音声（mp3）の置き場所を一か所で扱う。

2026-10-05 から、音声はリポジトリではなく Cloudflare R2（音声ファイルの倉庫）に置く。
リポジトリに mp3 を入れ続けると、GitHub の推奨上限（1GB）を数か月で超えるため。
R2 は保存10GB・配信の転送料が無料で、この規模なら当面0円。

- どの日の音声がどこにあるかは podcast/audio.json（台帳）に書く。
  mp3 を手元から消しても「音声あり」と判定できるようにするため
  （以前は「podcast/ にファイルがあるか」で判定していた）
- R2 へ上げられなかった日は、従来どおりサイト（GitHub Pages）の podcast/ に置き、
  台帳に where="site" と書く。配信を止めないための保険
- 鍵は環境変数（GitHub Actions の Secrets）か、Mac のキーチェーン（サービス名 teraco-r2）から読む。
  鍵をファイルに書かない（公開リポジトリのため）

使い方:
  python3 podcast_store.py upload 2026-10-05     その日の mp3 を R2 へ上げて台帳に書く
  python3 podcast_store.py migrate               podcast/ の mp3 を全部 R2 へ上げる（初回の引っ越し）
  python3 podcast_store.py check                 台帳の全部の音声が R2 で開けるか確かめる
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

REPO_DIR = Path(__file__).parent
PODCAST_DIR = REPO_DIR / "podcast"
INDEX_FILE = PODCAST_DIR / "audio.json"
CONFIG_FILE = REPO_DIR / "monetize_config.json"
KEYCHAIN_SERVICE = "teraco-r2"


def _config() -> Dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("podcast", {})
    except Exception:
        return {}


def site_base() -> str:
    return _config().get("base_url", "https://teraco-labo.github.io/ai-news-digest").rstrip("/")


def r2_base() -> str:
    """R2 の公開URL（例 https://pub-xxxx.r2.dev）。未設定なら空。"""
    return (_config().get("audio_base_url") or "").rstrip("/")


def bucket() -> str:
    return _config().get("r2_bucket") or "ai-news-podcast"


def file_name(date_iso: str) -> str:
    return f"ai-news-{date_iso}.mp3"


# ---------------------------------------------------------------- 台帳

def load_index() -> Dict[str, Dict]:
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_index(index: Dict[str, Dict]) -> None:
    INDEX_FILE.write_text(json.dumps(dict(sorted(index.items(), reverse=True)),
                                     ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def record(date_iso: str, where: str, size: int) -> None:
    index = load_index()
    index[date_iso] = {"where": where, "size": int(size)}
    save_index(index)


def has_audio(date_iso: str) -> bool:
    """その日の音声があるか。台帳に載っているか、手元に mp3 があれば「あり」。"""
    e = load_index().get(date_iso)
    if e and int(e.get("size") or 0) > 0:
        return True
    p = PODCAST_DIR / file_name(date_iso)
    return p.exists() and p.stat().st_size > 0


def audio_url(date_iso: str, relative: bool = False) -> str:
    """その日の音声の公開URL。R2 にあれば R2、なければサイトの podcast/。

    relative=True は、サイト内のページから相対パスで鳴らしたいとき用
    （R2 にある日は相対にできないので、R2 の絶対URLを返す）。
    """
    e = load_index().get(date_iso) or {}
    if e.get("where") == "r2" and r2_base():
        return f"{r2_base()}/{file_name(date_iso)}"
    if relative:
        return f"podcast/{file_name(date_iso)}"
    return f"{site_base()}/podcast/{file_name(date_iso)}"


# ---------------------------------------------------------------- R2 への送り出し

def _keychain(account: str) -> str:
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
                            "-a", account, "-w"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _cred(name: str) -> str:
    return os.environ.get(name) or _keychain(name)


def _client():
    import boto3
    from botocore.config import Config
    account = _cred("R2_ACCOUNT_ID")
    key_id = _cred("R2_ACCESS_KEY_ID")
    secret = _cred("R2_SECRET_ACCESS_KEY")
    if not (account and key_id and secret):
        raise RuntimeError("R2 の鍵がありません（R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY）")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="auto",
        # 新しい boto3 は既定でチェックサムを付ける。R2 で弾かれることがあったので必要なときだけにする
        config=Config(request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )


def upload_file(path: Path, client=None) -> None:
    client = client or _client()
    client.upload_file(
        str(path), bucket(), path.name,
        ExtraArgs={
            "ContentType": "audio/mpeg",
            # 朝はクラウド版、そのあと Mac が本人の声に同じ名前で差し替えるので、
            # 古い音声がスマホ等に残らないよう毎回「変わっていないか」を確かめさせる
            "CacheControl": "no-cache",
        },
    )


def publish(date_iso: str) -> str:
    """その日の mp3 を R2 へ上げて台帳に書く。上げられなければサイト置き場（where=site）で記録。

    戻り値は "r2" か "site"。site のときは呼び出し側で mp3 をコミットすること
    （.gitignore で mp3 を外しているので git add -f が要る）。
    """
    path = PODCAST_DIR / file_name(date_iso)
    size = path.stat().st_size
    try:
        if not r2_base():
            raise RuntimeError("monetize_config.json の podcast.audio_base_url が未設定")
        upload_file(path)
        record(date_iso, "r2", size)
        print(f"  ✓ 音声を R2 へ: {audio_url(date_iso)}")
        return "r2"
    except Exception as e:
        record(date_iso, "site", size)
        print(f"  ⚠️ 音声を R2 へ上げられませんでした（サイトに置きます）: {e}")
        return "site"


def site_files() -> list:
    """サイト置き場（where=site）の mp3。コミット時に git add -f するもの。"""
    return [f"podcast/{file_name(d)}" for d, e in load_index().items()
            if e.get("where") == "site" and (PODCAST_DIR / file_name(d)).exists()]


# ---------------------------------------------------------------- コマンド

def _migrate() -> int:
    client = _client()
    files = sorted(PODCAST_DIR.glob("ai-news-*.mp3"))
    print(f"{len(files)} 本を R2（{bucket()}）へ上げます")
    for i, p in enumerate(files, 1):
        upload_file(p, client)
        record(p.stem.replace("ai-news-", ""), "r2", p.stat().st_size)
        print(f"  [{i}/{len(files)}] {p.name}")

    # episodes.json の音声URLを R2 に差し替える。guid は元のURLのまま固定する
    # （Spotify 登録済み。guid が変わると全話が新しい回として重複する）
    ep_file = PODCAST_DIR / "episodes.json"
    episodes = json.loads(ep_file.read_text(encoding="utf-8"))
    for e in episodes:
        e.setdefault("guid", e["url"])
        if load_index().get(e["date"], {}).get("where") == "r2":
            e["url"] = audio_url(e["date"])
    ep_file.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding="utf-8")

    # feed.xml を作り直す（いちばん新しい回で update_feed を呼ぶと全体が書き直される）
    from datetime import datetime
    from generate_podcast import update_feed
    latest = episodes[0]["date"]
    update_feed(datetime.strptime(latest, "%Y-%m-%d"), PODCAST_DIR / file_name(latest))
    return 0


def _check() -> int:
    import urllib.request
    bad = 0
    for d, e in load_index().items():
        url = audio_url(d)
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "teraco-check"})
            with urllib.request.urlopen(req, timeout=20) as r:
                size = int(r.headers.get("Content-Length") or 0)
            ok = size == int(e.get("size") or 0)
        except Exception:
            ok = False
        if not ok:
            bad += 1
            print(f"  ✗ {d} {url}")
    print(f"確認 {len(load_index())} 本、うち開けない・大きさ違い {bad} 本")
    return 1 if bad else 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "upload" and len(sys.argv) > 2:
        sys.exit(0 if publish(sys.argv[2]) == "r2" else 1)
    if cmd == "migrate":
        sys.exit(_migrate())
    if cmd == "check":
        sys.exit(_check())
    print(__doc__)
    sys.exit(2)
