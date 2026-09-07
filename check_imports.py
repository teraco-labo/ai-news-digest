#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎朝の処理で使うファイルが、全部ちゃんと読み込めるかを確かめる。

名前を変えたり消したりしたとき、それを使っている別のファイルを直し忘れると、
その場では気づかず、翌朝の自動処理で初めて止まる（2026-09-08 に実際に起きた。
COVER_URL を関数に変えたが、読み込んでいた側を直し忘れて音声が作られなかった）。

  python3 check_imports.py     # 全部OKなら「異常なし」。1つでも駄目なら終了コード1
"""
import importlib
import sys
from pathlib import Path

MODULES = [
    "generate_news", "generate_podcast", "generate_podcast_dialogue",
    "glossary", "seo_builder", "digest_page", "player_page", "site_theme",
    "monetize", "article_builder", "newsletter", "curate",
]

sys.path.insert(0, str(Path(__file__).resolve().parent))
ng = []
for name in MODULES:
    try:
        importlib.import_module(name)
    except Exception as e:
        ng.append(f"  {name}: {type(e).__name__}: {e}")

if ng:
    print("読み込めないファイルがあります:")
    print("\n".join(ng))
    sys.exit(1)
print(f"異常なし（{len(MODULES)} 件）")
