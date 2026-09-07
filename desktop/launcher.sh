#!/bin/bash
# サブスクAPIチェッカー — ダブルクリックで起動する入口。
#
# やること:
#   1. 手元の台帳を点検して、要対応があれば知らせる
#   2. チェッカー本体（Web）を開く
#
# 台帳（service_costs.json）が見つからなくても、本体は必ず開きます。

set -uo pipefail

# 台帳の本体は teraco.money に統合した（2026-09）。ここを開けば最新が出る
APP_URL="https://teraco-money.vercel.app/advice/subscriptions"
TITLE="サブスクAPIチェッカー"

# osascript に渡す前に、引用符とバックスラッシュを潰しておく
esc() {
  local s=${1//\\/\\\\}
  s=${s//\"/\\\"}
  s=${s//$'\n'/ / }
  printf '%s' "$s"
}

notify() {
  /usr/bin/osascript -e "display notification \"$(esc "$2")\" with title \"$TITLE\" subtitle \"$(esc "$1")\"" >/dev/null 2>&1
}

# 赤（要対応）は通知だと流れてしまうので、前面のダイアログで止める
alert() {
  /usr/bin/osascript >/dev/null 2>&1 <<EOF
tell application "System Events"
  activate
  display dialog "$(esc "$1")" with title "$TITLE" buttons {"OK"} default button 1 with icon caution
end tell
EOF
}

# --- 台帳のある場所を探す -------------------------------------------------
# 引っ越しても動くように、~/.subscheck-repo に書いたパスを最優先で見る
REPO=""
CANDIDATES=()
[ -f "$HOME/.subscheck-repo" ] && CANDIDATES+=("$(cat "$HOME/.subscheck-repo")")
CANDIDATES+=(
  "$HOME/teraco-labo-website"
  "$HOME/Documents/GitHub/ai-news-digest"
  "$HOME/Documents/Claude/ai-news-repo"
)
for d in "${CANDIDATES[@]}"; do
  if [ -n "$d" ] && [ -f "$d/service_costs.py" ]; then
    REPO="$d"
    break
  fi
done

# --- 本体を開く（何があっても必ず通る） -----------------------------------
/usr/bin/open "$APP_URL"

# --- 手元の台帳を点検する -------------------------------------------------
if [ -z "$REPO" ]; then
  notify "台帳は読めませんでした" "リポジトリの場所を ~/.subscheck-repo に書いてください"
  exit 0
fi

PY="python3"
[ -x "$REPO/venv/bin/python3" ] && PY="$REPO/venv/bin/python3"
if ! command -v "$PY" >/dev/null 2>&1 && [ ! -x "$PY" ]; then
  notify "台帳は読めませんでした" "python3 が見つかりません"
  exit 0
fi

cd "$REPO" || exit 0
OUTPUT=$("$PY" service_costs.py check 2>&1)

DANGER=$(printf '%s\n' "$OUTPUT" | grep '^🔴' | head -3)
WARN=$(printf '%s\n' "$OUTPUT"   | grep '^🟡' | head -2)

if [ -n "$DANGER" ]; then
  alert "$DANGER"
elif [ -n "$WARN" ]; then
  notify "要確認" "$WARN"
else
  notify "異常なし" "期限が近いものはありません"
fi

exit 0
