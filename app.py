"""
AutoProcure AI — AI-Based Purchase Request Checking System
Full working Gradio application (frontend + backend in one process).

Pipeline:  Gradio UI -> Python App Logic -> PR Data + Inventory + Open PO
           -> Gate 1..4 -> Groq LLM (optional) -> AI Procurement Decision
           -> PROCEED / HOLD / REDUCE / INVESTIGATE / EXPEDITE
"""

import time
import os
import pandas as pd
import gradio as gr

from core import data_cleaning, item_matching, budget_check, stock_check, usage_check
from core import decision_engine, ai_narrative, storage

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

ITEM_MASTER = pd.read_csv(os.path.join(DATA_DIR, "item_master.csv"))
DEPARTMENT_BUDGETS = pd.read_csv(os.path.join(DATA_DIR, "department_budgets.csv"))
WAREHOUSE_STOCK = pd.read_csv(os.path.join(DATA_DIR, "warehouse_stock.csv"))
USAGE_HISTORY = pd.read_csv(os.path.join(DATA_DIR, "usage_history.csv"))

DEPARTMENTS = DEPARTMENT_BUDGETS["department"].tolist()

ACTION_COLORS = {
    "PROCEED": "#22c55e",
    "REDUCE": "#f59e0b",
    "HOLD": "#ef4444",
    "INVESTIGATE": "#a855f7",
    "EXPEDITE": "#3b82f6",
}

CUSTOM_CSS = """
.gradio-container {background: #0b1220 !important;}
#app-header {text-align: center; padding: 10px 0 4px 0;}
#app-header h1 {color: #f8fafc; margin-bottom: 2px;}
#app-header p {color: #94a3b8; margin-top: 0;}
.badge {
  display: inline-block; padding: 6px 18px; border-radius: 20px;
  font-weight: 700; font-size: 1.05em; color: white; letter-spacing: 0.5px;
}
.card {
  background: #131c31; border: 1px solid #1f2b45; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 10px;
}
footer {display: none !important;}
"""

PIPELINE_FOOTER = (
    "**Your App (Gradio UI) → Python App Logic → PR Data + Inventory + Open PO "
    "→ Groq LLM → AI Procurement Decision → PROCEED / HOLD / REDUCE / INVESTIGATE / EXPEDITE**"
)


def _card(title, body_md):
    return f'<div class="card"><b>{title}</b><br>{body_md}</div>'


