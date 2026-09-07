#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ポッドキャストの「てらこ先生」の台詞を Teraco Voice（本人の声・0円）で作り直す。

Teraco Voice ＝ 講義メーカー（~/.claude/skills/teraco-movie）の `--use terako`。
GPT-SoVITS のゼロショット（追加学習なし・見本 ref_B.wav）で、このMacの中だけで動く。
ミカは従来どおり edge-tts（クラウド・0円）。

  python3 podcast_teraco_voice.py podcast/script-2026-09-04.txt --out /tmp/test.mp3

作った台詞ごとの音声は podcast/.work/<台本名>/ に残す（途中で落ちても続きから。--clean で捨てて作り直し）。

GitHub Actions では動かない（Mac専用）ので、朝の自動処理とは別に Mac 側で走らせる前提。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from generate_podcast import preprocess_for_tts                     # noqa: E402
from generate_podcast_dialogue import (                             # noqa: E402
    parse_dialogue, _voice_params_for, _tts_segment_async, _run_async,
)

SKILL     = Path.home() / ".claude/skills/teraco-movie"
SOVITS_PY = Path.home() / ".openclaw/workspace/GPT-SoVITS/.venv/bin/python"
VOICE_KEY = "terako"          # voice.json の項目名（＝Teraco Voice）
SIL_SAME, SIL_CHANGE = 0.25, 0.5   # 同一話者／話者交代の間（秒）。従来と同じ
PEAK_DB = -2.0                # 2つの声の音量をそろえる（ピーク基準）


def _tidy_for_teraco(text: str) -> str:
    """Teraco Voice 向けの手直し。呼びかけのあとの読点は語尾が伸びるので「！」にする。"""
    text = preprocess_for_tts(text)
    for name in ("ミカさん", "みなさん", "リスナーのみなさん"):
        text = text.replace(name + "、", name + "！")
    return text


def synth_teraco(jobs, log):
    """てらこ先生の台詞をまとめて1回のモデル読み込みで作る（sovits_say.py）。"""
    # 種42（sovits_say.py の既定）はこの声だと20件中16件が空振り（無音・同じ音の繰り返し）になった。
    # 種1019から始めると6件中6件が1回で合格（2026-09-05 実測）。作成時間が約70分→約7分。
    env = dict(os.environ, TERAKO_VOICE=VOICE_KEY, TERAKO_SEED=os.environ.get("TERAKO_SEED", "1019"))
    r = subprocess.run([str(SOVITS_PY), str(SKILL / "sovits_say.py")],
                       input=json.dumps(jobs, ensure_ascii=False).encode(),
                       capture_output=True, env=env)
    log.write(r.stdout.decode("utf-8", "replace"))
    if r.returncode != 0:
        log.write(r.stderr.decode("utf-8", "replace")[-2000:])
        raise SystemExit("Teraco Voice の読み上げに失敗しました（log を見てください）")


def trim_pauses(wav: Path):
    r = subprocess.run([str(SOVITS_PY), str(SKILL / "trim_pauses.py"), str(wav), "--out", str(wav)],
                       capture_output=True)
    if r.returncode != 0:
        print(f"  ！ 間の詰めに失敗（そのまま使う）: {wav.name} {r.stderr.decode('utf-8','replace')[-200:]}")


