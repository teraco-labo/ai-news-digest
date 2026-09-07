#!/usr/bin/env python3
"""
desktop/ の部品から macOS の .app を組み立てて zip にする。

Finder に置くアイコンの実体は「決まった形のフォルダ」なので、
macOS が無くても組み立てられます。zip にするのは実行権限を保つためです。

使い方:
  python desktop/build_app.py [出力先ディレクトリ]
"""

import os
import plistlib
import stat
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).parent
APP_NAME = "サブスクAPIチェッカー"
EXEC_NAME = "subscheck"

README = """サブスクAPIチェッカー
====================

## 置きかた

1. 「{app}.app」をアプリケーションフォルダか、好きな場所に置く
2. Dock かデスクトップにドラッグする（エイリアスを作るなら option+command を押しながら）

## 初回だけ必要な操作

インターネット経由で受け取ったアプリなので、macOS が最初の1回だけ止めます。

  ダブルクリックではなく「右クリック → 開く」→ ダイアログで「開く」

これで以降は普通にダブルクリックで起動します。
うまくいかないときはターミナルで次を実行してください。

  xattr -dr com.apple.quarantine "{app}.app"

## 台帳の場所を教える

台帳（service_costs.json のあるフォルダ）を自動で探しますが、
見つからないと言われたら、次のファイルにパスを1行書いてください。

  echo "$HOME/teraco-labo-website" > ~/.subscheck-repo

## 起動すると何が起きるか

1. 手元の台帳を点検する
2. 要対応（赤）があればダイアログで止める。黄色は通知で知らせる
3. チェッカー本体をブラウザで開く

台帳が読めなくても、本体は必ず開きます。
""".format(app=APP_NAME)


def build(out_dir: Path) -> int:
    icns = HERE / "icon.icns"
    launcher = HERE / "launcher.sh"
    plist = HERE / "Info.plist"
    for f in (icns, launcher, plist):
        if not f.exists():
            print(f"❌ {f.name} がありません")
            return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    app = out_dir / f"{APP_NAME}.app"
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)

    (app / "Contents" / "Info.plist").write_bytes(plist.read_bytes())
    (app / "Contents" / "PkgInfo").write_text("APPL????", encoding="ascii")
    (res / "icon.icns").write_bytes(icns.read_bytes())

    binary = macos / EXEC_NAME
    binary.write_text(launcher.read_text(encoding="utf-8"), encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    (out_dir / "はじめにお読みください.txt").write_text(README, encoding="utf-8")

    # zip にする。実行権限は外部属性に載せないと Finder で起動できなくなる
    zip_path = out_dir / f"{APP_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(app.rglob("*")):
            if not path.is_file():
                continue
            arc = path.relative_to(out_dir)
            info = zipfile.ZipInfo(str(arc))
            mode = path.stat().st_mode
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
        z.write(out_dir / "はじめにお読みください.txt", "はじめにお読みください.txt")

    print(f"✅ {app.name}")
    print(f"✅ {zip_path.name} ({zip_path.stat().st_size:,} バイト)")
    print(f"   実行ビット: {oct(binary.stat().st_mode & 0o777)}")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "build"
    sys.exit(build(target))
