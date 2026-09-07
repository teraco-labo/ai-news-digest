#!/usr/bin/env python3
"""
サブスクAPIチェッカー（台帳） — 「何を使っていて、どこにいくら払っているか」を1枚で見る。

金額がゼロのものも載せます。無料で使っているツールこそ、あとから有料プランへ
誘導されて課金が始まる入口だからです。

前払いクレジット制のものは、残高と自動リチャージの ON/OFF も持ちます。
自動リチャージが ON のまま放置された前払い残高は、請求が来るまで誰も気づけません。

api_cost_calculator.py が扱うのは *このリポジトリのコードが呼んだ API* の従量課金だけです。
実際に財布から出ていくお金には、コードが一切関与しないもの（サブスク、前払いクレジット、
無料体験からの自動移行）が混ざります。fal のように「コードは呼んでいないのに請求が来る」
のはこの型です。そこを取りこぼさないための台帳が service_costs.json です。

使い方:
  python service_costs.py report            # 全サービスと月額合計
  python service_costs.py check             # 直近で危ないものだけ（cron向け・要対応なら exit 1）
  python service_costs.py add --id elevenlabs --name ElevenLabs --amount 5 --currency USD \
                              --category "AI API" --dashboard https://elevenlabs.io/app/subscription
"""

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

JST = timezone(timedelta(hours=9))
REPO_DIR = Path(__file__).parent
CONFIG_FILE = REPO_DIR / "service_costs.json"
SAMPLE_FILE = REPO_DIR / "service_costs.sample.json"

# 何日前から警告するか
TRIAL_WARN_DAYS = 14
CHARGE_WARN_DAYS = 7

STATUS_LABEL = {
    "active": "稼働中",
    "trial": "無料体験中",
    "watch": "要確認",
    "unused": "未使用",
    "cancelled": "解約済み",
}

CYCLE_LABEL = {"monthly": "毎月", "yearly": "毎年", "one_time": "都度"}

BILLING_LABEL = {
    "subscription": "サブスク", "prepaid": "前払いクレジット",
    "usage": "従量課金", "free": "無料", "included": "枠内",
}

# お金が出ていかない型。金額未確認の催促はしない
NO_COST = ("free", "included")

# 残高を持つ型。ここは残高と自動リチャージも見張る
CHARGE_LIKE = ("prepaid", "usage")

RECHARGE_LABEL = {
    "on": "自動リチャージ ON", "off": "自動リチャージ OFF",
    "off?": "自動リチャージ OFF（推定）", "unknown": "自動リチャージ 未確認",
}

# 残高をいつ確認したか。これより古いと数字を信用しない
BALANCE_STALE_DAYS = 30

# 為替をいつ更新したか。これより古いとドル建てが信用できない
RATE_STALE_DAYS = 14

# 月額合計に数えるステータス
COUNTED = ("active", "trial", "watch")


def today_jst() -> date:
    return datetime.now(JST).date()


