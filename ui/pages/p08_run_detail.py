"""ui/pages/p08_run_detail.py — Full run detail view (triage + fix + execution)."""

import html as _html

import streamlit as st
from ui.theme import topbar, sev_badge, section_label


def render() -> None:
    run     = st.session_state.get("current_run")
    triage  = st.session_state.get("triage_result")
    script  = st.session_state.get("fix_script")
    results = st.session_state.get("exec_results", [])
    back_page = st.session_state.get("detail_back_page", "history")

    sev = getattr(run, "severity", "") if run else ""
    topbar("Run Detail", sev_badge(sev) if sev else "")

    # Back button
    back_label = "← Dashboard" if back_page == "p01" else "← History"
    if st.button(back_label):
        st.session_state.page = back_page
        st.rerun()

    if not run:
        st.info("No run loaded. Go to History to select a run.")
        return

    # ── Run metadata ───────────────────────────────────────────────────────
    test_name = getattr(run, "test_case_name", "") or getattr(run, "test_case", "—")
    device_id = getattr(run, "device_id", "—") or "—"
    vendor    = getattr(run, "vendor", "") or ""
    model_    = getattr(run, "model", "") or ""
    run_id    = str(getattr(run, "run_id", "") or "")
    device_str = f"{vendor} {model_}".strip() or device_id
    created   = getattr(run, "created_at", "") or ""

    st.markdown(
        f'<div class="tt-card">'
        f'<div class="tt-card-head">'
        f'<span class="tt-card-title">{_html.escape(str(test_name))}</span>'
        f'{sev_badge(sev)}'
        f'</div>'
        f'<div class="tt-card-body">'
        f'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">'
        f'<div><div style="font-size:10px;color:#9BA8B3;font-family:monospace;margin-bottom:3px">DEVICE</div>'
        f'<div style="font-size:12px;font-weight:500">{_html.escape(str(device_str))}</div></div>'
        f'<div><div style="font-size:10px;color:#9BA8B3;font-family:monospace;margin-bottom:3px">RUN ID</div>'
        f'<div style="font-size:10px;font-family:monospace;color:#3D4A56">{_html.escape(run_id)}</div></div>'
        f'<div><div style="font-size:10px;color:#9BA8B3;font-family:monospace;margin-bottom:3px">DATE</div>'
        f'<div style="font-size:11px;color:#3D4A56">{_html.escape(str(created)[:19])}</div></div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )

    # ── Triage analysis ────────────────────────────────────────────────────
    if triage:
        confidence     = getattr(triage, "confidence", 0) or 0
        root_cause     = getattr(triage, "root_cause_summary", None) or getattr(triage, "root_cause", "—")
        root_detail    = getattr(triage, "root_cause_detail", "") or ""
        recommendations = getattr(triage, "recommendations", []) or []

        col_l, col_r = st.columns(2)
        with col_l:
            detail_html = (
                f'<p style="font-size:11px;color:#9BA8B3;line-height:1.6;margin:8px 0 0">'
                f'{_html.escape(str(root_detail))}</p>'
                if root_detail else ""
            )
            st.markdown(
                f'<div class="tt-card"><div class="tt-card-head">'
                f'<span class="tt-card-title">Root cause</span>'
                f'<span style="font-size:10px;font-family:monospace;color:#9BA8B3">'
                f'{float(confidence):.0%} confidence</span></div>'
                f'<div class="tt-card-body">'
                f'<p style="font-size:12px;color:#3D4A56;line-height:1.7;margin:0">'
                f'{_html.escape(str(root_cause))}</p>'
                f'{detail_html}'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        with col_r:
            if recommendations:
                items_html = "".join(
                    f'<div style="padding:6px 0;border-bottom:0.5px solid #E0E4EA">'
                    f'<div style="font-size:11px;font-weight:500;color:#1C2B3A">'
                    f'{_html.escape(str(getattr(r, "action", r)))}</div>'
                    f'<div style="font-size:10px;color:#9BA8B3;margin-top:2px">'
                    f'{_html.escape(str(getattr(r, "rationale", "")))}</div>'
                    f'</div>'
                    for r in recommendations
                )
                st.markdown(
                    f'<div class="tt-card"><div class="tt-card-head">'
                    f'<span class="tt-card-title">Recommendations</span>'
                    f'<span class="tt-tag tt-tag-blue">{len(recommendations)}</span>'
                    f'</div>'
                    f'<div class="tt-card-body" style="padding:0 14px">'
                    f'{items_html}</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="tt-card"><div class="tt-card-head">'
                    '<span class="tt-card-title">Recommendations</span></div>'
                    '<div class="tt-card-body" style="color:#9BA8B3;font-size:11px">'
                    'No recommendations recorded.</div></div>',
                    unsafe_allow_html=True,
                )

    # ── Metrics ────────────────────────────────────────────────────────────
    metrics = getattr(run, "metrics", []) or []
    if metrics:
        header_html = (
            '<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:8px;'
            'padding:6px 0;border-bottom:0.5px solid #E0E4EA;font-size:10px;font-weight:500;'
            'color:#9BA8B3;font-family:monospace;text-transform:uppercase">'
            '<span>Metric</span><span>Expected</span><span>Measured</span><span>Result</span></div>'
        )
        rows_html = "".join(
            f'<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:8px;'
            f'padding:6px 0;border-bottom:0.5px solid #F5F7FA;font-size:11px">'
            f'<span style="color:#3D4A56">{_html.escape(str(getattr(m,"name","")))}</span>'
            f'<span style="font-family:monospace;color:#9BA8B3">{_html.escape(str(getattr(m,"expected","—")))}</span>'
            f'<span style="font-family:monospace;color:#1C2B3A">{_html.escape(str(getattr(m,"measured","—")))}</span>'
            f'<span style="color:{"#2E7D32" if getattr(m,"passed",None) else "#C62828"}">'
            f'{"Pass" if getattr(m,"passed",None) else "Fail"}</span>'
            f'</div>'
            for m in metrics
        )
        st.markdown(
            f'<div class="tt-card"><div class="tt-card-head">'
            f'<span class="tt-card-title">Metrics</span>'
            f'<span class="tt-tag tt-tag-gray">{len(metrics)} total</span>'
            f'</div>'
            f'<div class="tt-card-body" style="padding:0 14px">'
            f'{header_html}{rows_html}</div></div>',
            unsafe_allow_html=True,
        )

    # ── Fix script ─────────────────────────────────────────────────────────
    if script:
        steps = getattr(script, "steps", []) or []
        exec_mode = str(getattr(script, "execution_mode", "") or "")
        passed = sum(
            1 for r in results
            if getattr(getattr(r, "status", ""), "value", str(getattr(r, "status", ""))) == "passed"
        )
        executed = len(results)

        status_tag = (
            f'<span class="tt-tag tt-tag-green">{passed}/{len(steps)} passed</span>'
            if results else
            f'<span class="tt-tag tt-tag-gray">{len(steps)} steps · {_html.escape(exec_mode)}</span>'
        )

        st.markdown(
            f'<div class="tt-card"><div class="tt-card-head">'
            f'<span class="tt-card-title">Fix script</span>'
            f'{status_tag}'
            f'</div>'
            f'<div class="tt-card-body" style="padding:0 14px">',
            unsafe_allow_html=True,
        )

        for i, step in enumerate(steps):
            res    = results[i] if i < len(results) else None
            status = getattr(getattr(res, "status", ""), "value", "") if res else ""
            ok     = (status == "passed") if res else None
            icon   = "✓" if ok else ("✕" if ok is False else "○")
            colour = "#2E7D32" if ok else ("#C62828" if ok is False else "#9BA8B3")
            cmd    = str(getattr(step, "command", "") or getattr(step, "cmd", "") or "")
            desc   = str(getattr(step, "description", "") or "")
            output = str(getattr(res, "output", "") or "") if res else ""

            cmd_block = (
                f'<div style="font-size:10px;font-family:monospace;background:#F5F7FA;'
                f'border-radius:4px;padding:3px 8px;margin-top:4px;color:#3D4A56">'
                f'{_html.escape(cmd)}</div>'
                if cmd else ""
            )
            output_block = (
                f'<div style="font-size:10px;font-family:monospace;background:#E8F5E9;'
                f'border-radius:4px;padding:3px 8px;margin-top:3px;color:#1B5E20">'
                f'{_html.escape(output[:200])}</div>'
                if output else ""
            )
            st.markdown(
                f'<div style="display:flex;align-items:flex-start;gap:10px;'
                f'padding:8px 0;border-bottom:0.5px solid #F5F7FA">'
                f'<span style="color:{colour};font-weight:600;font-size:14px;'
                f'min-width:18px;margin-top:1px">{icon}</span>'
                f'<div style="flex:1">'
                f'<div style="font-size:11px;font-weight:500;color:#1C2B3A">'
                f'{_html.escape(desc)}</div>'
                f'{cmd_block}{output_block}'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("</div></div>", unsafe_allow_html=True)

    # ── Error logs snippet ─────────────────────────────────────────────────
    logs = getattr(run, "error_logs", []) or []
    if logs:
        log_lines = "\n".join(str(l) for l in logs[:20])
        st.markdown(
            f'<div class="tt-card"><div class="tt-card-head">'
            f'<span class="tt-card-title">Error logs</span>'
            f'<span class="tt-tag tt-tag-orange">{len(logs)} lines</span>'
            f'</div>'
            f'<div class="tt-code" style="max-height:200px;overflow-y:auto">'
            f'{_html.escape(log_lines)}'
            f'</div></div>',
            unsafe_allow_html=True,
        )
