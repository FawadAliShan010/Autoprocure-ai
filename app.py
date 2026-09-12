"""
AutoProcure AI — AI-Based Purchase Request Checking System
Full working Gradio application (frontend + backend in one process).

Pipeline:  Gradio UI -> Python App Logic -> PR Data + Inventory + Open PO
           -> Gate 1..4 -> Groq LLM (optional) -> AI Procurement Decision
           -> PROCEED / HOLD / REDUCE / INVESTIGATE / EXPEDITE (recommendation)
           -> manager finalizes -> Approved / On Hold / Investigate / Expedited
"""

import time
import os
import pandas as pd
import gradio as gr

from core import data_cleaning, item_matching, stock_check, usage_check
from core import decision_engine, ai_narrative, storage

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

ITEM_MASTER = pd.read_csv(os.path.join(DATA_DIR, "item_master.csv"))
DEPARTMENT_BUDGETS = pd.read_csv(os.path.join(DATA_DIR, "department_budgets.csv"))
WAREHOUSE_STOCK = pd.read_csv(os.path.join(DATA_DIR, "warehouse_stock.csv"))
USAGE_HISTORY = pd.read_csv(os.path.join(DATA_DIR, "usage_history.csv"))

DEPARTMENTS = DEPARTMENT_BUDGETS["department"].tolist()

ACTION_COLORS = {
    "PROCEED": "#22c55e", "REDUCE": "#f59e0b", "HOLD": "#ef4444",
    "INVESTIGATE": "#a855f7", "EXPEDITE": "#3b82f6",
}
STATUS_COLORS = {
    "Approved": "#22c55e", "On Hold": "#ef4444", "Investigate": "#a855f7",
    "Expedited": "#3b82f6", "Pending Review": "#64748b", "Saved": "#f59e0b",
}

CUSTOM_CSS = """
.gradio-container {background: #0b1220 !important;}
#app-header {text-align: left; padding: 4px 0;}
#app-header h1 {color: #f8fafc; margin-bottom: 2px; font-size: 1.4em;}
#app-header p {color: #94a3b8; margin-top: 0; font-size: 0.9em;}
.badge {display: inline-block; padding: 5px 16px; border-radius: 20px; font-weight: 700; font-size: 1em; color: white;}
.card {background: #131c31; border: 1px solid #1f2b45; border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;}
.stat-card {background: #131c31; border: 1px solid #1f2b45; border-radius: 10px; padding: 14px 18px; text-align: left;}
.stat-card .num {font-size: 1.8em; font-weight: 800; color: #f8fafc;}
.stat-card .label {color: #94a3b8; font-size: 0.85em;}
footer {display: none !important;}
"""

PIPELINE_FOOTER = (
    "**Your App (Gradio UI) → Python App Logic → PR Data + Inventory + Open PO "
    "→ Gates 1-4 → Groq LLM → AI Procurement Decision → "
    "PROCEED / HOLD / REDUCE / INVESTIGATE / EXPEDITE**"
)


def _card(title, body_md):
    return f'<div class="card"><b>{title}</b><br>{body_md}</div>'


def _badge(text, color):
    return f'<span class="badge" style="background:{color};">{text}</span>'


# --------------------------------------------------------------------------
# Core pipeline (Gates 1-4 + AI decision) — unchanged logic, now also
# returns the generated request_id as its own output so the UI can wire
# real "finalize" actions to it instead of faking success messages.
# --------------------------------------------------------------------------