def run_pipeline(employee_name, department, item_description, quantity, estimated_price, required_date, notes):
    """Generator that streams the processing checklist, then all gate
    results, the AI decision, and the final recommendation."""

    if not employee_name or not department or not item_description:
        empty = "*(Waiting for a valid request…)*"
        yield ("⚠️ Please fill in Employee Name, Department, and Item Description.",
               empty, empty, "")
        return

    try:
        quantity = float(quantity) if quantity else 0
        estimated_price = float(estimated_price) if estimated_price else 0.0
    except ValueError:
        yield ("⚠️ Quantity and Estimated Price must be numeric.",
               "", "", "")
        return

    steps = [
        "Cleaning & standardizing data",
        "Checking inventory across sites",
        "Verifying purchase orders / budget",
        "Analyzing usage patterns",
        "Generating recommendation",
    ]
    done = []
    for i, s in enumerate(steps):
        done.append(f"✅ {s}")
        pending = [f"⏳ {x}" for x in steps[i + 1:]]
        status_md = "\n\n".join(done + pending)
        yield (status_md, "", "", "")
        time.sleep(0.35)

    # ---- Gate 1: Data Cleaning ----
    clean_result = data_cleaning.clean_description(item_description)
    corrections_str = (
        ", ".join(f"'{b}' → '{a}'" for b, a in clean_result["corrections"])
        if clean_result["corrections"] else "No corrections needed"
    )
    gate1_md = _card(
        "Gate 1 — Data Cleaning ✅",
        f"Original: <i>{clean_result['original']}</i><br>"
        f"Standardized: <b>{clean_result['cleaned']}</b><br>"
        f"Corrections: {corrections_str}<br>"
        f"Special characters removed: {clean_result['special_chars_removed']}"
    )

    # ---- Vector item-code mapping ----
    match_result = item_matching.match_item(clean_result["cleaned"], ITEM_MASTER)

    request_value = round(quantity * estimated_price, 2)

    # ---- Gate 3: Other-Site Stock Check ----
    stock_result = stock_check.check_other_sites(match_result["sku"], int(quantity), WAREHOUSE_STOCK)

    # ---- Gate 4: Usage Check ----
    usage_result = usage_check.check_usage(
        match_result["sku"], department, stock_result["remaining_after_transfer"], USAGE_HISTORY
    )

    # ---- AI Decision (this also runs Gate 2 internally, both on the
    #      initial request and on the transfer/usage-adjusted quantity) ----
    decision = decision_engine.decide(
        match_result, department, quantity, estimated_price, DEPARTMENT_BUDGETS,
        stock_result, usage_result,
    )
    budget_result = decision["initial_budget_result"] or {
        "department": department, "request_value": request_value,
        "remaining_budget": 0, "exceeds_budget": None, "status": "unknown",
    }

    match_badge = {
        "matched": "✅ High confidence match",
        "low_confidence": "🟡 Low confidence match",
        "unmatched": "🔴 No catalog match — routed to human review",
    }[match_result["status"]]

    gate_match_md = _card(
        "Item Master Mapping",
        f"{match_badge}<br>"
        + (f"SKU: <b>{match_result['sku']}</b> — {match_result['description']}<br>"
           f"GL Code: {match_result['gl_code']} · Confidence: {match_result['confidence']}%"
           if match_result["sku"] else "No SKU could be assigned.")
    )

    budget_status_emoji = "🔴" if budget_result["status"] == "variance_flag" else "✅"
    gate2_md = _card(
        f"Gate 2 — Budget Check {budget_status_emoji}",
        f"Department: <b>{budget_result['department']}</b><br>"
        f"Request Value: ${budget_result['request_value']:,.2f}<br>"
        f"Remaining Monthly Balance: ${budget_result['remaining_budget']:,.2f}<br>"
        f"Result: {'Automatic budget variance flag' if budget_result['exceeds_budget'] else 'Within budget'}"
    )

    if stock_result["status"] == "transfer_available":
        sites_str = "<br>".join(
            f"• {s['warehouse']}: {s['quantity']} units ({s['stock_status']})"
            for s in stock_result["other_sites"]
        )
        gate3_md = _card(
            "Gate 3 — Other-Site Stock Check 🟡",
            f"{sites_str}<br>"
            f"Transferable Qty: <b>{stock_result['transferable_qty']}</b><br>"
            f"Remaining external order needed: {stock_result['remaining_after_transfer']}<br>"
            "Result: Internal transfer recommended"
        )
    else:
        gate3_md = _card(
            "Gate 3 — Other-Site Stock Check ✅",
            "No idle/excess stock found at other sites. Full quantity proceeds externally."
        )

    if usage_result["status"] in ("overstock_flag", "understock_flag"):
        emoji = "🔴" if usage_result["status"] == "understock_flag" else "🟡"
        gate4_md = _card(
            f"Gate 4 — Usage Check {emoji}",
            f"Average usage: {usage_result['avg_monthly_usage']} units/month<br>"
            f"Months of supply at requested qty: {usage_result['months_of_supply']}<br>"
            f"Result: Flagged for resizing ({usage_result['status'].replace('_', ' ')})"
        )
    elif usage_result["status"] == "no_usage_history":
        gate4_md = _card("Gate 4 — Usage Check ⚪", "No usage history on file for this SKU/department.")
    elif usage_result["status"] == "not_applicable":
        gate4_md = _card("Gate 4 — Usage Check ⚪", "Not applicable (no catalog match).")
    else:
        gate4_md = _card(
            "Gate 4 — Usage Check ✅",
            f"Average usage: {usage_result['avg_monthly_usage']} units/month<br>"
            "Result: Requested quantity is within normal range."
        )

    checks_md = gate1_md + gate_match_md + gate2_md + gate3_md + gate4_md

    context = {
        "employee": employee_name, "department": department,
        "item": clean_result["cleaned"], "requested_qty": quantity,
    }
    narrative = ai_narrative.generate_reasoning(
        decision["action"], decision["reasons"], decision["estimated_savings"], context
    )
    color = ACTION_COLORS.get(decision["action"], "#64748b")
    decision_md = (
        f'<span class="badge" style="background:{color};">{decision["action"]}</span><br><br>'
        + narrative.replace("\n", "<br>")
    )

    # ---- Final Recommendation / Result ----
    adjusted_qty = decision["adjusted_qty"]
    final_value = decision["final_order_value"]
    qty_line = (
        f"Requested Qty: {int(quantity)} → Final External Order Qty: <b>{int(adjusted_qty)}</b><br>"
        if adjusted_qty is not None and adjusted_qty != quantity
        else f"Requested Qty: {int(quantity)}<br>"
    )
    value_line = (
        f"Estimated Value: ${request_value:,.2f}"
        + (f" → Final Order Value: <b>${final_value:,.2f}</b>" if final_value is not None and final_value != request_value else "")
        + "<br>"
    )
    final_md = _card(
        "Final Recommendation",
        f"Employee: <b>{employee_name}</b> · Department: <b>{department}</b><br>"
        f"Item: <b>{clean_result['cleaned']}</b> (SKU {match_result['sku'] or 'N/A'})<br>"
        f"{qty_line}"
        f"{value_line}"
        f"Final Action: <b style='color:{color};'>{decision['action']}</b><br>"
        f"Estimated Savings: ${decision['estimated_savings']:,.2f}<br>"
        f"Notes: {notes or '—'}"
    )

    # ---- Persist to history log ----
    request_id = storage.append_request({
        "employee_name": employee_name,
        "department": department,
        "item_raw": item_description,
        "item_matched": clean_result["cleaned"],
        "sku": match_result["sku"] or "",
        "quantity": int(quantity),
        "estimated_price": estimated_price,
        "required_date": str(required_date) if required_date else "",
        "request_value": request_value,
        "action": decision["action"],
        "estimated_savings": decision["estimated_savings"],
        "notes": notes or "",
    })

    final_status = "\n\n".join(f"✅ {s}" for s in steps)
    yield (final_status, checks_md, decision_md,
           final_md + f"<br><i>Saved as {request_id}</i>")


