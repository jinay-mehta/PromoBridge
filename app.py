from __future__ import annotations

import json
import os
import sys
import importlib.util
import uuid
from html import escape
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.catalogue import (apply_catalogue_edits, catalogue_dataframe, load_sample_catalogue,
                           parse_uploaded_files, validate_catalogue, save_catalogue_json, load_catalogue_json)
from src.export import build_manifest_row, export_csv, export_json
from src.scoring import score_candidates, decide_status
from src.config import HIGH_SCORE_THRESHOLD, LOW_SCORE_THRESHOLD, MIN_TOP_TWO_MARGIN


st.set_page_config(page_title="PromoBridge | Kuku", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")

RED = "#E32636"
DARK = "#090909"
PANEL = "#151515"
WHITE = "#F7F7F7"
MUTED = "#A7A7A7"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');
html, body, [class*="css"] {{ font-family: 'DM Sans', sans-serif; }}
.stApp {{ background: {DARK}; color: {WHITE}; }}
[data-testid="stHeader"] {{ background: rgba(9,9,9,0.92); }}
[data-testid="stSidebar"] {{ background: #101010; border-right: 1px solid #2B2B2B; }}
h1,h2,h3 {{ font-family: 'Manrope', sans-serif !important; letter-spacing: -0.035em; }}
h1 {{ font-size: 2.35rem !important; }}
.brand {{ font-family: 'Manrope',sans-serif; font-weight: 800; letter-spacing: -0.05em; font-size: 1.5rem; }}
.brand span {{ color: {RED}; }}
.kicker {{ color: {RED}; font-size: .72rem; letter-spacing: .18em; font-weight: 800; text-transform: uppercase; }}
.hero {{ background: linear-gradient(115deg,#1B090B 0%,#111 60%,#171717 100%); border: 1px solid #462026; border-left: 4px solid {RED}; padding: 1.25rem 1.4rem; border-radius: 14px; margin-bottom: 1rem; }}
.panel {{ background: {PANEL}; border: 1px solid #2A2A2A; border-radius: 12px; padding: 1rem; }}
.metric {{ background: #141414; border: 1px solid #292929; border-radius: 12px; padding: .85rem 1rem; }}
.metric-label {{ color: {MUTED}; font-size: .76rem; text-transform: uppercase; letter-spacing: .09em; }}
.metric-value {{ color: {WHITE}; font-size: 1.55rem; font-weight: 800; font-family: 'Manrope',sans-serif; }}
.status {{ display:inline-block; padding: 5px 10px; border-radius: 6px; font-size: .72rem; font-weight: 800; letter-spacing: .06em; }}
.status-verified {{ background:#163B29; color:#7BE0A7; border:1px solid #236641; }}
.status-review {{ background:#4B3515; color:#FFD17D; border:1px solid #86612B; }}
.status-nomatch {{ background:#421D21; color:#FF9BA4; border:1px solid #81313B; }}
.status-error {{ background:#3B2424; color:#FFB0A9; border:1px solid #7A3F3F; }}
div.stButton > button[kind="primary"] {{ background:{RED}; border:1px solid {RED}; color:white; font-weight:700; }}
div.stButton > button[kind="primary"]:hover {{ background:#BD1727; border-color:#BD1727; color:white; }}
div.stDownloadButton > button {{ border-color:#555; }}
hr {{ border-color:#2B2B2B !important; }}
[data-testid="stDataFrame"] {{ border:1px solid #2B2B2B; border-radius:8px; }}
.small-note {{ color:{MUTED}; font-size:.82rem; }}
</style>
""", unsafe_allow_html=True)


def init_state():
    if "catalogue" not in st.session_state:
        st.session_state.catalogue = load_sample_catalogue()
    if "promo_runs" not in st.session_state:
        st.session_state.promo_runs = []
    if "review_decisions" not in st.session_state:
        st.session_state.review_decisions = {}
    if "active_result_id" not in st.session_state:
        st.session_state.active_result_id = None
    if "catalogue_version" not in st.session_state:
        st.session_state.catalogue_version = 1


def status_html(status: str) -> str:
    classes = {"VERIFIED": "status-verified", "NEEDS REVIEW": "status-review", "NO MATCH": "status-nomatch", "METADATA ERROR": "status-error"}
    return f'<span class="status {classes.get(status, "status-review")}">{status}</span>'


def write_raw_output(result: dict):
    out_dir = ROOT / "raw_outputs"
    out_dir.mkdir(exist_ok=True)
    safe = result.get("promo", {}).get("promo_id", "promo").replace("/", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = out_dir / f"{timestamp}_{safe}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def filter_catalogue_for_promo(promo: dict, catalogue: list[dict]) -> tuple[list[dict], list[str]]:
    filtered = catalogue
    notes = []
    lang = str(promo.get("language", "Unknown"))
    territory = str(promo.get("territory", "Unknown"))
    if lang and lang != "Unknown":
        filtered = [x for x in filtered if str(x.get("language", "Unknown")).lower() in {lang.lower(), "unknown", ""}]
        notes.append(f"Language filter: {lang} (records marked Unknown remain eligible).")
    if territory and territory != "Unknown":
        filtered = [x for x in filtered if str(x.get("territory", "Unknown")).lower() in {territory.lower(), "unknown", ""}]
        notes.append(f"Territory filter: {territory} (records marked Unknown remain eligible).")
    return filtered, notes


def run_match(promo: dict, catalogue: list[dict], use_semantic: bool = False):
    validation = validate_catalogue(catalogue)
    if not validation["valid"]:
        return {"promo": promo, "candidates": [], "status": "METADATA ERROR", "reasons": validation["errors"],
                "created_at": datetime.now(timezone.utc).isoformat(), "catalogue_version": st.session_state.catalogue_version}
    filtered_catalogue, filter_notes = filter_catalogue_for_promo(promo, catalogue)
    semantic_note = []
    try:
        candidates = score_candidates(promo, filtered_catalogue, top_k=5, use_semantic=use_semantic)
    except Exception as exc:
        if use_semantic:
            semantic_note.append(f"Local semantic model unavailable; lexical baseline used instead ({exc}).")
            candidates = score_candidates(promo, filtered_catalogue, top_k=5, use_semantic=False)
        else:
            raise
    status, reasons = decide_status(promo, candidates)
    reasons = filter_notes + semantic_note + reasons
    if not filtered_catalogue:
        status = "NO MATCH"
        reasons.insert(0, "No episodes passed the supplied language / territory filters. Unknown catalogue metadata is normally retained.")
    result = {
        "promo": promo, "candidates": candidates, "status": status, "reasons": reasons,
        "verifier": {"enabled": False, "verdict": "not_checked", "reason": "100% deterministic local retrieval; external LLM verifier disabled."},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "catalogue_version": st.session_state.catalogue_version,
        "retrieval_method": candidates[0].get("retrieval_mode", "lexical-baseline") if candidates else "no-candidate",
    }
    return result


init_state()

with st.sidebar:
    st.markdown('<div class="brand">PROMO<span>BRIDGE</span></div>', unsafe_allow_html=True)
    st.caption("Kuku-inspired promo-to-show traceability")
    st.markdown("---")
    validation = validate_catalogue(st.session_state.catalogue)
    st.markdown("**Workspace**")
    st.write(f"{validation['show_count']} shows · {validation['episode_count']} episodes")
    st.write(f"{validation['evidence_count']} evidence spans")
    if validation["valid"]:
        st.success("Catalogue structure valid", icon="✅")
    else:
        st.error("Catalogue needs correction", icon="⚠️")
    if st.button("↺  Reload demo catalogue", use_container_width=True):
        st.session_state.catalogue = load_sample_catalogue()
        st.session_state.catalogue_version += 1
        st.toast("Demo catalogue loaded")
        st.rerun()
    st.markdown("---")
    st.markdown("**Decision rules**")
    st.caption(f"≥ {HIGH_SCORE_THRESHOLD:.2f} + distinctive evidence + ≥ {MIN_TOP_TWO_MARGIN:.2f} margin → VERIFIED")
    st.caption(f"{LOW_SCORE_THRESHOLD:.2f}–{HIGH_SCORE_THRESHOLD - 0.01:.2f} or ambiguity → NEEDS REVIEW")
    st.caption(f"< {LOW_SCORE_THRESHOLD:.2f} → NO MATCH")
    st.caption("Scores are ranking signals, not probabilities.")
    st.markdown("---")
    st.caption("Prototype · Local-first · Synthetic demo content")

st.markdown('<div class="kicker">CONTENT OPERATIONS WORKSPACE</div>', unsafe_allow_html=True)
st.markdown("# Every promo. The right story.")
st.markdown("""<div class="hero"><div style="font-size:1.05rem;font-weight:700;margin-bottom:.3rem">PromoBridge</div>
<div style="color:#D8D8D8">Trace a promotional creative to the exact show, episode and screenplay evidence it advertises — then hand off a clean, reviewable manifest.</div>
<div style="color:#A7A7A7;font-size:.78rem;margin-top:.7rem">MVP: transcript-first matching · evidence-grounded results · human approval · CSV / JSON export</div></div>""", unsafe_allow_html=True)

tab_match, tab_catalogue, tab_eval, tab_about = st.tabs(["🎯  Match a promo", "📚  Catalogue", "🧪  Evaluation & export", "⚙️  Method & limits"])

with tab_match:
    left, right = st.columns([0.88, 1.12], gap="large")
    with left:
        st.subheader("1. Promo intake")
        with st.form("promo_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            promo_id = c1.text_input("Promo ID", value=f"PROMO-{uuid.uuid4().hex[:6].upper()}")
            platform = c2.selectbox("Platform", ["Instagram", "Facebook", "TikTok", "YouTube", "Other"])
            displayed_title = st.text_input("Title shown in ad (optional)", placeholder="e.g. The Last Promise")
            c3, c4 = st.columns(2)
            language = c3.selectbox("Promo language", ["Unknown", "English", "Hindi", "Tamil", "Telugu", "Kannada"])
            territory = c4.selectbox("Target territory", ["Unknown", "US", "India", "Singapore", "Global"])
            caption = st.text_area("Ad caption / description (optional)", height=78, placeholder="Paste the social caption or ad copy...")
            transcript = st.text_area("Promo dialogue transcript *", height=185, placeholder="Paste the words spoken or displayed in the promotional clip...\n\nExample: 'Stop the ceremony! This groom is already married.'")
            st.markdown("<div class='small-note'>Text-first prototype. It does not extract audio or read text from video frames.</div>", unsafe_allow_html=True)
            st.markdown("---")
            semantic_available = importlib.util.find_spec("sentence_transformers") is not None
            use_semantic = st.checkbox("Use local semantic retrieval for paraphrases (optional)", value=False, disabled=not semantic_available)
            if not semantic_available:
                st.caption("Deterministic lexical matching is active (TF-IDF + RapidFuzz token matching).")
            submitted = st.form_submit_button("Find matching show & episode", type="primary", use_container_width=True)
        if submitted:
            if promo_id.strip() and any(x.get("promo", {}).get("promo_id") == promo_id.strip() for x in st.session_state.promo_runs):
                st.error("Promo ID already exists in this workspace. Use a unique ID or edit the existing run.")
            elif not transcript.strip() and not caption.strip():
                st.error("Add dialogue or an ad caption. A title alone is not enough for reliable matching.")
            else:
                promo = {"promo_id": promo_id.strip() or f"PROMO-{uuid.uuid4().hex[:6].upper()}",
                         "displayed_title": displayed_title.strip(), "platform": platform,
                         "language": language, "territory": territory,
                         "caption": caption.strip(), "transcript_raw": transcript.strip(),
                         "transcript_normalized": " ".join(transcript.lower().split()),
                         "input_source": "manual_text"}
                result = run_match(promo, st.session_state.catalogue, use_semantic=use_semantic)
                st.session_state.promo_runs.insert(0, result)
                st.session_state.active_result_id = promo["promo_id"]
                write_raw_output(result)
                st.toast("Matching complete")
    with right:
        st.subheader("2. Match results")
        active = next((x for x in st.session_state.promo_runs if x["promo"]["promo_id"] == st.session_state.active_result_id), None)
        if not active:
            st.markdown("<div class='panel'><div style='color:#E32636;font-weight:800;font-size:.75rem;letter-spacing:.1em'>WAITING FOR INPUT</div><h3 style='margin:.45rem 0'>Your evidence-led match will appear here.</h3><div style='color:#A7A7A7'>Run a promo transcript to see ranked episodes, source dialogue, timestamps and a clear decision status.</div></div>", unsafe_allow_html=True)
        else:
            safe_promo_id = escape(str(active['promo'].get('promo_id', '')))
            safe_display_title = escape(str(active['promo'].get('displayed_title') or 'Untitled promotional creative'))
            st.markdown(f"<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem'><div><div class='small-note'>PROMO {safe_promo_id}</div><div style='font-size:1.1rem;font-weight:700'>{safe_display_title}</div></div>{status_html(active['status'])}</div>", unsafe_allow_html=True)
            if active.get("reasons"):
                for reason in active["reasons"]:
                    st.caption("• " + reason)
            if active.get("candidates"):
                candidate_rows = []
                for i, cand in enumerate(active["candidates"], start=1):
                    candidate_rows.append({"Rank": i, "Show": cand["canonical_title"], "Episode": cand["episode_id"],
                                           "Score": round(cand["score"], 3), "Content": round(cand["content_score"], 3),
                                           "Title": round(cand["title_score"], 3)})
                st.dataframe(pd.DataFrame(candidate_rows), use_container_width=True, hide_index=True)
                st.markdown("**Top candidate evidence**")
                top = active["candidates"][0]
                ev = top["evidence"]
                timing = f"{ev.get('start_time') or 'Timestamp unavailable'} – {ev.get('end_time') or 'Timestamp unavailable'}"
                safe_show = escape(str(top.get('canonical_title', '')))
                safe_episode_title = escape(str(top.get('episode_title', '')))
                safe_episode_id = escape(str(top.get('episode_id', '')))
                safe_evidence_id = escape(str(ev.get('evidence_id', '')))
                safe_timing = escape(timing)
                safe_source_text = escape(str(ev.get('text', '')))
                safe_release = escape(str(top.get('release_status', 'Unknown')))
                safe_destination = escape(str(top.get('destination_url') or 'UNKNOWN — not supplied'))
                safe_episode_number = escape(str(top.get('episode_number', '')))
                safe_line_start = escape(str(ev.get('source_line_start', '')))
                safe_line_end = escape(str(ev.get('source_line_end', '')))
                st.markdown(f"<div class='panel'><div style='font-weight:800;color:#E32636'>{safe_show} · Episode {safe_episode_number} — {safe_episode_title}</div><div class='small-note' style='margin:.35rem 0'>{safe_episode_id} · {safe_evidence_id} · {safe_timing} · Lines {safe_line_start}–{safe_line_end}</div><div style='color:#F1F1F1;line-height:1.55'>{safe_source_text}</div><div class='small-note' style='margin-top:.55rem'>End time uses the next scene timestamp as a boundary estimate when no explicit scene end is supplied. Availability: {safe_release} · Destination: {safe_destination}</div></div>", unsafe_allow_html=True)
                with st.expander("Inspect all candidate evidence"):
                    for idx, cand in enumerate(active["candidates"], start=1):
                        e = cand["evidence"]
                        st.markdown(f"**#{idx} · {cand['canonical_title']} · {cand['episode_id']} · {cand['score']:.3f}**")
                        st.caption(f"{e.get('evidence_id')} | {e.get('start_time') or 'No timestamp'} | lines {e.get('source_line_start')}–{e.get('source_line_end')}")
                        st.write(e.get("text", ""))
                with st.expander("Scoring & diagnostic breakdown"):
                    st.json({"top_candidate_component_scores": top.get("component_scores", {}),
                             "title_score": top.get("title_score"), "top_two_margin": round(top["score"] - (active["candidates"][1]["score"] if len(active["candidates"]) > 1 else 0), 4),
                             "retrieval_method": active.get("retrieval_method", "lexical-baseline")}, expanded=False)
                st.markdown("---")
                st.markdown("**3. Human review & handoff**")
                decision_key = active["promo"]["promo_id"]
                candidate_options = {f"{x['canonical_title']} · {x['episode_id']}": x["episode_id"] for x in active["candidates"]}
                chosen_label = st.selectbox("Select the correct episode (or keep the top candidate)", list(candidate_options.keys()), key=f"choose_{decision_key}")
                reviewer = st.text_input("Reviewer", value="Content Ops", key=f"reviewer_{decision_key}")
                review_reason = st.text_input("Review note (optional)", key=f"reason_{decision_key}")
                rb1, rb2 = st.columns(2)
                if rb1.button("✓ Approve mapping", type="primary", use_container_width=True, key=f"approve_{decision_key}"):
                    st.session_state.review_decisions[decision_key] = {"decision": "APPROVED", "selected_episode_id": candidate_options[chosen_label],
                        "reviewer": reviewer, "reason": review_reason, "reviewed_at": datetime.now(timezone.utc).isoformat()}
                    st.success("Mapping approved for export.")
                if rb2.button("✕ Reject as no match", use_container_width=True, key=f"reject_{decision_key}"):
                    st.session_state.review_decisions[decision_key] = {"decision": "REJECTED", "selected_episode_id": "",
                        "reviewer": reviewer, "reason": review_reason or "Reviewer rejected all candidates", "reviewed_at": datetime.now(timezone.utc).isoformat()}
                    st.warning("Mapping rejected. It will be marked rejected in the manifest.")
                saved = st.session_state.review_decisions.get(decision_key)
                if saved:
                    st.caption(f"Human decision: **{saved['decision']}** · {saved.get('reviewer','')} · {saved.get('reviewed_at','')}")
            else:
                st.warning("No candidate evidence was returned. Check the catalogue, add more text, or confirm that this creative belongs to the indexed shows.")
        if st.session_state.promo_runs:
            with st.expander("Recent promo runs"):
                for result in st.session_state.promo_runs[:8]:
                    if st.button(f"{result['promo']['promo_id']} · {result['status']}", key=f"load_{result['promo']['promo_id']}", use_container_width=True):
                        st.session_state.active_result_id = result['promo']['promo_id']
                        st.rerun()

with tab_catalogue:
    st.subheader("Screenplay catalogue")
    st.markdown("Upload one file per episode. Supported: TXT, DOCX, PDF and JSON. Filename convention recommended: `Show Title - E01 - Episode Title.txt`.")
    saved_catalogue_file = st.file_uploader("Or restore a previously exported PromoBridge catalogue JSON", type=["json"], accept_multiple_files=False, key="catalogue_json_restore")
    if saved_catalogue_file and st.button("Restore saved catalogue", key="restore_catalogue_button"):
        try:
            st.session_state.catalogue = load_catalogue_json(saved_catalogue_file.getvalue())
            st.session_state.catalogue_version += 1
            st.success("Saved catalogue restored.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not restore catalogue: {exc}")
    uploaded = st.file_uploader("Add screenplay files (one episode per file)", type=["txt", "md", "docx", "pdf", "json"], accept_multiple_files=True, key="screenplay_upload")
    col_a, col_b = st.columns([1, 1])
    with col_a:
        replace_catalogue = st.checkbox("Replace current catalogue (otherwise append)", value=False)
    with col_b:
        parse_clicked = st.button("Parse & add to catalogue", type="primary", disabled=not uploaded)
    if parse_clicked and uploaded:
        try:
            parsed = parse_uploaded_files(uploaded)
            combined = parsed if replace_catalogue else st.session_state.catalogue + parsed
            # Deduplicate on exact episode ID: new upload replaces the existing row.
            by_id = {x["episode_id"]: x for x in combined}
            st.session_state.catalogue = list(by_id.values())
            st.session_state.catalogue_version += 1
            st.success(f"Parsed {len(parsed)} episode file(s). Review inferred metadata below.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not parse upload: {exc}")
    validation = validate_catalogue(st.session_state.catalogue)
    m1, m2, m3, m4 = st.columns(4)
    for col, label, val in zip([m1,m2,m3,m4], ["Shows", "Episodes", "Evidence spans", "Parse warnings"],
                               [validation["show_count"], validation["episode_count"], validation["evidence_count"], len(validation["warnings"]) ]):
        col.markdown(f"<div class='metric'><div class='metric-label'>{label}</div><div class='metric-value'>{val}</div></div>", unsafe_allow_html=True)
    if validation["errors"]:
        for err in validation["errors"]: st.error(err)
    if validation["warnings"]:
        with st.expander(f"Parse warnings ({len(validation['warnings'])})"):
            for warning in validation["warnings"]: st.warning(warning)
    st.markdown("---")
    st.markdown("**Review and correct canonical metadata**")
    edit_df = catalogue_dataframe(st.session_state.catalogue)
    edited = st.data_editor(edit_df, use_container_width=True, hide_index=True, num_rows="fixed", key=f"catalogue_editor_{st.session_state.catalogue_version}",
                            column_config={"destination_url": st.column_config.TextColumn("destination_url", help="Optional user-supplied URL. Never fabricated."),
                                            "release_status": st.column_config.SelectboxColumn("release_status", options=["Unknown", "Available", "Coming soon", "Unavailable"], required=True),
                                            "language": st.column_config.TextColumn("language"), "territory": st.column_config.TextColumn("territory")})
    if st.button("Save catalogue metadata", type="primary"):
        st.session_state.catalogue = apply_catalogue_edits(st.session_state.catalogue, edited)
        st.session_state.catalogue_version += 1
        st.success("Metadata saved to this workspace session.")
        st.rerun()
    st.download_button("Download catalogue JSON", data=save_catalogue_json(st.session_state.catalogue), file_name="promobridge_catalogue.json", mime="application/json")
    st.caption("Edits persist for this browser session. Download the JSON to retain the edited catalogue between runs.")

with tab_eval:
    st.subheader("Evaluation & export")
    gold_path = ROOT / "evaluation" / "gold_set.csv"
    gold = pd.read_csv(gold_path).fillna("") if gold_path.exists() else pd.DataFrame()
    st.markdown("**Run the included labelled demo set**")
    st.caption("The gold set is synthetic and exists to test the prototype's behaviour. It is not Kuku performance data.")
    if not gold.empty:
        g1, g2, g3 = st.columns(3)
        g1.metric("Evaluation cases", len(gold))
        g2.metric("Positive examples", int(gold["case_type"].eq("positive").sum()))
        g3.metric("Ambiguous / negative", int(gold["case_type"].isin(["ambiguous", "negative"]).sum()))
    if st.button("Run evaluation on current catalogue", type="primary", disabled=gold.empty):
        outcomes = []
        for row in gold.to_dict(orient="records"):
            promo = {"promo_id": row["promo_id"], "displayed_title": row.get("displayed_title", ""),
                     "caption": row.get("caption", ""), "transcript_raw": row["transcript"],
                     "language": "English", "territory": "US", "platform": "Evaluation", "input_source": "gold_set"}
            candidates = score_candidates(promo, st.session_state.catalogue, top_k=5)
            status, reasons = decide_status(promo, candidates)
            top_id = candidates[0]["episode_id"] if candidates else ""
            expected = str(row.get("expected_episode_id", "") or "")
            outcomes.append({"promo_id": row["promo_id"], "case_type": row["case_type"], "expected_episode_id": expected,
                             "top1_episode_id": top_id, "top1_correct": bool(expected and top_id == expected),
                             "top3_correct": bool(expected and expected in [x["episode_id"] for x in candidates[:3]]),
                             "status": status, "top_score": round(candidates[0]["score"], 4) if candidates else 0.0,
                             "candidates": [x["episode_id"] for x in candidates], "reasons": reasons})
        positives = [x for x in outcomes if x["case_type"] == "positive"]
        abstention_cases = [x for x in outcomes if x["case_type"] in {"ambiguous", "negative"}]
        top1 = sum(x["top1_correct"] for x in positives) / max(1, len(positives))
        top3 = sum(x["top3_correct"] for x in positives) / max(1, len(positives))
        false_verified = sum(x["status"] == "VERIFIED" for x in abstention_cases) / max(1, len(abstention_cases))
        metrics = {"cases": len(outcomes), "positive_cases": len(positives), "top1_accuracy_positive": round(top1, 3),
                   "top3_recall_positive": round(top3, 3), "false_verified_rate_on_ambiguous_and_negative": round(false_verified, 3),
                   "note": "Synthetic test set only; not production accuracy or calibrated confidence."}
        st.session_state.eval_outcomes = outcomes
        st.session_state.eval_metrics = metrics
        out_dir = ROOT / "raw_outputs"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "evaluation_run.json").write_text(json.dumps({"metrics": metrics, "outcomes": outcomes}, indent=2), encoding="utf-8")
    if "eval_metrics" in st.session_state:
        metrics = st.session_state.eval_metrics
        st.markdown("---")
        st.markdown("**Latest evaluation results**")
        x1,x2,x3 = st.columns(3)
        x1.metric("Top-1 accuracy", f"{metrics['top1_accuracy_positive']:.1%}")
        x2.metric("Top-3 recall", f"{metrics['top3_recall_positive']:.1%}")
        x3.metric("False VERIFIED rate", f"{metrics['false_verified_rate_on_ambiguous_and_negative']:.1%}")
        st.json(metrics)
        st.dataframe(pd.DataFrame(st.session_state.eval_outcomes), use_container_width=True, hide_index=True)
        st.download_button("Download evaluation results CSV", export_csv(st.session_state.eval_outcomes), "evaluation_results.csv", "text/csv")
        st.download_button("Download evaluation results JSON", json.dumps({"metrics": metrics, "outcomes": st.session_state.eval_outcomes}, indent=2), "evaluation_results.json", "application/json")
    st.markdown("---")
    st.markdown("**Campaign manifest**")
    manifest_rows = []
    for result in st.session_state.promo_runs:
        promo_id = result["promo"]["promo_id"]
        decision = st.session_state.review_decisions.get(promo_id)
        row = build_manifest_row(result["promo"], result, decision)
        if decision and decision.get("decision") == "REJECTED":
            row.update({"status": "REJECTED", "show_id": "", "canonical_title": "", "episode_id": "",
                        "evidence_id": "", "destination_url": "UNKNOWN"})
        manifest_rows.append(row)
    if manifest_rows:
        st.dataframe(pd.DataFrame(manifest_rows), use_container_width=True, hide_index=True)
        st.download_button("Export manifest CSV", export_csv(manifest_rows), "promobridge_manifest.csv", "text/csv", type="primary")
        full = {"product": "PromoBridge", "catalogue_version": st.session_state.catalogue_version,
                "catalogue_summary": validate_catalogue(st.session_state.catalogue),
                "runs": st.session_state.promo_runs, "review_decisions": st.session_state.review_decisions}
        st.download_button("Export full traceability JSON", export_json(full), "promobridge_traceability.json", "application/json")
    else:
        st.info("Run at least one promo match to generate a manifest.")

with tab_about:
    st.subheader("How PromoBridge decides")
    st.markdown("""
    **1 · Parse and preserve evidence**  
    Each uploaded file becomes an episode record. Scene/timestamp boundaries create evidence spans with stable IDs and original line offsets.

    **2 · Retrieve likely episodes**  
    The default baseline combines word TF-IDF, character n-gram TF-IDF, meaningful-token overlap, fuzzy text similarity and exact phrase detection. An optional local `all-MiniLM-L6-v2` sentence-transformer can add semantic similarity for paraphrases. The best evidence span represents each episode.

    **3 · Apply conservative rules**  
    The rules engine assigns VERIFIED, NEEDS REVIEW, NO MATCH or METADATA ERROR. A high score alone is never enough: the text must be distinctive, directly present in evidence and separated from the runner-up.

    **4 · Human approval and export**  
    An operator can select the correct candidate, approve or reject it, then export CSV / JSON with the source evidence and destination URL (only when supplied).
    """)
    st.markdown("---")
    st.subheader("Important limits")
    st.warning("A VERIFIED result means the promo text is strongly traceable to a screenplay excerpt under this prototype's rules. It does not prove that the show is currently available in the viewer's territory, that a deep link works, or that an ad click converts to a view.")
    st.markdown("- No video editing, OCR, audio transcription, ASR or ad-platform integration.\n- No automatic deep-link generation. Missing destination URLs remain UNKNOWN.\n- No cross-language semantic matching in this MVP.\n- The included demo scripts and evaluation cases are synthetic, not Kuku content or performance data.")
    st.markdown("---")
    st.subheader("Run locally")
    st.code("python -m venv .venv\n# Windows: .venv\\Scripts\\activate\n# macOS/Linux: source .venv/bin/activate\npip install -r requirements.txt\nstreamlit run app.py", language="bash")
    st.markdown("**Optional free local semantic retrieval**")
    st.code("pip install -r requirements-semantic.txt", language="bash")
    st.caption("The first run downloads the open-weight sentence-transformer model. Check model licence and hosting constraints before commercial deployment.")
