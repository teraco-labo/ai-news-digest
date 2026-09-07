#!/usr/bin/env python3
"""
サブスクAPIチェッカー（受信箱の見張り） — 毎朝、新しい課金を勝手に見つける。

Gmail の App パスワード（GMAIL_APP_PASSWORD）は SMTP 送信だけでなく IMAP 読み取りにも
使えます。日次ダイジェストのメール配信で既に登録済みの Secret をそのまま流用するので、
新しい認証情報も、ブラウザ自動化も要りません。

読むのはヘッダ（From / Subject / Date）だけです。本文は取得しないので、
「請求書が来た」という事実だけを見て、中身は覗きません。
既読フラグも立てません（BODY.PEEK）。

使い方:
  python billing_watch.py                    # 直近2日ぶんを見る（毎朝の実行想定）
  python billing_watch.py --days 30          # 過去30日をまとめて棚卸し
  python billing_watch.py --days 7 --notify  # 見つかったらメールで知らせる

環境変数:
  GMAIL_ADDRESS / GMAIL_APP_PASSWORD  … 未設定なら何もせず正常終了する
"""

import argparse
import email
import email.header
import imaplib
import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Dict, List, Optional

JST = timezone(timedelta(hours=9))
REPO_DIR = Path(__file__).parent
REPORT_FILE = REPO_DIR / ".billing-watch.json"
SEEN_FILE = REPO_DIR / ".billing-seen.json"

# 期限は毎日わめかず、この残り日数になったときだけ知らせる
DEADLINE_MILESTONES = (7, 3, 1, 0)

# 過ぎた期限を何日ぶん引きずるか。0日で消すと「気づいたら課金されていた」を取り逃がす
PAST_DUE_DAYS = 60

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


def load_ledger() -> Dict:
    """実データがあればそれを、無ければひな形を読む（CI では後者になる）。"""
    for name in ("service_costs.json", "service_costs.sample.json"):
        p = REPO_DIR / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"⚠️  {name} の読み込みに失敗しました: {e}")
    return {"services": [], "mail": {}}


def decode_header(raw: Optional[str]) -> str:
    if not raw:
        return ""
    out = []
    for text, enc in email.header.decode_header(raw):
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out).strip()


def fetch_headers(days: int) -> List[Dict]:
    """直近 days 日ぶんのヘッダを取る。認証情報が無ければ空を返す。"""
    user = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not password:
        print("ℹ️  GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定のため受信箱は見ません")
        return []

    since = (datetime.now(JST) - timedelta(days=days)).strftime("%d-%b-%Y")
    messages: List[Dict] = []

    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    except Exception as e:
        print(f"⚠️  IMAP に接続できませんでした: {e}")
        return []

    try:
        conn.login(user, password)
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, f'(SINCE "{since}")')
        if status != "OK":
            print(f"⚠️  検索に失敗しました: {status}")
            return []

        ids = data[0].split()
        print(f"📬 直近{days}日で {len(ids)} 通を確認します")

        for msg_id in ids:
            status, raw = conn.fetch(
                msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
            )
            if status != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])
            messages.append({
                "id": decode_header(msg.get("Message-ID")) or f"noid:{msg_id.decode()}",
                "from": decode_header(msg.get("From")),
                "subject": decode_header(msg.get("Subject")),
                "date": decode_header(msg.get("Date")),
            })
    except imaplib.IMAP4.error as e:
        # パスワードそのものは絶対にログへ出さない
        print(f"⚠️  Gmail にログインできませんでした（App パスワードを確認してください）: {type(e).__name__}")
        return []
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    return messages


def load_seen() -> Dict:
    """一度知らせたものを覚えておく台帳。毎朝2日ぶんを見るので、これが無いと同じ請求を二度知らせてしまう。"""
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            data.setdefault("messages", [])
            data.setdefault("deadlines", {})
            return data
        except Exception as e:
            print(f"⚠️  {SEEN_FILE.name} を読めませんでした（作り直します）: {e}")
    return {"messages": [], "deadlines": {}}


