#!/usr/bin/env python3
"""
icon.svg から描き出した PNG を macOS の .icns にまとめる。

iconutil は macOS にしか無いので、ICNS の構造（4バイトの型 + 長さ + PNG 本体）を
そのまま組み立てています。どの環境でも動きます。

使い方:
  python desktop/build_icns.py <PNGの置き場> <出力先.icns>
"""

import struct
import sys
from pathlib import Path

# 型と、その型が期待する一辺のピクセル数
SLOTS = [
    ("icp4", 16), ("icp5", 32), ("icp6", 64),
    ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024),
    ("ic11", 32),   # 16pt @2x
    ("ic12", 64),   # 32pt @2x
    ("ic13", 256),  # 128pt @2x
    ("ic14", 512),  # 256pt @2x
]


def build(png_dir: Path, out: Path) -> int:
    chunks = []
    for kind, size in SLOTS:
        src = png_dir / f"icon_{size}.png"
        if not src.exists():
            print(f"⚠️  {src.name} が無いので {kind} は入れません")
            continue
        data = src.read_bytes()
        chunks.append(kind.encode("ascii") + struct.pack(">I", len(data) + 8) + data)

    if not chunks:
        print("❌ PNG が1枚も見つかりませんでした")
        return 1

    body = b"".join(chunks)
    out.write_bytes(b"icns" + struct.pack(">I", len(body) + 8) + body)
    print(f"✅ {out.name} ({len(chunks)} サイズ / {out.stat().st_size:,} バイト)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    sys.exit(build(Path(sys.argv[1]), Path(sys.argv[2])))