def run_pipeline(employee_name, department, item_description, quantity, estimated_price, required_date, notes):
    if not employee_name or not department or not item_description:
        empty = "*(Waiting for a valid request…)*"
        yield ("⚠️ Please fill in Employee Name, Department, and Item Description.",
               empty, empty, "", "", None,
               gr.update(interactive=False), gr.update(interactive=False),
               gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False))
        return

    try:
        quantity = float(quantity) if quantity else 0
        estimated_price = float(estimated_price) if estimated_price else 0.0
    except ValueError:
        yield ("⚠️ Quantity and Estimated Price must be numeric.",
               "", "", "", "", None,
               gr.update(interactive=False), gr.update(interactive=False),
               gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False))
        return

    if quantity <= 0:
        yield ("⚠️ Quantity must be greater than zero.",
               "", "", "", "", None,
               gr.update(interactive=False), gr.update(interactive=False),
               gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False))
        return

    steps = [
        "Cleaning & standardizing data", "Checking inventory across sites",
        "Verifying purchase orders / budget", "Analyzing usage patterns", "Generating recommendation",
    ]
    done = []
    for i, s in enumerate(steps):
        done.append(f"✅ {s}")
        pending = [f"⏳ {x}" for x in steps[i + 1:]]
        yield ("\n\n".join(done + pending), "", "", "", "", None,
               gr.update(interactive=False), gr.update(interactive=False),
               gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False))
        time.sleep(0.3)

    # Gate 1
    clean_result = data_cleaning.clean_description(item_description)
    corrections_str = (
        ", ".join(f"'{b}' → '{a}'" for b, a in clean_result["corrections"])
        if clean_result["corrections"] else "No corrections needed"
    )
    gate1_md = _card("Gate 1 — Data Cleaning ✅",
        f"Original: <i>{clean_result['original']}</i><br>"
        f"Standardized: <b>{clean_result['cleaned']}</b><br>"
        f"Corrections: {corrections_str}<br>"
        f"Special characters removed: {clean_result['special_chars_removed']}")

    match_result = item_matching.match_item(clean_result["cleaned"], ITEM_MASTER)
    match_badge = {
        "matched": "✅ High confidence match", "low_confidence": "🟡 Low confidence match",
        "unmatched": "🔴 No catalog match — routed to human review",
    }[match_result["status"]]
    gate_match_md = _card("Item Master Mapping",
        f"{match_badge}<br>" + (
            f"SKU: <b>{match_result['sku']}</b> — {match_result['description']}<br>"
            f"GL Code: {match_result['gl_code']} · Confidence: {match_result['confidence']}%"
            if match_result["sku"] else "No SKU could be assigned."))

    stock_result = stock_check.check_other_sites(match_result["sku"], int(quantity), WAREHOUSE_STOCK)
    usage_result = usage_check.check_usage(
        match_result["sku"], department, stock_result["remaining_after_transfer"], USAGE_HISTORY)

    decision = decision_engine.decide(
        match_result, department, quantity, estimated_price, DEPARTMENT_BUDGETS, stock_result, usage_result)

    request_value = round(quantity * estimated_price, 2)
    initial_budget = decision["initial_budget_result"] or {
        "department": department, "request_value": request_value, "remaining_budget": 0,
        "exceeds_budget": None,
    }
    budget_emoji = "🔴" if initial_budget.get("exceeds_budget") else "✅"
    gate2_md = _card(f"Gate 2 — Budget Check {budget_emoji}",
        f"Department: <b>{initial_budget['department']}</b><br>"
        f"Request Value: ${initial_budget['request_value']:,.2f}<br>"
        f"Remaining Monthly Balance: ${initial_budget.get('remaining_budget', 0):,.2f}<br>"
        f"Result: {'Budget variance flag' if initial_budget.get('exceeds_budget') else 'Within budget'}")

    if stock_result["status"] == "transfer_available":
        sites_str = "<br>".join(f"• {s['warehouse']}: {s['quantity']} units ({s['stock_status']})"
                                 for s in stock_result["other_sites"])
        gate3_md = _card("Gate 3 — Other-Site Stock Check 🟡",
            f"{sites_str}<br>Transferable Qty: <b>{stock_result['transferable_qty']}</b><br>"
            f"Remaining external need: {stock_result['remaining_after_transfer']}<br>"
            "Result: Internal transfer recommended")
    else:
        gate3_md = _card("Gate 3 — Other-Site Stock Check ✅",
            "No idle/excess stock found at other sites.")

    if usage_result["status"] in ("overstock_flag", "understock_flag"):
        emoji = "🔴" if usage_result["status"] == "understock_flag" else "🟡"
        gate4_md = _card(f"Gate 4 — Usage Check {emoji}",
            f"Average usage: {usage_result['avg_monthly_usage']} units/month<br>"
            f"Months of supply: {usage_result['months_of_supply']}<br>"
            f"Result: Flagged ({usage_result['status'].replace('_', ' ')})")
    elif usage_result["status"] in ("no_usage_history", "not_applicable"):
        gate4_md = _card("Gate 4 — Usage Check ⚪", "No usage history available for this item.")
    else:
        gate4_md = _card("Gate 4 — Usage Check ✅",
            f"Average usage: {usage_result['avg_monthly_usage']} units/month<br>"
            "Result: Requested quantity is within normal range.")

    checks_md = gate1_md + gate_match_md + gate2_md + gate3_md + gate4_md

    context = {"employee": employee_name, "department": department,
               "item": clean_result["cleaned"], "requested_qty": quantity}
    narrative = ai_narrative.generate_reasoning(
        decision["action"], decision["reasons"], decision["estimated_savings"], context)
    color = ACTION_COLORS.get(decision["action"], "#64748b")
    decision_md = _badge(decision["action"], color) + "<br><br>" + narrative.replace("\n", "<br>")

    adjusted_qty = decision["adjusted_qty"]
    final_value = decision["final_order_value"]
    qty_line = (f"Requested Qty: {int(quantity)} → Final External Order Qty: <b>{int(adjusted_qty)}</b><br>"
                if adjusted_qty is not None and adjusted_qty != quantity
                else f"Requested Qty: {int(quantity)}<br>")
    value_line = (f"Estimated Value: ${request_value:,.2f}"
                  + (f" → Final Order Value: <b>${final_value:,.2f}</b>"
                     if final_value is not None and final_value != request_value else "") + "<br>")
    final_md = _card("Final Recommendation",
        f"Employee: <b>{employee_name}</b> · Department: <b>{department}</b><br>"
        f"Item: <b>{clean_result['cleaned']}</b> (SKU {match_result['sku'] or 'N/A'})<br>"
        f"{qty_line}{value_line}"
        f"Recommended Action: <b style='color:{color};'>{decision['action']}</b><br>"
        f"Estimated Savings: ${decision['estimated_savings']:,.2f}<br>"
        f"Notes: {notes or '—'}")

    full_report_md = _card("Technical Detail",
        f"Match confidence: {match_result['confidence']}% ({match_result['status']})<br>"
        f"GL Code: {match_result.get('gl_code') or 'N/A'}<br>"
        f"Initial budget check: {'exceeded' if initial_budget.get('exceeds_budget') else 'within budget'} "
        f"(remaining ${initial_budget.get('remaining_budget', 0):,.2f})<br>"
        f"Stock transfer status: {stock_result['status']} ({stock_result['transferable_qty']} units)<br>"
        f"Usage status: {usage_result['status']} "
        f"(avg {usage_result.get('avg_monthly_usage')} units/mo)<br>"
        f"Final recalculated order value: ${final_value:,.2f}" if final_value is not None else "N/A")

    request_id = storage.append_request({
        "employee_name": employee_name, "department": department, "item_raw": item_description,
        "item_matched": clean_result["cleaned"], "sku": match_result["sku"] or "",
        "quantity": int(quantity), "estimated_price": estimated_price,
        "required_date": str(required_date) if required_date else "", "request_value": request_value,
        "action": decision["action"], "estimated_savings": decision["estimated_savings"], "notes": notes or "",
    })

    final_status_text = "\n\n".join(f"✅ {s}" for s in steps)
    yield (final_status_text, checks_md, decision_md, final_md, full_report_md, request_id,
           gr.update(interactive=True), gr.update(interactive=True),
           gr.update(interactive=True), gr.update(interactive=True), gr.update(interactive=True))