def load_config() -> Dict:
    # 実データは .gitignore 済み（公開リポジトリに金額を出さないため）。
    # 手元に無ければひな形から起こす。
    if not CONFIG_FILE.exists() and SAMPLE_FILE.exists():
        CONFIG_FILE.write_text(SAMPLE_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        print("📋 service_costs.sample.json から service_costs.json を作成しました。金額を埋めてください")

    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️  service_costs.json の読み込みに失敗しました: {e}")
    return {"jpy_per_usd": 150, "monthly_budget_jpy": 0, "services": []}


def save_config(cfg: Dict):
    CONFIG_FILE.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def to_jpy(amount: Optional[float], currency: str, rate: float, fee_pct: float = 0.0) -> Optional[float]:
    """ドル建てはカードの海外事務手数料を乗せないと、実際の引き落とし額に合わない。"""
    if amount is None:
        return None
    if currency.upper() != "USD":
        return float(amount)
    return float(amount) * rate * (1 + fee_pct / 100.0)


def monthly_jpy(svc: Dict, rate: float, fee_pct: float = 0.0) -> Optional[float]:
    """月あたりに均した円。一度きりの支払いは 0（合計を膨らませないため）。"""
    jpy = to_jpy(svc.get("amount"), svc.get("currency", "JPY"), rate, fee_pct)
    if jpy is None:
        return None
    cycle = svc.get("cycle", "monthly")
    if cycle == "yearly":
        return jpy / 12
    if cycle == "one_time":
        return 0.0
    return jpy


def parse_day(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def summarize(cfg: Dict = None) -> Dict:
    cfg = cfg or load_config()
    rate = float(cfg.get("jpy_per_usd", 150))
    fee = float(cfg.get("fx_fee_pct", 0))
    rows: List[Dict] = []
    total = 0.0
    unknown = 0

    for svc in cfg.get("services", []):
        jpy = monthly_jpy(svc, rate, fee)
        counted = svc.get("status") in COUNTED
        if counted:
            if jpy is None:
                unknown += 1
            else:
                total += jpy
        rows.append({**svc, "monthly_jpy": jpy, "counted": counted})

    rows.sort(key=lambda r: (r["monthly_jpy"] is None, -(r["monthly_jpy"] or 0)))
    return {
        "rate": rate,
        "fee_pct": fee,
        "rate_updated_at": cfg.get("jpy_per_usd_updated_at"),
        "rows": rows,
        "monthly_total_jpy": round(total),
        "unknown_count": unknown,
        "budget_jpy": cfg.get("monthly_budget_jpy", 0),
    }


def alerts(cfg: Dict = None, today: date = None) -> List[Dict]:
    """要対応のものを重い順に返す。level: danger / warn / info"""
    cfg = cfg or load_config()
    today = today or today_jst()
    rate = float(cfg.get("jpy_per_usd", 150))
    fee = float(cfg.get("fx_fee_pct", 0))
    out: List[Dict] = []

    # 為替が古いと、ドル建ての行が全部ずれる
    rate_day = parse_day(cfg.get("jpy_per_usd_updated_at"))
    has_usd = any(s.get("currency") == "USD" and s.get("status") in COUNTED
                  for s in cfg.get("services", []))
    if has_usd:
        if rate_day is None:
            out.append({"level": "info", "service": "為替レート",
                        "message": f"1 USD = {rate} 円 の更新日が空。jpy_per_usd_updated_at を入れる"})
        elif (today - rate_day).days > RATE_STALE_DAYS:
            out.append({"level": "warn", "service": "為替レート",
                        "message": f"1 USD = {rate} 円 は {(today - rate_day).days} 日前の値。"
                                   f"ドル建ての金額が実際とずれている"})

    for svc in cfg.get("services", []):
        name = svc.get("name", svc.get("id", "?"))
        status = svc.get("status")
        if status in ("unused", "cancelled"):
            continue

        jpy = monthly_jpy(svc, rate)
        yen = f"{round(jpy):,}円/月" if jpy else "金額未確認"

        trial_end = parse_day(svc.get("trial_ends"))
        if status == "trial" and trial_end:
            left = (trial_end - today).days
            if left < 0:
                out.append({"level": "danger", "service": name,
                            "message": f"無料体験は {trial_end} に終了済み。{yen} の課金が始まっているはず"})
            elif left == 0:
                out.append({"level": "danger", "service": name,
                            "message": f"無料体験は今日（{trial_end}）が最終日。続けないなら今すぐ解約。放置すると {yen}"})
            elif left <= TRIAL_WARN_DAYS:
                out.append({"level": "danger", "service": name,
                            "message": f"無料体験があと {left} 日で終了（{trial_end}）。続けないなら前日までに解約。放置すると {yen}"})

        charge = parse_day(svc.get("next_charge"))
        if charge and status != "trial":
            left = (charge - today).days
            if 0 <= left <= CHARGE_WARN_DAYS:
                out.append({"level": "warn", "service": name,
                            "message": f"{left} 日後（{charge}）に次の請求。{yen}"})

        if svc.get("billing") in CHARGE_LIKE:
            out.extend(charge_alerts(svc, name, today))

        if jpy is None and status in COUNTED and svc.get("billing") not in NO_COST:
            out.append({"level": "info", "service": name,
                        "message": "金額が未確認。請求書を見て service_costs.json の amount を埋める"})

    order = {"danger": 0, "warn": 1, "info": 2}
    out.sort(key=lambda a: order[a["level"]])
    return out


def charge_alerts(svc: Dict, name: str, today: date) -> List[Dict]:
    """残高を持つサービスの見張り。ON のまま忘れられた自動リチャージが一番こわい。"""
    out = []
    where = svc.get("dashboard") or "各社の請求ページ"
    recharge = svc.get("auto_recharge", "unknown")

    if recharge == "on":
        out.append({"level": "danger", "service": name,
                    "message": f"自動リチャージが ON。残高が減るたび黙って再課金される。"
                               f"上限が要るなら {where} で設定する"})
    elif recharge in ("unknown", "off?"):
        certainty = "推定でしかない" if recharge == "off?" else "未確認"
        out.append({"level": "warn", "service": name,
                    "message": f"自動リチャージの ON/OFF が{certainty}。{where} で見て台帳に記録する"})

    balance = svc.get("balance")
    checked = parse_day(svc.get("balance_checked_at"))
    unit = svc.get("balance_currency", "USD")

    if balance is None:
        out.append({"level": "info", "service": name,
                    "message": f"残高が未確認。{where} で見て balance に書く"})
    elif checked is None:
        out.append({"level": "info", "service": name,
                    "message": f"残高 {balance} {unit} の確認日が空。balance_checked_at に日付を入れる"})
    else:
        age = (today - checked).days
        if age > BALANCE_STALE_DAYS:
            out.append({"level": "info", "service": name,
                        "message": f"残高 {balance} {unit} は {age} 日前の数字。もう当てにならない"})
        elif recharge in ("off", "off?") and float(balance) <= 2:
            out.append({"level": "warn", "service": name,
                        "message": f"残高が {balance} {unit} しかない。自動リチャージは入っていないので、"
                                   f"尽きた時点で止まる"})
    return out


# ---------------------------------------------------------------- コマンド

def cmd_report(_args: List[str]):
    s = summarize()
    print("💳 サブスクAPIチェッカー\n")

    # 課金の有無で分けて出す。無料のものも必ず載せる（有料化の入口はそこなので）
    paid, gratis, stopped = [], [], []
    for r in s["rows"]:
        if not r["counted"]:
            stopped.append(r)
        elif r.get("billing") in NO_COST:
            gratis.append(r)
        else:
            paid.append(r)

    def line(r):
        jpy = r["monthly_jpy"]
        if r.get("billing") in NO_COST:
            amount = "     ―  "
        elif not r["counted"]:
            amount = "     ―  "
        elif jpy is None:
            amount = "   不明  "
        else:
            amount = f"¥{round(jpy):>7,}"
        cycle = "都度" if r.get("cycle") == "one_time" else ("  " if r.get("billing") in NO_COST else "/月")
        mark = {"active": "●", "trial": "◐", "watch": "○"}.get(r.get("status"), "×")
        print(f"  {mark} {amount}{cycle:<3}{r.get('name','?')}")

        bits = [r.get("category", ""), BILLING_LABEL.get(r.get("billing"), r.get("billing", ""))]
        if r.get("plan"):
            bits.append(r["plan"])
        bits.append(STATUS_LABEL.get(r.get("status"), r.get("status", "")))
        print(f"        {' / '.join(b for b in bits if b)}")

        if r.get("billing") in CHARGE_LIKE:
            bal = r.get("balance")
            unit = r.get("balance_currency", "USD")
            when = r.get("balance_checked_at")
            shown = f"{bal} {unit}" + (f"（{when} 時点）" if when else "") if bal is not None else "未確認"
            print(f"        残高 {shown} / {RECHARGE_LABEL.get(r.get('auto_recharge'), '未確認')}")

        if r.get("dashboard"):
            print(f"        {r['dashboard']}")
        if r.get("note"):
            print(f"        {r['note']}")
        print()

    if paid:
        print(f"── 課金あり（{len(paid)}）──\n")
        for r in paid:
            line(r)
    if gratis:
        print(f"── 無料・枠内で使用中（{len(gratis)}）──\n")
        for r in gratis:
            line(r)
    if stopped:
        print(f"── 止めたもの（{len(stopped)}）──\n")
        for r in stopped:
            line(r)

    print(f"  月額合計: ¥{s['monthly_total_jpy']:,}"
          + (f"（金額未確認 {s['unknown_count']} 件を除く）" if s["unknown_count"] else ""))
    print(f"  使用中のサービス: {len(paid) + len(gratis)} 件（うち無料・枠内 {len(gratis)} 件）")
    print(f"  為替: 1 USD = {s['rate']} 円"
          + (f"（{s['rate_updated_at']} 時点）" if s.get("rate_updated_at") else "")
          + (f" + カード海外事務手数料 {s['fee_pct']}%" if s.get("fee_pct") else ""))
    budget = s["budget_jpy"]
    if budget:
        print(f"  予算（収益で賄いたい額）: ¥{budget:,} / 月  →  残り ¥{budget - s['monthly_total_jpy']:,}")

    a = alerts()
    if a:
        print("\n⚠️  要対応\n")
        for item in a:
            icon = {"danger": "🔴", "warn": "🟡", "info": "⚪"}[item["level"]]
            print(f"  {icon} {item['service']}: {item['message']}")


def cmd_check(_args: List[str]) -> int:
    a = alerts()
    if not a:
        print("✅ 直近で対応が必要な課金はありません")
        return 0
    for item in a:
        icon = {"danger": "🔴", "warn": "🟡", "info": "⚪"}[item["level"]]
        print(f"{icon} {item['service']}: {item['message']}")
    return 1 if any(i["level"] == "danger" for i in a) else 0


def cmd_add(args: List[str]) -> int:
    def opt(name, default=None):
        if f"--{name}" in args:
            return args[args.index(f"--{name}") + 1]
        return default

    svc_id = opt("id")
    if not svc_id:
        print("使い方: python service_costs.py add --id <ID> --name <名前> [--amount 10 --currency USD ...]")
        return 1

    cfg = load_config()
    if any(s.get("id") == svc_id for s in cfg["services"]):
        print(f"⚠️  {svc_id} はすでに登録されています")
        return 1

    amount = opt("amount")
    cfg["services"].append({
        "id": svc_id,
        "name": opt("name", svc_id),
        "category": opt("category", "AI API"),
        "billing": opt("billing", "usage"),
        "status": opt("status", "watch"),
        "amount": float(amount) if amount is not None else None,
        "currency": opt("currency", "JPY"),
        "cycle": opt("cycle", "monthly"),
        "next_charge": opt("next-charge"),
        "dashboard": opt("dashboard", ""),
        "note": opt("note", ""),
        "evidence": opt("evidence", ""),
    })
    save_config(cfg)
    print(f"✅ {svc_id} を service_costs.json に追加しました")
    return 0


# ---------------------------------------------------------------- ダッシュボード

def generate_service_costs_html() -> str:
    """dashboard_app.py に差し込むカード。api_dashboard.py から呼ばれる。"""
    s = summarize()
    a = alerts()

    html = '''<div class="card">
    <div class="card-title">💳 課金しているサービス</div>

    <div style="margin-bottom: 1.25rem; padding: 1.25rem; background: linear-gradient(135deg, #0f172a, #1e293b); border-radius: 8px; border-left: 4px solid #f472b6; text-align: center;">
      <div style="font-size: 2rem; font-weight: bold; color: #f472b6;">¥''' + f"{s['monthly_total_jpy']:,}" + '''</div>
      <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 0.4rem;">月額の固定費合計'''
    if s["unknown_count"]:
        html += f"（金額未確認 {s['unknown_count']} 件を除く）"
    html += '''</div>
    </div>'''

    if a:
        html += '''
    <div style="margin-bottom: 1.25rem; display: grid; gap: 0.5rem;">'''
        for item in a:
            color = {"danger": "#ef4444", "warn": "#f59e0b", "info": "#64748b"}[item["level"]]
            icon = {"danger": "🔴", "warn": "🟡", "info": "⚪"}[item["level"]]
            html += f'''
      <div style="padding: 0.75rem 1rem; background: #1e293b; border-left: 4px solid {color}; border-radius: 6px; font-size: 0.85rem; color: #e2e8f0;">
        {icon} <strong>{item["service"]}</strong> — {item["message"]}
      </div>'''
        html += '''
    </div>'''

    html += '''
    <div style="display: grid; gap: 0.75rem;">'''

    for r in s["rows"]:
        jpy = r["monthly_jpy"]
        if not r["counted"]:
            amount = "―"
        elif jpy is None:
            amount = "金額未確認"
        elif jpy == 0:
            amount = "¥0"
        else:
            amount = f"¥{round(jpy):,}"
        if r.get("cycle") == "one_time":
            spot = to_jpy(r.get("amount"), r.get("currency", "JPY"), s["rate"], s["fee_pct"])
            amount = f"¥{round(spot):,}" if spot else "―"
        color = {"active": "#22c55e", "trial": "#f59e0b", "watch": "#60a5fa"}.get(r.get("status"), "#475569")
        url = r.get("dashboard") or "#"
        tag = "a" if url != "#" else "div"
        target = ' target="_blank"' if url != "#" else ""
        href = f' href="{url}"' if url != "#" else ""

        html += f'''
      <{tag}{href}{target} style="display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem; background: #1e293b; border: 1px solid #334155; border-left: 4px solid {color}; border-radius: 6px; text-decoration: none; color: #e2e8f0;">
        <div>
          <div style="font-weight: 600; font-size: 0.95rem;">{r.get("name", "?")}</div>
          <div style="font-size: 0.8rem; color: #94a3b8;">{r.get("category", "")} / {STATUS_LABEL.get(r.get("status"), "")}</div>
        </div>
        <div style="text-align: right; white-space: nowrap;">
          <div style="font-weight: 700; color: {color}; font-size: 1.05rem;">{amount}</div>
          <div style="font-size: 0.75rem; color: #64748b;">{CYCLE_LABEL.get(r.get("cycle"), r.get("cycle", ""))}</div>
        </div>
      </{tag}>'''

    html += '''
    </div>
  </div>'''
    return html


COMMANDS = {"report": cmd_report, "check": cmd_check, "add": cmd_add}


def main() -> int:
    args = sys.argv[1:]
    cmd = args[0] if args else "report"
    if cmd not in COMMANDS:
        print(__doc__)
        return 1
    return COMMANDS[cmd](args[1:]) or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # `| head` などで打ち切られたときに醜い traceback を出さない
        sys.exit(0)