def refresh_dashboard():
    stats = storage.dashboard_stats()
    df = storage.load_history()
    df_display = df.sort_values("timestamp", ascending=False) if len(df) else df
    stats_md = (
        f'<div class="card">'
        f"<b>Total Requests:</b> {stats['total_requests']} &nbsp;|&nbsp; "
        f"<b>Proceed:</b> {stats['proceed']} &nbsp;|&nbsp; "
        f"<b>Hold:</b> {stats['hold']} &nbsp;|&nbsp; "
        f"<b>Reduce:</b> {stats['reduce']} &nbsp;|&nbsp; "
        f"<b>Investigate:</b> {stats['investigate']} &nbsp;|&nbsp; "
        f"<b>Expedite:</b> {stats['expedite']} &nbsp;|&nbsp; "
        f"<b>Total Est. Savings:</b> ${stats['total_savings']:,.2f}"
        f"</div>"
    )
    return stats_md, df_display


with gr.Blocks(css=CUSTOM_CSS, title="AutoProcure AI", theme=gr.themes.Soft(primary_hue="indigo")) as demo:
    with gr.Column(elem_id="app-header"):
        gr.Markdown("# 🛒 AutoProcure AI")
        gr.Markdown("AI-Powered Purchase Request Checking System · Clean data. Check budgets. Optimize inventory.")

    session_user = gr.State("")

    with gr.Tabs():
        with gr.TabItem("🔐 Sign In"):
            gr.Markdown("### Welcome Back")
            gr.Markdown("Sign in to access AutoProcure AI. *(Demo login — any name/email is accepted.)*")
            with gr.Row():
                with gr.Column(scale=1):
                    login_email = gr.Textbox(label="Email or Username", placeholder="ayesha.gill@company.com")
                    login_password = gr.Textbox(label="Password", type="password", placeholder="••••••••")
                    login_btn = gr.Button("Sign In", variant="primary")
                    login_message = gr.Markdown("")
                with gr.Column(scale=1):
                    gr.Markdown(
                        "**New here?** Contact your procurement admin to get access.\n\n"
                        "**Demo tip:** try submitting `saftey helms`, qty `500`, department "
                        "`Operational Safety` on the next tab to see the full Apex Manufacturing "
                        "case-study flow from the PRD play out end to end."
                    )

            def do_login(email, password):
                if not email:
                    return "⚠️ Please enter an email or username.", ""
                display_name = email.split("@")[0].replace(".", " ").title()
                return f"✅ Signed in as **{display_name}**. Head to the *Submit Purchase Request* tab →", display_name

            login_btn.click(fn=do_login, inputs=[login_email, login_password],
                             outputs=[login_message, session_user])

        with gr.TabItem("📝 Submit Purchase Request") as submit_tab:
            with gr.Row():
                with gr.Column(scale=1):
                    employee_name = gr.Textbox(label="Employee Name", placeholder="e.g. Ayesha Gill")
                    department = gr.Dropdown(label="Department", choices=DEPARTMENTS, value=DEPARTMENTS[0])
                    item_description = gr.Textbox(label="Item Description", placeholder="e.g. laptop chargr")
                    with gr.Row():
                        quantity = gr.Number(label="Quantity", value=10, precision=0)
                        estimated_price = gr.Number(label="Estimated Price (per unit)", value=25.0)
                    required_date = gr.Textbox(label="Required Date", placeholder="YYYY-MM-DD")
                    notes = gr.Textbox(label="Additional Notes (optional)", placeholder="Any extra information...")
                    submit_btn = gr.Button("Check Request →", variant="primary")

                with gr.Column(scale=1):
                    gr.Markdown("### Processing / Data Collection")
                    processing_status = gr.Markdown("*(No request submitted yet)*")

            gr.Markdown("### Data Checks & Analysis")
            checks_output = gr.HTML()

            gr.Markdown("### 🤖 AI Procurement Decision")
            decision_output = gr.HTML()

            gr.Markdown("### ✅ Final Recommendation / Result")
            final_output = gr.HTML()

            submit_btn.click(
                fn=run_pipeline,
                inputs=[employee_name, department, item_description, quantity,
                        estimated_price, required_date, notes],
                outputs=[processing_status, checks_output, decision_output, final_output],
            )

            submit_tab.select(
                fn=lambda name, current: name if name else current,
                inputs=[session_user, employee_name],
                outputs=[employee_name],
            )

        with gr.TabItem("📊 Dashboard / History"):
            gr.Markdown("### Good morning! Here's what's happening with your procurement requests.")
            refresh_btn = gr.Button("🔄 Refresh")
            stats_output = gr.HTML()
            history_table = gr.Dataframe(
                headers=["request_id", "timestamp", "employee_name", "department",
                         "item_matched", "sku", "quantity", "request_value", "action", "estimated_savings"],
                wrap=True,
            )

            def refresh_and_select():
                stats_md, df = refresh_dashboard()
                cols = ["request_id", "timestamp", "employee_name", "department",
                        "item_matched", "sku", "quantity", "request_value", "action", "estimated_savings"]
                df_show = df[cols] if len(df) else pd.DataFrame(columns=cols)
                return stats_md, df_show

            refresh_btn.click(fn=refresh_and_select, outputs=[stats_output, history_table])
            demo.load(fn=refresh_and_select, outputs=[stats_output, history_table])

    gr.Markdown(PIPELINE_FOOTER)

if __name__ == "__main__":
    demo.launch()