def finalize_request(request_id, new_status):
    if not request_id:
        return ("⚠️ No active request to finalize.", None,
                gr.update(interactive=False), gr.update(interactive=False),
                gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False))
    ok = storage.update_status(request_id, new_status)
    color = STATUS_COLORS.get(new_status, "#64748b")
    if ok:
        msg = f'{_badge(new_status, color)} &nbsp; Request <b>{request_id}</b> has been marked <b>{new_status}</b>.'
    else:
        msg = f"⚠️ Could not find request {request_id} to update."
    return (msg, None,
            gr.update(interactive=False), gr.update(interactive=False),
            gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False))


# --------------------------------------------------------------------------
# Dashboard / My Requests / Analytics helpers
# --------------------------------------------------------------------------

DISPLAY_COLS = ["request_id", "timestamp", "employee_name", "department",
                 "item_matched", "sku", "quantity", "request_value", "action", "final_status"]


def _status_html(df):
    """Render final_status as colored badges inside an HTML table for nicer display
    than a raw dataframe cell (used on the Home screen)."""
    if df.empty:
        return '<div class="card">No requests yet. Submit your first purchase request to see it here.</div>'
    rows = []
    for _, r in df.iterrows():
        color = STATUS_COLORS.get(r["final_status"], "#64748b")
        rows.append(
            f"<tr><td>{r['request_id']}</td><td>{r['item_matched']}</td><td>{r['department']}</td>"
            f"<td>{_badge(r['final_status'], color)}</td>"
            f"<td>{str(r['timestamp'])[:10]}</td></tr>"
        )
    return (
        '<table style="width:100%; color:#e2e8f0; border-collapse:collapse;">'
        '<tr style="color:#94a3b8; text-align:left;"><th>Request</th><th>Item</th><th>Department</th>'
        '<th>Status</th><th>Date</th></tr>' + "".join(rows) + "</table>"
    )