def to_pcm(src: Path, dst: Path):
    """どの声も 24kHz mono 16bit wav にそろえ、ピークを PEAK_DB に合わせる。"""
    probe = subprocess.run(["ffmpeg", "-i", str(src), "-af", "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    gain = 0.0
    for line in probe.splitlines():
        if "max_volume" in line:
            gain = PEAK_DB - float(line.split("max_volume:")[1].split("dB")[0])
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-af", f"volume={gain:.2f}dB",
                    "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
                   capture_output=True, check=True)


def build(script_path: Path, out_mp3: Path, log):
    segments = parse_dialogue(script_path.read_text(encoding="utf-8"))
    if not segments:
        raise SystemExit("台本に [てらこ先生]/[ミカ] の行がありません")
    n_t = sum(1 for s, _ in segments if s == "てらこ先生")
    log.write(f"台詞 {len(segments)} 件（てらこ先生 {n_t}／ミカ {len(segments) - n_t}）\n")

    work = HERE / "podcast" / ".work" / script_path.stem
    work.mkdir(parents=True, exist_ok=True)
    if True:
        tmp = work
        # 1) てらこ先生 → Teraco Voice（まとめて。作り済みの分は飛ばす＝途中で落ちてもやり直しが速い）
        jobs = [{"text": _tidy_for_teraco(t), "out": str(tmp / f"t_{i:04d}.wav")}
                for i, (s, t) in enumerate(segments) if s == "てらこ先生"]
        todo = [j for j in jobs if not (Path(j["out"]).exists() and Path(j["out"]).stat().st_size > 0)]
        log.write(f"Teraco Voice で {len(todo)} 件を作成中（作り済み {len(jobs) - len(todo)} 件）...\n"); log.flush()
        if todo:
            synth_teraco(todo, log)
            for j in todo:
                trim_pauses(Path(j["out"]))

        # 2) ミカ → edge-tts
        log.write("ミカ（edge-tts）を作成中...\n"); log.flush()
        for i, (s, t) in enumerate(segments):
            if s != "ミカ" or (tmp / f"m_{i:04d}.mp3").exists():
                continue
            p = _voice_params_for(s)
            _run_async(_tts_segment_async(t, p["voice"], tmp / f"m_{i:04d}.mp3",
                                          rate=p["rate"], pitch=p["pitch"]))

        # 3) そろえて結合
        entries, prev = [], ""
        for i, (s, _) in enumerate(segments):
            src = tmp / (f"t_{i:04d}.wav" if s == "てらこ先生" else f"m_{i:04d}.mp3")
            if not src.exists() or src.stat().st_size == 0:
                log.write(f"  ！ {i} 番（{s}）が作れていないので飛ばします\n")
                continue
            dst = tmp / f"p_{i:04d}.wav"
            to_pcm(src, dst)
            if prev:
                sil = tmp / ("sil_same.wav" if prev == s else "sil_change.wav")
                if not sil.exists():
                    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                                    "-t", str(SIL_SAME if prev == s else SIL_CHANGE),
                                    "-c:a", "pcm_s16le", str(sil)], capture_output=True, check=True)
                entries.append(sil)
            entries.append(dst)
            prev = s
        lst = tmp / "concat.txt"
        lst.write_text("".join(f"file '{e}'\n" for e in entries))
        out_mp3.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "80k",
                        "-write_xing", "1", "-id3v2_version", "3", str(out_mp3)],
                       capture_output=True, check=True)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(out_mp3)], capture_output=True, text=True).stdout.strip()
    log.write(f"できました {out_mp3}  {float(dur or 0)/60:.1f}分\n")


VOICES_FILE = HERE / "podcast" / "voices.json"   # どの回がどの声で作られたかの台帳（サイトにも載せられる）
PRODUCT = "Teraco Voice"


def _product_version() -> str:
    try:
        v = json.loads((SKILL / "voice.json").read_text(encoding="utf-8"))["voices"][VOICE_KEY]
        return v.get("product_version", "?")
    except Exception:
        return "?"


def publish(date_str: str, log) -> int:
    """その日の回を Teraco Voice 版に差し替えて公開する（Mac の定時ジョブから呼ばれる）。

    戻り値 0=差し替えた／2=まだ台本が無い（クラウド側が未完了）／3=差し替え済み
    """
    from datetime import datetime
    from generate_podcast import update_feed
    script = HERE / "podcast" / f"script-{date_str}.txt"
    mp3    = HERE / "podcast" / f"ai-news-{date_str}.mp3"
    voices = json.loads(VOICES_FILE.read_text(encoding="utf-8")) if VOICES_FILE.exists() else {}
    if voices.get(date_str, {}).get("teraco") == f"{PRODUCT} {_product_version()}":
        log.write(f"{date_str} は差し替え済み\n"); return 3
    if not script.exists() or not mp3.exists():
        log.write(f"{date_str} の台本または音声がまだ無い（クラウド側の配信待ち）\n"); return 2
    build(script, mp3, log)
    # フィードに載せてよいかの判定（generate_podcast._feed_ready）が voices.json を見るので、
    # update_feed より先に「本人の声にした」と記録しておく
    voices[date_str] = {"teraco": f"{PRODUCT} {_product_version()}", "mika": "edge-tts ja-JP-NanamiNeural"}
    VOICES_FILE.write_text(json.dumps(voices, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    update_feed(datetime.strptime(date_str, "%Y-%m-%d"), mp3)
    log.write(f"{date_str} を {PRODUCT} {_product_version()} に差し替えました\n")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?", help="podcast/script-YYYY-MM-DD.txt（試作用）")
    ap.add_argument("--out", help="書き出す mp3（試作用）")
    ap.add_argument("--publish", metavar="YYYY-MM-DD", help="その日の回を本番差し替え（feed/episodes も更新）")
    ap.add_argument("--clean", action="store_true", help="作り済みの台詞音声を捨てて全部作り直す")
    a = ap.parse_args()
    if a.publish:
        if a.clean:
            import shutil
            shutil.rmtree(HERE / "podcast" / ".work" / f"script-{a.publish}", ignore_errors=True)
        sys.exit(publish(a.publish, sys.stdout))
    if not (a.script and a.out):
        ap.error("試作は 台本 と --out、本番は --publish 日付 を指定してください")
    if a.clean:
        import shutil
        shutil.rmtree(HERE / "podcast" / ".work" / Path(a.script).stem, ignore_errors=True)
    build(Path(a.script), Path(a.out), sys.stdout)


if __name__ == "__main__":
    main()
