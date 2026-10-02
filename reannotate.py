#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公開済みの記事ページに、いまの用語集で注釈を付け直す。

用語集に語を足しても、すでに公開したページには反映されない。記事の中身は変えずに、
見出し・3行まとめ・本文の注釈だけを作り直す。

  python3 reannotate.py ai-news-2026-10-02.html          1ページ
  python3 reannotate.py --days 7                          直近7日ぶん
"""
import json
import re
import sys
from pathlib import Path

import glossary
import monetize

HERE = Path(__file__).resolve().parent
SPAN = re.compile(r'<span class="t" data-t="[^"]*"[^>]*>(.*?)</span>', re.S)
# 注釈を付ける場所（本文の記事カードと冒頭の3行まとめ）
TARGET = re.compile(r'(<(div|li|p) class="(card-title-ja|card-body)"[^>]*>)(.*?)(</\2>)', re.S)
LEAD = re.compile(r'<div class="lead">.*?</ol>', re.S)
LI = re.compile(r'(<li>)(.*?)(</li>)', re.S)
PAYLOAD = re.compile(r'<script type="application/json" id="glossary-data">.*?</script>\n?', re.S)


def redo(path: Path) -> tuple:
    s = path.read_text(encoding="utf-8")
    before = len(set(re.findall(r'data-t="([^"]+)"', s)))
    gcfg = monetize.load_config().get("glossary", {})
    ann = glossary.Annotator(limit=int(gcfg.get("max_marks_per_page", 60)))
    s = SPAN.sub(r"\1", s)                                   # いったん注釈を外す
    # 先に「今日の3行まとめ」（ページの最初に読まれる場所なので、初出の注釈をここに付ける）
    def lead(m):
        return LI.sub(lambda li: li.group(1) + ann(li.group(2)) + li.group(3), m.group(0))
    s = LEAD.sub(lead, s, count=1)
    s = TARGET.sub(lambda m: m.group(1) + ann(m.group(4)) + m.group(5), s)
    s = PAYLOAD.sub(ann.payload(), s, count=1)
    path.write_text(s, encoding="utf-8")
    return before, len(ann.used)


def main():
    if "--days" in sys.argv:
        n = int(sys.argv[sys.argv.index("--days") + 1])
        pages = sorted(HERE.glob("ai-news-20*.html"))[-n:]
    else:
        pages = [HERE / a for a in sys.argv[1:]]
    for p in pages:
        b, a = redo(p)
        print(f"  {p.name}: 注釈 {b} 語 → {a} 語")


if __name__ == "__main__":
    main()