def refresh_home():
    stats = storage.dashboard_stats()
    stats_html = '<div style="display:flex; gap:10px; flex-wrap:wrap;">' + "".join(
        f'<div class="stat-card" style="flex:1; min-width:120px;">'
        f'<div class="num">{v}</div><div class="label">{label}</div></div>'
        for label, v in [
            ("Total Requests", stats["total_requests"]), ("Approved", stats["approved"]),
            ("On Hold", stats["on_hold"]), ("Investigate", stats["investigate"]),
            ("Expedited", stats["expedited"]), ("Pending Review", stats["pending_review"]),
        ]
    ) + "</div>"
    df = storage.load_history()
    recent = df.sort_values("timestamp", ascending=False).head(8) if len(df) else df
    return stats_html, _status_html(recent)


def filter_my_requests(session_user, search_text, dept_filter, status_filter, show_all):
    df = storage.load_history()
    if len(df) == 0:
        return pd.DataFrame(columns=DISPLAY_COLS)
    if not show_all and session_user:
        df = df[df["employee_name"].str.lower() == session_user.lower()]
    if search_text:
        s = search_text.lower()
        mask = (df["item_matched"].str.lower().str.contains(s, na=False)
                | df["employee_name"].str.lower().str.contains(s, na=False)
                | df["sku"].astype(str).str.lower().str.contains(s, na=False))
        df = df[mask]
    if dept_filter and dept_filter != "All":
        df = df[df["department"] == dept_filter]
    if status_filter and status_filter != "All":
        df = df[df["final_status"] == status_filter]
    df = df.sort_values("timestamp", ascending=False)
    return df[DISPLAY_COLS] if len(df) else pd.DataFrame(columns=DISPLAY_COLS)


def refresh_analytics():
    df = storage.load_history()
    if len(df) == 0:
        empty = pd.DataFrame({"category": [], "count": []})
        return empty, empty, empty
    action_counts = df["action"].value_counts().reset_index()
    action_counts.columns = ["action", "count"]

    savings_by_dept = df.groupby("department")["estimated_savings"].sum().reset_index()
    savings_by_dept.columns = ["department", "savings"]

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date.astype(str)
    over_time = df.groupby("date").size().reset_index(name="requests")

    return action_counts, savings_by_dept, over_time


def do_reset_demo_data():
    storage.reset_demo_data()
    stats_html, recent_html = refresh_home()
    return "✅ Demo data cleared. All submitted requests have been removed.", stats_html, recent_html


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

