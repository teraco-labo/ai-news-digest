"""選んだ記事の「日本ではいつから使えるか」を、公式の出どころで調べて要約の最後に1文足す。

2026-10-14 藤崎さん「拾ってきている情報はほとんど海外の最新のもの。日本ではまだ使えないケースが多い。
きちんと調べて、日本ではいつから使えるかを付けないと、早速試そうと思ってもできないことがある」。

- 調べるのは「読者が自分で試せるもの」（モデル・アプリ・機能・サービス）だけ。研究・資金調達・規制の話は対象外
- 公式（提供元の日本語ページ・ヘルプ・提供地域の一覧・公式発表）で確かめる。確かめられなければ
  「日本での提供時期は発表されていません」と書く。推測で「近く使えそう」とは書かない
- Claude は claude -p（サブスク枠）。API の従量課金にはフォールバックしない（調べる段なので、無ければ足さないだけ）
- 失敗しても配信は止めない（その日は1文が付かないだけ）
"""
import json
import os
import shutil
import subprocess
from typing import Dict, List

TARGET_CATEGORIES = ("model", "tools")
MAX_ITEMS = 8

PROMPT = """あなたは日本のAIニュースの事実確認係です。次の記事のうち、読者が自分で試せるもの
（AIのモデル・アプリ・機能・サービス）について、**日本で今使えるか、使えないならいつから使えるか**を調べてください。

調べ方：
- WebSearch と WebFetch で、提供元の公式（日本語ページ、ヘルプセンター、提供地域・対応言語の一覧、公式ブログ・発表）を開いて確かめる
- ニュースサイトやSNSだけを根拠にしない。公式で確かめられないことは書かない
- 「日本で使える」には、日本から使えるか（提供地域）を見る。日本語に対応しているかも分かれば添える

each の書き方（1文・です・ます・「日本では、」で始める）：
- 使える：「日本では、すでに使えます（日本語にも対応）。」
- 時期が発表済み：「日本では、11月から使える予定です。」
- まだ・時期未定：「日本では、まだ使えません。提供時期は発表されていません。」
- 分からない：「日本での提供時期は、公式には発表されていません。」
- 一部だけ：「日本では、有料プランの人だけ使えます。」のように条件を書く
試せるものではない記事（研究・資金調達・規制など）は入れない。

返事は次の JSON だけ（前置き・コードフェンスなし）：
{"items": [{"index": 記事番号, "japan": "日本では、〜。", "source": "確かめた公式ページのURL"}]}

---
"""


def _claude(prompt: str) -> str:
    exe = shutil.which("claude") or next((p for p in (os.path.expanduser("~/.npm-global/bin/claude"),
                                                      "/opt/homebrew/bin/claude") if os.path.exists(p)), None)
    if not exe:
        raise RuntimeError("claude コマンドが見つかりません")
    env = os.environ.copy()
    for k in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_AUTH_TOKEN"):   # サブスク枠だけで動かす
        env.pop(k, None)
    tools = ["WebSearch", "WebFetch"]
    cmd = [exe, "-p", "--output-format", "json", "--tools", *tools, "--allowedTools", *tools,
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence"]
    pr = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1200, env=env)
    outer = json.loads(pr.stdout)
    if outer.get("is_error"):
        raise RuntimeError(str(outer.get("result", ""))[:300])
    return str(outer.get("result", ""))


def annotate(categorized: Dict[str, List[Dict]], verbose: bool = True) -> Dict[str, List[Dict]]:
    """対象の記事の summary の最後に「日本では、〜。」を1文足す（その場で書き換えて返す）。"""
    picks = []
    for c in TARGET_CATEGORIES:
        for a in categorized.get(c, []):
            picks.append(a)
    picks = sorted(picks, key=lambda a: -int(a.get("importance", 1)))[:MAX_ITEMS]
    if not picks:
        return categorized
    lines = []
    for i, a in enumerate(picks):
        lines.append(f"[{i}] {a.get('title_ja') or a.get('title', '')}\n{a.get('summary', '')}\n元記事: {a.get('url', '')}")
    try:
        r = _claude(PROMPT + "\n\n".join(lines))
        data = json.loads(r[r.index("{"): r.rindex("}") + 1])
    except Exception as e:
        if verbose:
            print(f"   ⚠️  日本での提供状況を調べられませんでした（今日は付けずに続行）: {e}")
        return categorized
    n = 0
    for it in data.get("items", []):
        try:
            a = picks[int(it["index"])]
        except Exception:
            continue
        j = str(it.get("japan", "")).strip()
        if not j.startswith("日本"):
            continue
        a["japan"] = j
        a["japan_source"] = str(it.get("source", ""))
        if j not in a.get("summary", ""):
            a["summary"] = a.get("summary", "").rstrip() + j
            n += 1
    if verbose:
        print(f"   日本での提供状況を {n} 件に付けました")
    return categorized