def save_seen(seen: Dict):
    # 件名は入れない。メールの識別子だけを、直近500件ぶん持つ
    seen["messages"] = seen["messages"][-500:]
    try:
        SEEN_FILE.write_text(
            json.dumps(seen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️  {SEEN_FILE.name} を保存できませんでした: {e}")


def looks_like_billing(msg: Dict, signals: List[str]) -> bool:
    haystack = (msg["subject"] + " " + msg["from"]).lower()
    return any(sig.lower() in haystack for sig in signals)


def sender_ignored(msg: Dict, ignore: List[str]) -> bool:
    sender = msg["from"].lower()
    return any(pat.lower() in sender for pat in ignore)


def match_service(msg: Dict, services: List[Dict]) -> Optional[Dict]:
    haystack = (msg["from"] + " " + msg["subject"]).lower()
    for svc in services:
        for pat in svc.get("mail_match", []):
            if pat.lower() in haystack:
                return svc
    return None


def sender_domain(sender: str) -> str:
    m = re.search(r"@([\w.-]+)", sender)
    return m.group(1).lower() if m else sender.lower()


def scan(days: int, seen: Dict = None) -> Dict:
    """seen を渡すと、初めて見たものに is_new / is_due の印がつく。"""
    seen = seen if seen is not None else {"messages": [], "deadlines": {}}
    seen_ids = set(seen.get("messages", []))
    ledger = load_ledger()
    mail_cfg = ledger.get("mail", {})
    signals = mail_cfg.get("billing_signals", [])
    ignore = mail_cfg.get("ignore_senders", [])
    services = ledger.get("services", [])

    messages = fetch_headers(days)
    known: Dict[str, List[Dict]] = {}
    unknown: Dict[str, List[Dict]] = {}

    for msg in messages:
        if not looks_like_billing(msg, signals):
            continue
        if sender_ignored(msg, ignore):
            continue
        msg["is_new"] = msg["id"] not in seen_ids
        svc = match_service(msg, services)
        if svc:
            known.setdefault(svc["name"], []).append(msg)
        else:
            unknown.setdefault(sender_domain(msg["from"]), []).append(msg)

    # 台帳側の期限チェック（メールが来なくても効く）
    today = datetime.now(JST).date()
    deadlines = []
    for svc in services:
        if svc.get("status") in ("unused", "cancelled"):
            continue
        for field, label in (("trial_ends", "無料体験の終了"), ("next_charge", "次回請求")):
            raw = svc.get(field)
            if not raw:
                continue
            # 体験終了日と次回請求日が同じなら、意味が濃い「体験終了」だけ出す
            if field == "next_charge" and raw == svc.get("trial_ends"):
                continue
            try:
                d = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue

            left = (d - today).days
            if left > 7 or left < -PAST_DUE_DAYS:
                continue

            # 過ぎた期限こそ一番危ない。黙って消さず、超過として出し続ける。
            # 「気づいたときには課金が始まっていた」を防ぐのがこの道具の仕事なので。
            overdue = left < 0
            milestone = -1 if overdue else next(
                (m for m in DEADLINE_MILESTONES if left >= m), None
            )
            key = f"{svc['id']}:{field}:{raw}"
            already = seen.get("deadlines", {}).get(key)
            deadlines.append({
                "service": svc["name"], "what": label, "date": raw,
                "days_left": left, "overdue": overdue,
                "key": key, "milestone": milestone,
                "is_due": milestone is not None and already != milestone,
            })

    new_messages = sum(
        1 for group in (known, unknown) for msgs in group.values()
        for m in msgs if m.get("is_new")
    )

    return {
        "new_messages": new_messages,
        "scanned_at": datetime.now(JST).isoformat(timespec="seconds"),
        "days": days,
        "messages_checked": len(messages),
        "known": known,
        "unknown": unknown,
        "deadlines": sorted(deadlines, key=lambda x: (not x["overdue"], x["days_left"])),
    }


def format_report(result: Dict) -> str:
    lines = []
    if result["unknown"]:
        lines.append("🔴 台帳に無い課金メールが届いています")
        for domain, msgs in result["unknown"].items():
            fresh = sum(1 for m in msgs if m.get("is_new"))
            lines.append(f"  {domain}（{len(msgs)}通" + (f" / 新着{fresh}" if fresh else "") + "）")
            for m in msgs[:3]:
                lines.append(f"    {'🆕' if m.get('is_new') else '  '} {m['subject']}")
        lines.append("")
    overdue = [d for d in result["deadlines"] if d.get("overdue")]
    upcoming = [d for d in result["deadlines"] if not d.get("overdue")]
    if overdue:
        lines.append("🔴 期限を過ぎています")
        for d in overdue:
            mark = "🆕" if d.get("is_due") else "  "
            lines.append(f"  {mark} {d['service']}: {d['what']}（{d['date']}）から {-d['days_left']} 日経過。"
                         f"手を打っていなければ課金が始まっています")
        lines.append("")
    if upcoming:
        lines.append("🟡 期限が近いもの")
        for d in upcoming:
            mark = "🆕" if d.get("is_due") else "  "
            lines.append(f"  {mark} {d['service']}: {d['what']} まであと {d['days_left']} 日（{d['date']}）")
        lines.append("")
    if result["known"]:
        lines.append("● 既知のサービスからの請求")
        for name, msgs in result["known"].items():
            fresh = sum(1 for m in msgs if m.get("is_new"))
            lines.append(f"  {name}（{len(msgs)}通" + (f" / 新着{fresh}" if fresh else "") + "）")
        lines.append("")
    if not lines:
        lines.append("✅ 新しい課金は見つかりませんでした")
    return "\n".join(lines)


def newsworthy(result: Dict) -> Dict:
    """知らせる価値があるものだけを抜き出す。既に知らせたものは黙って落とす。"""
    unknown = {}
    for domain, msgs in result["unknown"].items():
        fresh = [m for m in msgs if m.get("is_new")]
        if fresh:
            unknown[domain] = fresh
    due = [d for d in result["deadlines"] if d.get("is_due")]
    return {"unknown": unknown, "deadlines": due}


def notify(result: Dict) -> str:
    """'sent' / 'skipped'（知らせるものが無い） / 'failed' を返す。"""
    news = newsworthy(result)
    if not news["unknown"] and not news["deadlines"]:
        return "skipped"

    user = os.getenv("GMAIL_ADDRESS")
    password = os.getenv("GMAIL_APP_PASSWORD")
    if not user or not password:
        return "skipped"

    parts = []
    if news["unknown"]:
        parts.append("台帳に無い課金メールが届いています。")
        for domain, msgs in news["unknown"].items():
            parts.append(f"\n■ {domain}")
            for m in msgs:
                parts.append(f"  ・{m['subject']}")
        parts.append("")
    if news["deadlines"]:
        parts.append("期限のお知らせです。")
        for d in news["deadlines"]:
            if d.get("overdue"):
                parts.append(f"  ・{d['service']}: {d['what']}（{d['date']}）を {-d['days_left']} 日過ぎています")
            else:
                parts.append(f"  ・{d['service']}: {d['what']} まであと {d['days_left']} 日（{d['date']}）")
        parts.append("")

    if news["unknown"]:
        subject = f"【サブスクAPIチェッカー】台帳に無い課金 {len(news['unknown'])} 件"
    elif any(d.get("overdue") for d in news["deadlines"]):
        subject = "【サブスクAPIチェッカー】期限を過ぎているものがあります"
    else:
        soonest = min(d["days_left"] for d in news["deadlines"])
        subject = f"【サブスクAPIチェッカー】期限まであと {soonest} 日"

    msg = MIMEText(
        "\n".join(parts)
        + "\n台帳: https://claude.ai/code/artifact/2d12e881-53f5-492a-b8e8-0d6fdfbbcd46\n",
        "plain", "utf-8"
    )
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = "fujisaki@teraco-labo.com"

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(user, password)
            server.send_message(msg)
        print(f"📧 通知しました: {subject}")
        return "sent"
    except smtplib.SMTPException as e:
        print(f"⚠️  通知メールを送れませんでした: {type(e).__name__}")
        return "failed"


def push_to_teraco_money(result: Dict) -> str:
    """
    見つけたものを teraco.money の台帳へ送る。'sent' / 'skipped' / 'failed'。

    SUBSCHECK_URL（例: https://teraco-money.vercel.app）と SYNC_TOKEN があるときだけ動く。
    既知のサービスからの請求も送る（「最後に見た日」の更新に使われる）。
    未知の送信元は、向こうで「確認待ちの課金の気配」として画面に出る。
    reconcile=true で、仕訳との照合も一緒に走らせる（毎朝の取込の後なので都合がいい）。
    """
    base = os.getenv("SUBSCHECK_URL", "").rstrip("/")
    token = os.getenv("SYNC_TOKEN", "")
    if not base or not token:
        return "skipped"

    ledger = load_ledger()
    services = ledger.get("services", [])
    name_to_key = {s.get("name"): s.get("id") for s in services}

    signals: List[Dict] = []
    for name, msgs in result["known"].items():
        for m in msgs:
            signals.append({
                "kind": "EMAIL_KNOWN", "matchKey": name_to_key.get(name),
                "source": m["from"], "subject": m["subject"],
                "observedAt": _iso(m.get("date")), "externalId": m["id"],
            })
    for domain, msgs in result["unknown"].items():
        for m in msgs:
            signals.append({
                "kind": "EMAIL_UNKNOWN", "source": domain, "subject": m["subject"],
                "observedAt": _iso(m.get("date")), "externalId": m["id"],
            })

    import urllib.request
    import urllib.error
    payload = json.dumps({"signals": signals, "reconcile": True}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/sync/subscriptions", data=payload, method="POST",
        headers={"Content-Type": "application/json", "x-sync-token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = json.loads(res.read().decode("utf-8") or "{}")
        rec = body.get("reconcile") or {}
        print(f"☁️  teraco.money へ送りました: 追加 {body.get('inserted', 0)} / 重複 {body.get('skipped', 0)}"
              f" / 既知に紐づけ {body.get('linked', 0)}"
              + (f" / 仕訳照合 {rec.get('matched', 0)} 件・候補 {rec.get('candidates', 0)} 件" if rec else ""))
        return "sent"
    except urllib.error.HTTPError as e:
        print(f"⚠️  teraco.money が {e.code} を返しました（SYNC_TOKEN を確認）")
        return "failed"
    except Exception as e:
        print(f"⚠️  teraco.money へ送れませんでした: {type(e).__name__}")
        return "failed"


def _iso(date_header: Optional[str]) -> str:
    """メールの Date ヘッダを ISO 8601 に。読めなければ今"""
    if date_header:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_header).isoformat()
        except Exception:
            pass
    return datetime.now(JST).isoformat()


def record(result: Dict, seen: Dict):
    """知らせ終わったものを既読にする。次の朝に同じことを言わないため。"""
    for group in (result["known"], result["unknown"]):
        for msgs in group.values():
            for m in msgs:
                if m["id"] not in seen["messages"]:
                    seen["messages"].append(m["id"])
    for d in result["deadlines"]:
        if d.get("milestone") is not None:
            seen["deadlines"][d["key"]] = d["milestone"]
    save_seen(seen)


def main() -> int:
    ap = argparse.ArgumentParser(description="サブスクAPIチェッカー — 受信箱から新しい課金を見つける")
    ap.add_argument("--days", type=int, default=2, help="さかのぼる日数（既定 2）")
    ap.add_argument("--notify", action="store_true", help="新しいものが見つかったらメールで知らせる")
    ap.add_argument("--fresh", action="store_true",
                    help="既読を無視して全部を新着として扱う（棚卸し用）")
    args = ap.parse_args()

    seen = {"messages": [], "deadlines": {}} if args.fresh else load_seen()
    result = scan(args.days, seen)
    print()
    print(format_report(result))

    try:
        REPORT_FILE.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️  記録の保存に失敗しました: {e}")

    # teraco.money に台帳があるなら、そちらが正。メール通知は補助になる
    pushed = push_to_teraco_money(result)

    if args.notify:
        outcome = notify(result)
        if outcome in ("sent", "skipped") and pushed != "failed":
            record(result, seen)
        else:
            # 送れなかったものは既読にしない。明日もう一度知らせる
            print("ℹ️  通知か同期ができなかったので既読にしません（次回また知らせます）")

    # 毎朝のワークフローを止めたくないので、見つかっても 0 で返す
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # `| head` などで打ち切られたときに醜い traceback を出さない
        sys.exit(0)