with gr.Blocks(css=CUSTOM_CSS, title="AutoProcure AI", theme=gr.themes.Soft(primary_hue="indigo")) as demo:
    session_user = gr.State("")
    current_request_id = gr.State(None)

    # ---------------- Login view ----------------
    with gr.Column(visible=True) as login_view:
        gr.Markdown("# 🛒 AutoProcure AI")
        gr.Markdown("AI-Powered Purchase Request Checking System · Clean data. Check budgets. Optimize inventory.")
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
                    "**Demo tip:** after signing in, try submitting `saftey helms`, qty `500`, "
                    "department `Operational Safety` to see the full case-study flow play out end to end."
                )

    # ---------------- App shell (post-login) ----------------
    with gr.Column(visible=False) as app_view:
        with gr.Sidebar(width=230):
            gr.Markdown("### 🛒 AutoProcure AI")
            nav_home = gr.Button("🏠 Home", variant="primary")
            nav_submit = gr.Button("📝 Submit PR", variant="secondary")
            nav_myreq = gr.Button("📋 My Requests", variant="secondary")
            nav_analytics = gr.Button("📊 Analytics", variant="secondary")
            nav_settings = gr.Button("⚙️ Settings", variant="secondary")
            gr.Markdown("---")
            profile_label = gr.Markdown("")
            logout_btn = gr.Button("Sign out", size="sm")

        with gr.Column():
                # ---------------- Home ----------------
                with gr.Column(visible=True) as page_home:
                    home_greeting = gr.Markdown("### Good morning! 👋")
                    home_stats = gr.HTML()
                    gr.Markdown("#### Recent Requests")
                    home_recent = gr.HTML()

                # ---------------- Submit PR ----------------
                with gr.Column(visible=False) as page_submit:
                    gr.Markdown("### 📝 Submit Purchase Request")
                    with gr.Row():
                        with gr.Column(scale=1):
                            employee_name = gr.Textbox(label="Employee Name", placeholder="e.g. Ayesha Gill")
                            department = gr.Dropdown(label="Department", choices=DEPARTMENTS, value=DEPARTMENTS[0])
                            item_description = gr.Textbox(label="Item Description", placeholder="e.g. laptop chargr")
                            with gr.Row():
                                quantity = gr.Number(label="Quantity", value=10, precision=0)
                                estimated_price = gr.Number(label="Estimated Price (per unit)", value=25.0)
                            required_date = gr.Textbox(label="Required Date", placeholder="YYYY-MM-DD")
                            notes = gr.Textbox(label="Additional Notes (optional)")
                            submit_btn = gr.Button("Check Request →", variant="primary")
                        with gr.Column(scale=1):
                            gr.Markdown("#### Processing / Data Collection")
                            processing_status = gr.Markdown("*(No request submitted yet)*")

                    gr.Markdown("#### Data Checks & Analysis")
                    checks_output = gr.HTML()
                    gr.Markdown("#### 🤖 AI Procurement Decision")
                    decision_output = gr.HTML()
                    gr.Markdown("#### ✅ Final Recommendation / Result")
                    final_output = gr.HTML()
                    with gr.Accordion("View Full Report", open=False):
                        full_report_output = gr.HTML()

                    gr.Markdown("Finalize this request:")
                    with gr.Row():
                        approve_btn = gr.Button("✅ Approve", interactive=False)
                        hold_btn = gr.Button("⏸ Hold", interactive=False)
                        investigate_btn = gr.Button("🔍 Investigate", interactive=False)
                        expedite_btn = gr.Button("🚀 Expedite", interactive=False)
                        save_btn = gr.Button("💾 Save for Later", interactive=False)
                    finalize_message = gr.Markdown("")

                    submit_btn.click(
                        fn=run_pipeline,
                        inputs=[employee_name, department, item_description, quantity,
                                estimated_price, required_date, notes],
                        outputs=[processing_status, checks_output, decision_output, final_output,
                                 full_report_output, current_request_id,
                                 approve_btn, hold_btn, investigate_btn, expedite_btn, save_btn],
                    )
                    finalize_outputs = [finalize_message, current_request_id,
                                         approve_btn, hold_btn, investigate_btn, expedite_btn, save_btn]
                    approve_btn.click(fn=lambda rid: finalize_request(rid, "Approved"),
                                       inputs=[current_request_id], outputs=finalize_outputs)
                    hold_btn.click(fn=lambda rid: finalize_request(rid, "On Hold"),
                                    inputs=[current_request_id], outputs=finalize_outputs)
                    investigate_btn.click(fn=lambda rid: finalize_request(rid, "Investigate"),
                                           inputs=[current_request_id], outputs=finalize_outputs)
                    expedite_btn.click(fn=lambda rid: finalize_request(rid, "Expedited"),
                                        inputs=[current_request_id], outputs=finalize_outputs)
                    save_btn.click(fn=lambda rid: finalize_request(rid, "Saved"),
                                    inputs=[current_request_id], outputs=finalize_outputs)

                # ---------------- My Requests ----------------
                with gr.Column(visible=False) as page_myreq:
                    gr.Markdown("### 📋 My Requests")
                    with gr.Row():
                        search_box = gr.Textbox(label="Search requests...", placeholder="item, SKU, or employee")
                        dept_filter = gr.Dropdown(label="Department", choices=["All"] + DEPARTMENTS, value="All")
                        status_filter = gr.Dropdown(
                            label="Status", value="All",
                            choices=["All"] + storage.VALID_FINAL_STATUSES)
                        show_all_chk = gr.Checkbox(label="Show all requests (admin view)", value=False)
                    myreq_table = gr.Dataframe(headers=DISPLAY_COLS, wrap=True)

                    myreq_inputs = [session_user, search_box, dept_filter, status_filter, show_all_chk]
                    for ctrl in [search_box, dept_filter, status_filter, show_all_chk]:
                        ctrl.change(fn=filter_my_requests, inputs=myreq_inputs, outputs=[myreq_table])

                # ---------------- Analytics ----------------
                with gr.Column(visible=False) as page_analytics:
                    gr.Markdown("### 📊 Analytics")
                    analytics_refresh = gr.Button("🔄 Refresh")
                    action_chart = gr.BarPlot(x="action", y="count", title="Requests by AI Recommendation",
                                               x_title="Action", y_title="Count")
                    savings_chart = gr.BarPlot(x="department", y="savings", title="Estimated Savings by Department",
                                                x_title="Department", y_title="Savings ($)")
                    time_chart = gr.LinePlot(x="date", y="requests", title="Requests Over Time",
                                              x_title="Date", y_title="Requests")
                    analytics_refresh.click(fn=refresh_analytics, outputs=[action_chart, savings_chart, time_chart])

                # ---------------- Settings ----------------
                with gr.Column(visible=False) as page_settings:
                    gr.Markdown("### ⚙️ Settings")
                    ai_status = "🟢 Connected (Groq LLM)" if os.environ.get("GROQ_API_KEY") else \
                                "⚪ Not configured — using rule-based reasoning fallback"
                    gr.Markdown(f"**AI Provider Status:** {ai_status}")
                    gr.Markdown("#### Department Budgets (reference)")
                    gr.Dataframe(value=DEPARTMENT_BUDGETS, interactive=False)
                    gr.Markdown("#### Item Master (reference)")
                    gr.Dataframe(value=ITEM_MASTER[["sku", "description", "category", "unit_price", "gl_code"]],
                                 interactive=False)
                    gr.Markdown("#### Danger Zone")
                    reset_btn = gr.Button("🗑️ Reset Demo Data", variant="stop")
                    reset_message = gr.Markdown("")

        # ---------------- Navigation wiring ----------------
        pages = [page_home, page_submit, page_myreq, page_analytics, page_settings]
        nav_buttons = [nav_home, nav_submit, nav_myreq, nav_analytics, nav_settings]

        def _switch_page(idx):
            def _fn():
                vis = [gr.update(visible=(i == idx)) for i in range(len(pages))]
                variants = [gr.update(variant=("primary" if i == idx else "secondary")) for i in range(len(nav_buttons))]
                return vis + variants
            return _fn

        for i, btn in enumerate(nav_buttons):
            btn.click(fn=_switch_page(i), outputs=pages + nav_buttons)

        nav_home.click(fn=refresh_home, outputs=[home_stats, home_recent])
        nav_myreq.click(fn=filter_my_requests,
                         inputs=[session_user, search_box, dept_filter, status_filter, show_all_chk],
                         outputs=[myreq_table])
        nav_analytics.click(fn=refresh_analytics, outputs=[action_chart, savings_chart, time_chart])

        reset_btn.click(fn=do_reset_demo_data, outputs=[reset_message, home_stats, home_recent])

    # ---------------- Login wiring ----------------
    def do_login(email, password):
        if not email:
            return "⚠️ Please enter an email or username.", "", gr.update(visible=True), gr.update(visible=False), "", ""
        display_name = email.split("@")[0].replace(".", " ").title()
        stats_html, recent_html = refresh_home()
        greeting = f"### Good morning, {display_name}! 👋"
        profile = f"**{display_name}**  \nProcurement Team"
        return "", display_name, gr.update(visible=False), gr.update(visible=True), greeting, profile

    login_btn.click(
        fn=do_login, inputs=[login_email, login_password],
        outputs=[login_message, session_user, login_view, app_view, home_greeting, profile_label],
    ).then(fn=refresh_home, outputs=[home_stats, home_recent]
    ).then(fn=lambda name: name, inputs=[session_user], outputs=[employee_name])

    logout_btn.click(
        fn=lambda: ("", gr.update(visible=True), gr.update(visible=False)),
        outputs=[session_user, login_view, app_view],
    )

    gr.Markdown(PIPELINE_FOOTER)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port)
