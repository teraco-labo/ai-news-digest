#!/usr/bin/env python3
"""API Cost Dashboard Generator"""

import json
from pathlib import Path
from api_cost_calculator import get_dashboard_data


def generate_api_dashboard_html() -> str:
    """Generate HTML for API cost dashboard with subscription and usage separated"""

    costs = get_dashboard_data()
    total_jpy = costs.get("total_jpy", 0)
    total_usd = costs.get("total_usd", 0)

    subscription = costs.get("subscription", {})
    subscription_jpy = subscription.get("jpy", 0)
    subscription_usd = subscription.get("usd", 0)
    subscription_name = subscription.get("name", "Claude Subscription")

    api_usage = costs.get("api_usage", {})
    api_models = api_usage.get("models", [])
    api_usage_jpy = api_usage.get("total_jpy", 0)
    api_usage_usd = api_usage.get("total_usd", 0)

    # Main container with total cost
    html = '''<div class="card">
    <div class="card-title">💰 今月のコスト内訳</div>

    <!-- Total cost summary -->
    <div style="margin-bottom: 1.5rem; padding: 1.5rem; background: linear-gradient(135deg, #0f172a, #1e293b); border-radius: 8px; border-left: 4px solid #60a5fa; text-align: center;">
      <div style="font-size: 2.5rem; font-weight: bold; color: #60a5fa;">¥''' + f'''{total_jpy:,}''' + '''</div>
      <div style="font-size: 0.9rem; color: #94a3b8; margin-top: 0.5rem;">''' + f'''${total_usd:.2f} USD''' + '''</div>
    </div>

    <!-- Subscription Costs Section -->
    <div style="margin-bottom: 1.5rem;">
      <div style="font-weight: 600; color: #e2e8f0; margin-bottom: 0.75rem; padding-left: 0.5rem; border-left: 3px solid #8B5CF6;">📌 Claude月額料金</div>
      <div style="display: flex; align-items: center; justify-content: space-between; padding: 1rem; background: linear-gradient(135deg, rgba(139, 92, 246, 0.1), rgba(139, 92, 246, 0.05)); border: 1px solid rgba(139, 92, 246, 0.3); border-left: 4px solid #8B5CF6; border-radius: 6px; text-decoration: none; color: #e2e8f0;">
        <div>
          <div style="font-weight: 600; color: #e2e8f0; font-size: 0.95rem;">''' + subscription_name + '''</div>
          <div style="font-size: 0.8rem; color: #94a3b8;">月額プラン</div>
        </div>
        <div style="text-align: right;">
          <div style="font-weight: 700; color: #8B5CF6; font-size: 1.1rem;">¥''' + f'''{subscription_jpy:,}''' + '''</div>
          <div style="font-size: 0.8rem; color: #64748b;">''' + f'''${subscription_usd:.2f} USD''' + '''</div>
        </div>
      </div>
    </div>

    <!-- API Usage Costs Section -->
    <div>
      <div style="font-weight: 600; color: #e2e8f0; margin-bottom: 0.75rem; padding-left: 0.5rem; border-left: 3px solid #60a5fa;">⚙️ API使用料金</div>

      <!-- API Usage Summary -->
      <div style="margin-bottom: 1rem; padding: 1rem; background: linear-gradient(135deg, rgba(96, 165, 250, 0.1), rgba(96, 165, 250, 0.05)); border: 1px solid rgba(96, 165, 250, 0.3); border-left: 4px solid #60a5fa; border-radius: 6px; text-decoration: none; color: #e2e8f0;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="font-size: 0.95rem; color: #94a3b8;">実際の利用料金</div>
          <div style="text-align: right;">
            <div style="font-weight: 700; color: #60a5fa; font-size: 1.1rem;">¥''' + f'''{api_usage_jpy:,}''' + '''</div>
            <div style="font-size: 0.8rem; color: #64748b;">''' + f'''${api_usage_usd:.4f} USD''' + '''</div>
          </div>
        </div>
      </div>

      <!-- Models list -->
      <div style="display: grid; gap: 0.75rem;">'''

    if api_models:
        for model in api_models:
            color = model.get("color", "#60a5fa")
            name = model.get("name", "Unknown")
            provider = model.get("provider", "Unknown")
            jpy = model.get("jpy", 0)
            usd = model.get("usd", 0)
            url = model.get("url", "#")
            purposes = model.get("purposes", [])

            html += f'''
        <a href="{url}" target="_blank" style="display: flex; align-items: center; justify-content: space-between; padding: 1rem; background: #1e293b; border: 1px solid #334155; border-left: 4px solid {color}; border-radius: 6px; text-decoration: none; color: #e2e8f0; transition: all 0.2s; cursor: pointer;">
          <div>
            <div style="font-weight: 600; color: #e2e8f0; font-size: 0.95rem;">{name}</div>
            <div style="font-size: 0.8rem; color: #94a3b8;">{provider}</div>'''

            # Add purpose breakdown if available
            if purposes:
                html += '''<div style="margin-top: 0.5rem; font-size: 0.75rem; color: #64748b; border-top: 1px solid #475569; padding-top: 0.5rem;">'''
                for purpose in purposes:
                    purpose_name = purpose.get("name", "Unknown")
                    calls = purpose.get("calls", 0)
                    html += f'''<div>• {purpose_name} ({calls}回)</div>'''
                html += '''</div>'''

            html += f'''
          </div>
          <div style="text-align: right;">
            <div style="font-weight: 700; color: {color}; font-size: 1.1rem;">¥{jpy:,}</div>
            <div style="font-size: 0.8rem; color: #64748b;">${usd:.4f} USD</div>
          </div>
        </a>'''
    else:
        html += '''
        <p class="no-data" style="padding: 1rem; color: #94a3b8; text-align: center;">まだAPI使用データがありません</p>'''

    html += '''
      </div>
    </div>
  </div>'''

    # コードが呼んでいない課金（サブスク・前払い・無料体験からの自動移行）は
    # 上の集計に出てこないので、service_costs.json の台帳を隣に並べる。
    try:
        from service_costs import generate_service_costs_html
        html += "\n" + generate_service_costs_html()
    except Exception as e:
        print(f"⚠️  課金サービスカードの生成に失敗しました: {e}")

    return html


if __name__ == "__main__":
    print(generate_api_dashboard_html())
