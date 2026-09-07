#!/usr/bin/env python3
"""
記事のキュレーション — 「捨てる・選ぶ・日本語で書く」を Claude に任せる。

これまでの実装の問題:
  - 選別が無く、取得した50件をそのまま全部載せていた
  - カテゴリ分けがキーワードマッチだったので誤爆していた
    （AIと無関係な記事が「研究」に入る等）
  - 日本語化が Google 翻訳の直訳だったため、固有名詞の誤訳や
    不自然な分かち書き、敬体と常体の混在が起きていた

ここでやること:
  1. AI に実質的に関係する記事だけを残す
  2. 重複を1本にまとめる
  3. 日本語の見出しとして自然なタイトルを「書く」（翻訳ではない）
  4. 「何が起きたか・なぜ重要か」を2〜3文で書く
  5. カテゴリと重要度を判定する

失敗しても止めない:
  API キーが無い・通信に失敗した等の場合は None を返し、
  呼び出し側は従来のキーワード分類＋機械翻訳にフォールバックする。
"""

import json
import os
import re
from typing import Dict, List, Optional

import monetize

CATEGORIES = ["model", "research", "business", "policy", "tools"]

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_MIN = 8
DEFAULT_MAX = 12

SYSTEM_PROMPT = """あなたは日本のAI専門メディアの編集者です。
その日に集まった英語のテック記事から、日本の読者に届ける価値のあるものだけを選び、日本語で書き直します。

## 選ぶ基準

- AI・機械学習に**実質的に**関係する記事だけを残す。
  単に「テック企業のニュース」というだけのもの、AIに触れていない製品・企業・訴訟の話は落とす。
- 同じ出来事を報じた記事が複数あれば、最も情報量の多い1本にまとめる。
- 残りは重要度の高い順に並べる。

## 日本語の書き方

- **翻訳しない。日本語の見出しとして書き直す。** 直訳調は禁止。
- 製品名・企業名・人名・ニュースレター名などの固有名詞は訳さずそのまま使う。
  （例: "The Download" はニュースレター名なので「ダウンロード」と訳さない）
- カタカナ語を不自然に分かち書きしない。
  （×「カスタマー サービス エクスペリエンス」→ ○「カスタマーサポート体験」）
- 文体は敬体（です・ます）で統一する。常体と混ぜない。
- **本文のレベルを下げない。** 大人が読んで物足りなくならない筆致を保つこと。
  専門用語を本文で使うのは構わない（用語には別の仕組みで解説が付くため、
  本文側でかみくだく必要はない）。やさしくしすぎると中級の読者が離れる。
- 要約は3〜5文。読者が元記事を開かなくても要点が掴めることをゴールにする。
  「何が起きたか」→「背景・数字・固有名詞などの具体」→「なぜ重要か / 読者に何が変わるか」
  の順で書く。元記事の説明文をなぞるだけにしない。
- 金額・割合・日付などの具体的な数字が元記事にあれば、必ず要約に残す。

## カテゴリ

- model: 新しいモデル・性能・リリース
- research: 研究成果・論文・技術的な発見
- business: 資金調達・買収・提携・市場動向・採用
- policy: 規制・訴訟・倫理・安全性・著作権
- tools: 開発者向けツール・API・製品機能

## 重要度

- 3: その日の主要ニュース。業界の流れが変わりうるもの。**毎日必ず1〜3件選ぶ**
- 2: 知っておきたいが、決定的ではないもの
- 1: 参考程度

判断に迷ったら「載せない」を選んでください。件数を埋めるために質を落とさないこと。

## 用語の抽出

このサイトは「専門用語にすべて解説がつく」ことを売りにしています。
選んだ記事に出てくる企業名・ツール名・専門用語のうち、**まだ用語集に無いもの**を
最大8件まで new_terms に入れてください。登録済みの語は入れないこと。

### 拾う基準 —「世界一わかりやすい」を名乗るサイトとして

方針: **本文はレベルを下げない代わりに、引っかかりうる言葉には全部フォローを付ける。**
「そこまで説明しなくてもいいでしょ」と言われるくらい過剰で構いません。
迷ったら**拾う**。基準は「日常生活で聞き慣れない言葉かどうか」です。

- **企業名・組織名すべて**（AI企業、投資会社、調査会社、メディア、政府機関）
- **人名**（経営者・研究者など、記事の意味に関わる人物。
  「どういう立場の人か」が1行分かるだけでニュースの読み方が変わります）
- **製品名・モデル名・チップ名・コードネーム**すべて。
  「NVIDIA Blackwell」のように登録済みの語と未登録の語が並ぶ場合、
  未登録側（この例では Blackwell）を必ず拾うこと
- **読み方が難しい英単語**（Jalapeño など。読めない綴りはそれだけで読者が止まる）
- 専門用語、規格名、業界の慣用句（「ムーンショット」「デューデリジェンス」等も対象）

拾わないもの: 誰でも知っている言葉（Google、iPhone、news など）だけ。

### 書き方

- reading には**カタカナの読み方**を必ず入れる（例: Jalapeño → ハラペーニョ）。
  日本語の用語で読みが自明なら空文字でよい
- short は専門用語を使わずに2文で書く。「〜とは」で始めない
- detail は3〜4文。なぜ重要か、実務でどう関わるかまで書く
- **記事から読み取れないことは書かない。** 推測で説明を作らないこと。
  確かなことが書けない語は new_terms に入れないでください"""


