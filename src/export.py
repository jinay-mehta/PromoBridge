from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any


def build_manifest_row(promo: dict[str, Any], result: dict[str, Any], decision: dict[str, Any] | None = None) -> dict[str, Any]:
    top = (result.get("candidates") or [{}])[0]
    selected_id = (decision or {}).get("selected_episode_id") or top.get("episode_id", "")
    selected = next((x for x in result.get("candidates", []) if x.get("episode_id") == selected_id), top)
    ev = selected.get("evidence", {})
    is_abstention = not decision and result.get("status") in {"NO MATCH", "METADATA ERROR"}
    return {
        "promo_id": promo.get("promo_id", ""), "displayed_title": promo.get("displayed_title", ""),
        "platform": promo.get("platform", ""), "language": promo.get("language", "Unknown"),
        "territory": promo.get("territory", "Unknown"), "show_id": "" if is_abstention else selected.get("show_id", ""),
        "canonical_title": "" if is_abstention else selected.get("canonical_title", ""), "episode_id": "" if is_abstention else selected.get("episode_id", ""),
        "episode_number": "" if is_abstention else selected.get("episode_number", ""), "episode_title": "" if is_abstention else selected.get("episode_title", ""),
        "evidence_id": "" if is_abstention else ev.get("evidence_id", ""), "start_time": "" if is_abstention else (ev.get("start_time") or ""),
        "end_time": "" if is_abstention else (ev.get("end_time") or ""), "source_line_start": "" if is_abstention else ev.get("source_line_start", ""),
        "source_line_end": "" if is_abstention else ev.get("source_line_end", ""), "match_score": round(selected.get("score", 0), 4),
        "status": decision.get("decision", result.get("status", "NOT CHECKED")) if decision else result.get("status", "NOT CHECKED"),
        "reviewer": (decision or {}).get("reviewer", ""), "review_reason": (decision or {}).get("reason", ""),
        "destination_url": (selected.get("destination_url", "") or "UNKNOWN") if not is_abstention else "UNKNOWN",
    }


def export_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def export_json(payload: dict[str, Any]) -> str:
    payload = {**payload, "exported_at": datetime.now(timezone.utc).isoformat()}
    return json.dumps(payload, ensure_ascii=False, indent=2)
