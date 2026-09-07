#!/usr/bin/env python3
"""
【テスト専用】ミカを「日本語を片言で話す外国人」にしたバージョンを生成する。
本番運用には組み込まない。既存の台本を読み込み、ミカのセリフだけを
片言に書き換え、外国人アクセントの多言語ボイスで読み上げる。
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from generate_podcast_dialogue import parse_dialogue, preprocess_for_tts  # noqa: E402

# てらこ先生は通常の日本語ボイスのまま
VOICE_TERAKO = "ja-JP-KeitaNeural"
# ミカは多言語ボイス（日本語を外国人アクセントで読む）
VOICE_MIKA_FOREIGN = os.environ.get("MIKA_VOICE", "en-US-AvaMultilingualNeural")

REWRITE_PROMPT = """\
あなたは、ポッドキャスト台本のセリフを書き換える編集者です。
以下は日本のラジオ番組のアシスタント「ミカ」のセリフです。

このミカのキャラクター設定を変更します。
ミカは日本語を勉強中の外国人アシスタントで、日本語がまだ完璧ではなく「片言」で話します。
好感が持てる、明るくて一生懸命な外国人という印象にしてください。
バカにした感じや、失礼な戯画化にはしないこと。

【片言の書き方のルール】
- 助詞（は・が・を・に）をときどき省く。例：「これ、とても 便利ですね」
- 難しい敬語や熟語は使わず、やさしい言葉に置き換える
- 一人称は「わたし」。文末は「〜ですね」「〜ます」「〜ました」中心
- ときどき「えーと」「んー」と言葉を探す
- ときどき「日本語で なんて 言いますか？」のように単語を確認する
- カタカナの外来語を好んで使う
- 一文を短く区切る。長い complex な文にしない
- 内容（意味）は元のセリフから変えないこと

【出力形式】
元のセリフと同じ行数だけ、書き換えたセリフを1行ずつ出力してください。
番号や記号、説明文は一切付けず、セリフ本文のみを1行ずつ出力すること。

【元のセリフ】
"""


def rewrite_mika_lines(lines):
    """Gemini でミカのセリフをまとめて片言に書き換える。"""
    from google import genai as google_genai
    from google.genai import types as genai_types

    client = google_genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    numbered = "\n".join(lines)
    resp = client.models.generate_content(
        model="gemini-flash-latest",
        contents=REWRITE_PROMPT + numbered,
        config=genai_types.GenerateContentConfig(temperature=0.8, max_output_tokens=8192),
    )
    out = [l.strip() for l in (resp.text or "").splitlines() if l.strip()]
    # 行数が合わない場合は、足りない分を元のセリフで埋める
    if len(out) != len(lines):
        print(f"  ⚠️  行数不一致（元{len(lines)} / 生成{len(out)}）→ 可能な範囲で対応付け")
        out = (out + lines[len(out):])[: len(lines)]
    return out


async def tts(text, voice, path, rate="+0%", pitch="+0Hz"):
    import edge_tts
    for attempt in range(4):
        try:
            c = edge_tts.Communicate(preprocess_for_tts(text), voice, rate=rate, pitch=pitch)
            await c.save(str(path))
            if path.exists() and path.stat().st_size > 0:
                return
            raise RuntimeError("empty")
        except Exception:
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"TTS failed: {text[:20]}")


def main():
    src_script = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "podcast/script-2026-08-26.txt"
    max_turns = int(sys.argv[2]) if len(sys.argv) > 2 else 16  # テストなので冒頭だけ
    out_mp3 = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/katakoto_test.mp3")

    segments = parse_dialogue(src_script.read_text(encoding="utf-8"))[:max_turns]
    mika_idx = [i for i, (sp, _) in enumerate(segments) if sp == "ミカ"]
    mika_lines = [segments[i][1] for i in mika_idx]

    print(f"  対象: {len(segments)}ターン（うちミカ {len(mika_lines)}）")
    print("  ミカのセリフを片言に書き換え中...")
    rewritten = rewrite_mika_lines(mika_lines)

    new_segments = list(segments)
    for i, new_line in zip(mika_idx, rewritten):
        new_segments[i] = ("ミカ", new_line)

    print("\n--- 書き換え例 ---")
    for orig, new in list(zip(mika_lines, rewritten))[:3]:
        print(f"  元: {orig[:48]}")
        print(f"  後: {new[:48]}\n")

    print(f"  音声合成中（ミカの声: {VOICE_MIKA_FOREIGN}）…")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        entries = []
        for i, (sp, text) in enumerate(new_segments):
            f = td / f"s{i:03d}.mp3"
            if sp == "てらこ先生":
                asyncio.run(tts(text, VOICE_TERAKO, f, pitch="-2Hz"))
            else:
                # 外国人らしく少しゆっくり
                asyncio.run(tts(text, VOICE_MIKA_FOREIGN, f, rate="-8%"))
            entries.append(f)

        sil = td / "sil.mp3"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                        "-t", "0.42", "-codec:a", "libmp3lame", "-b:a", "64k", str(sil)],
                       capture_output=True, check=True)

        lst = td / "l.txt"
        with open(lst, "w") as f:
            for i, e in enumerate(entries):
                if i:
                    f.write(f"file '{sil}'\n")
                f.write(f"file '{e}'\n")

        mid = td / "mid.mp3"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-codec:a", "libmp3lame", "-b:a", "64k", str(mid)],
                       capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(mid), "-ar", "44100", "-ac", "2",
                        "-codec:a", "libmp3lame", "-b:a", "80k", "-write_xing", "1",
                        str(out_mp3)], capture_output=True, check=True)

    # 台本も保存
    out_txt = out_mp3.with_suffix(".txt")
    out_txt.write_text("\n\n".join(f"[{s}] {t}" for s, t in new_segments), encoding="utf-8")
    print(f"  ✓ {out_mp3}")
    print(f"  ✓ {out_txt}")


if __name__ == "__main__":
    main()