CURATION_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "array",
            "description": "その日の要点を3行で。1行はそれぞれ40〜60字程度の日本語の文。",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        },
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "入力リストで示された記事の番号",
                    },
                    "title_ja": {"type": "string", "description": "日本語の見出し（40字以内）"},
                    "summary": {"type": "string", "description": "3〜5文の日本語要約。元記事を読まなくても要点が掴める濃さで、具体的な数字を含める"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "importance": {"type": "integer", "minimum": 1, "maximum": 3},
                },
                "required": ["index", "title_ja", "summary", "category", "importance"],
                "additionalProperties": False,
            },
        },
        "new_terms": {
            "type": "array",
            "description": ("今日の記事に出てきたが用語集に未登録の、聞き慣れない言葉すべて"
                            "（企業名・人名・製品名・専門用語）。最大8件。無ければ空配列。"),
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string",
                             "description": "URLに使う英小文字とハイフンのみの識別子（例: vector-db）"},
                    "term": {"type": "string", "description": "表示名"},
                    "reading": {"type": "string",
                                "description": "カタカナの読み方（例: Jalapeño → ハラペーニョ）。不要なら空文字"},
                    "aliases": {"type": "array", "items": {"type": "string"},
                                "description": "日本語訳や別表記。無ければ空配列"},
                    "category": {"type": "string",
                                 "enum": ["基礎", "使い方", "企業", "モデル", "インフラ",
                                          "安全性", "規制", "評価", "ビジネス",
                                          "メディア", "人物"]},
                    "short": {"type": "string",
                              "description": "初心者向けの説明。2文。専門用語を使わずに書く"},
                    "detail": {"type": "string",
                               "description": "中級者向けの補足。3〜4文。背景や実務上の意味"},
                },
                "required": ["slug", "term", "reading", "aliases", "category", "short", "detail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overview", "articles", "new_terms"],
    "additionalProperties": False,
}


def _config() -> Dict:
    return monetize.load_config().get("curation", {}) or {}


def _cli_available() -> bool:
    import shutil
    return shutil.which("claude") is not None


def is_enabled() -> bool:
    return bool(_config().get("enabled", True)) and (
        _cli_available()
        or bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"))
    )


def _source_name(article: Dict) -> str:
    """取得元の名前。RSS 側は {"name": "..."} の辞書で持っているため吸収する。"""
    source = article.get("source", "")
    if isinstance(source, dict):
        return str(source.get("name", ""))
    return str(source or "")


def _article_date(article: Dict) -> str:
    """記事の日付（YYYY-MM-DD）。フィールド名の揺れ（publishedAt / date）を吸収する。"""
    raw = article.get("date") or article.get("publishedAt") or ""
    return str(raw)[:10]


_CATEGORY_ALIASES = {
    "モデル": "model", "研究": "research", "ビジネス": "business",
    "ポリシー": "policy", "ツール": "tools",
    "models": "model", "tool": "tools", "biz": "business",
}


def _normalize_category(value) -> Optional[str]:
    """モデルが返すカテゴリ表記の揺れ（大文字・日本語など）を吸収する。"""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in CATEGORIES:
        return v
    return _CATEGORY_ALIASES.get(value.strip()) or _CATEGORY_ALIASES.get(v)


def _known_terms_line() -> str:
    """登録済みの用語をモデルに伝え、重複した提案を防ぐ。"""
    try:
        import glossary
        names = sorted({t["term"] for t in glossary.published()})
        if names:
            return "【用語集に登録済み（これらは new_terms に入れない）】\n" + "、".join(names) + "\n"
    except Exception:
        pass
    return ""


def _build_user_message(articles: List[Dict], min_n: int, max_n: int) -> str:
    lines = [
        f"本日集まった記事は {len(articles)} 件です。"
        f"この中から掲載する価値のあるものを {min_n}〜{max_n} 件選び、日本語で書き直してください。",
        "",
        "AIに関係する記事が少ない日は、無理に件数を埋めず少なくて構いません。",
        "",
        _known_terms_line(),
        "---",
        "",
    ]
    for i, a in enumerate(articles):
        desc = (a.get("description") or "").strip().replace("\n", " ")
        if len(desc) > 400:
            desc = desc[:400] + "…"
        lines.append(f"[{i}] {a.get('title', '')}")
        lines.append(f"    出典: {_source_name(a) or '不明'}")
        if desc:
            lines.append(f"    概要: {desc}")
        lines.append("")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[Dict]:
    """CLI の応答テキストから JSON オブジェクトを取り出す。

    コードフェンスや前置きが混ざることがあるため、最初の '{' から
    対応する '}' までをバランスを取りながら切り出す。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _curate_via_cli(articles: List[Dict], cfg: Dict, min_n: int, max_n: int,
                    verbose: bool) -> Optional[Dict]:
    """Claude Code CLI（サブスクリプション枠）でキュレーションする。

    Max プラン契約者は `claude setup-token` で発行した OAuth トークンを
    CLAUDE_CODE_OAUTH_TOKEN として渡せば、API の従量課金なしで動く。
    ローカルではログイン済みの CLI がそのまま使われる。
    """
    import shutil
    import subprocess

    exe = shutil.which("claude")
    if not exe:
        return None

    schema_str = json.dumps(CURATION_SCHEMA, ensure_ascii=False)
    prompt = (
        SYSTEM_PROMPT
        + "\n\n## 出力形式\n\n"
        + "次の JSON Schema に**厳密に**従う JSON オブジェクトだけを出力してください。"
        + "前置き・説明・コードフェンスは一切付けないこと。\n\n"
        + schema_str
        + "\n\n---\n\n"
        + _build_user_message(articles, min_n, max_n)
    )

    cmd = [exe, "-p", "--output-format", "json",
           "--model", cfg.get("cli_model", "opus")]

    # Claude Code の認証は ANTHROPIC_API_KEY が OAuth トークンより優先される。
    # 失効した API キーが環境に残っていると、有効なトークンを持っていても
    # 401 で落ちるため、トークンがあるときは API キーを環境から外して渡す。
    env = os.environ.copy()
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("CLAUDE_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)

    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=900,
            env=env,
        )
    except subprocess.TimeoutExpired:
        if verbose:
            print("   ⚠️  Claude Code CLI がタイムアウトしました")
        return None
    except Exception as e:
        if verbose:
            print(f"   ⚠️  Claude Code CLI の実行に失敗しました: {e}")
        return None

    if proc.returncode != 0:
        if verbose:
            # stdout が JSON なら result（人間向けのエラー文）を取り出して全文出す。
            # 生 JSON の先頭だけでは原因が分からない。
            detail = ""
            try:
                w = json.loads(proc.stdout)
                detail = str(w.get("result", ""))
            except Exception:
                detail = (proc.stdout or "").strip()
            stderr = (proc.stderr or "").strip()
            print(f"   ⚠️  Claude Code CLI がエラーを返しました（exit {proc.returncode}）")
            if detail:
                print(f"      result: {detail[:600]}")
            if stderr:
                print(f"      stderr: {stderr[:600]}")
        return None

    try:
        wrapper = json.loads(proc.stdout)
    except json.JSONDecodeError:
        wrapper = {"result": proc.stdout}

    if wrapper.get("is_error"):
        if verbose:
            print(f"   ⚠️  Claude Code CLI が失敗を報告しました: {str(wrapper.get('result'))[:200]}")
        return None

    data = _extract_json(wrapper.get("result", ""))
    if data is None:
        if verbose:
            print("   ⚠️  CLI の応答から JSON を取り出せませんでした")
        return None

    if verbose:
        usage = wrapper.get("usage") or {}
        if usage:
            print(f"   使用トークン: 入力 {usage.get('input_tokens', 0):,} / "
                  f"出力 {usage.get('output_tokens', 0):,}（サブスクリプション枠）")

    return data


def curate(articles: List[Dict], verbose: bool = True) -> Optional[Dict]:
    """記事を選別して日本語化する。

    Returns:
        {"overview": [3行], "categorized": {category: [記事…]}} 形式。
        利用できない場合は None（呼び出し側は従来処理にフォールバックする）。
    """
    if not articles:
        return None

    cfg = _config()
    if not cfg.get("enabled", True):
        if verbose:
            print("   キュレーションは設定で無効化されています")
        return None

    min_n = int(cfg.get("min_articles", DEFAULT_MIN))
    max_n = int(cfg.get("max_articles", DEFAULT_MAX))
    backend = cfg.get("backend", "auto")

    # サブスクリプション枠（Claude Code CLI）を優先し、API を予備にする。
    # backend: "claude-code" = CLI のみ / "api" = API のみ / "auto" = CLI → API の順
    if backend in ("auto", "claude-code"):
        data = _curate_via_cli(articles, cfg, min_n, max_n, verbose)
        if data is not None:
            result = _assemble(data, articles, verbose)
            if result is not None:
                return result
        if backend == "claude-code":
            if verbose:
                print("   ⚠️  CLI バックエンドが使えませんでした（従来処理で続行）")
            return None
        if verbose:
            print("   CLI が使えないため API にフォールバックします")

    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if not api_key:
        if verbose:
            print("   ⚠️  ANTHROPIC_API_KEY も未設定のためキュレーションをスキップします")
        return None

    model = cfg.get("model", DEFAULT_MODEL)

    try:
        import anthropic
    except ImportError:
        if verbose:
            print("   ⚠️  anthropic パッケージが見つかりません（pip install anthropic）")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_message(articles, min_n, max_n)}],
            output_config={
                "effort": cfg.get("effort", "medium"),
                "format": {"type": "json_schema", "schema": CURATION_SCHEMA},
            },
        )
    except Exception as e:
        if verbose:
            print(f"   ⚠️  キュレーションに失敗しました（従来処理で続行）: {e}")
        return None

    if getattr(response, "stop_reason", None) == "refusal":
        if verbose:
            print("   ⚠️  モデルが応答を拒否しました（従来処理で続行）")
        return None

    try:
        text = next(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
    except Exception as e:
        if verbose:
            print(f"   ⚠️  応答を解釈できませんでした（従来処理で続行）: {e}")
        return None

    _record_usage(response, model, verbose)
    return _assemble(data, articles, verbose)


def _record_usage(response, model: str, verbose: bool):
    """API 使用量を記録して、コストダッシュボードに反映させる。"""
    try:
        import api_cost_calculator
        api_cost_calculator.record_anthropic_usage(
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            purpose="ニュースの選別・日本語化",
        )
        if verbose:
            print(f"   使用トークン: 入力 {response.usage.input_tokens:,} / "
                  f"出力 {response.usage.output_tokens:,}")
    except Exception:
        pass


def _assemble(data: Dict, articles: List[Dict], verbose: bool) -> Optional[Dict]:
    """モデルの出力を元記事とつき合わせて、既存の categorized 形式に組み立てる。"""
    picked = data.get("articles", [])
    if not picked:
        if verbose:
            print("   ⚠️  掲載対象が0件でした（従来処理で続行）")
        return None

    categorized: Dict[str, List[Dict]] = {c: [] for c in CATEGORIES}
    seen = set()

    for item in picked:
        idx = item.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(articles)) or idx in seen:
            continue  # モデルが存在しない番号を返した場合に備える
        seen.add(idx)

        src = articles[idx]
        category = _normalize_category(item.get("category"))
        if category is None:
            if verbose:
                print(f"   ⚠️  未知のカテゴリ {item.get('category')!r} → research に振り分け")
            category = "research"
        categorized[category].append({
            "title_en": src.get("title", ""),
            "title_ja": str(item.get("title_ja", "")).strip(),
            "summary": str(item.get("summary", "")).strip(),
            "category": category,
            "importance": max(1, min(3, int(item.get("importance", 2)))),
            "source": _source_name(src),
            "url": src.get("url", ""),
            "date": _article_date(src),
        })

    total = sum(len(v) for v in categorized.values())
    if total == 0:
        return None

    _merge_new_terms(data.get("new_terms", []), verbose)

    overview = [s.strip() for s in data.get("overview", []) if s and s.strip()]
    if verbose:
        print(f"   ✓ {len(articles)} 件 → {total} 件に選別しました")
        for c in CATEGORIES:
            if categorized[c]:
                print(f"      {c}: {len(categorized[c])} 件")

    return {"overview": overview, "categorized": categorized}


_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _merge_new_terms(new_terms: List[Dict], verbose: bool = True) -> int:
    """モデルが見つけた新出用語を glossary.json に追記する。

    毎日のニュースから用語集がひとりでに育つ仕組み。用語ページはニュースと違って
    古びないため、これが検索流入の資産として積み上がっていく。
    """
    if not new_terms:
        return 0
    try:
        import glossary
    except Exception:
        return 0

    cfg = monetize.load_config().get("glossary", {})
    if not cfg.get("auto_discover", True):
        return 0

    data = glossary.load()
    existing_slugs = {t["slug"] for t in data.get("terms", [])}
    existing_names = {n.lower() for t in data.get("terms", [])
                      for n in [t.get("term", "")] + t.get("aliases", []) if n}

    added = []
    for item in new_terms:
        slug = _SLUG_RE.sub("-", str(item.get("slug", "")).lower()).strip("-")
        name = str(item.get("term", "")).strip()
        if not slug or not name or slug in existing_slugs or name.lower() in existing_names:
            continue
        if not str(item.get("short", "")).strip():
            continue
        data.setdefault("terms", []).append({
            "slug": slug,
            "term": name,
            "reading": str(item.get("reading", "")).strip(),
            "aliases": [a for a in item.get("aliases", []) if isinstance(a, str) and a.strip()],
            "category": item.get("category", "基礎"),
            "short": item["short"].strip(),
            "detail": str(item.get("detail", "")).strip(),
            "related": [],
            "status": "published",
            "auto": True,   # 自動追加であることを残す（あとで人が見直せるように）
        })
        existing_slugs.add(slug)
        existing_names.add(name.lower())
        added.append(name)

    if added:
        glossary.save(data)
        if verbose:
            print(f"   ✓ 用語集に {len(added)} 語を追加: {'、'.join(added)}")
    return len(added)


if __name__ == "__main__":
    # 実データで動作確認する（要 ANTHROPIC_API_KEY）
    import sys
    from datetime import datetime
    import generate_news

    target = datetime.now()
    if len(sys.argv) > 2 and sys.argv[1] == "--date":
        target = datetime.strptime(sys.argv[2], "%Y-%m-%d")

    raw = generate_news.fetch_rss_news(target)
    print(f"取得: {len(raw)} 件")
    result = curate(raw)
    if result:
        print("\n--- 今日の3行まとめ ---")
        for line in result["overview"]:
            print(f"  ・{line}")
        print("\n--- 掲載記事 ---")
        for cat, items in result["categorized"].items():
            for a in items:
                print(f"  [{cat}] {'★' * a['importance']} {a['title_ja']}")
                print(f"        {a['summary']}")
