from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from src.catalogue import load_sample_catalogue
from src.scoring import score_candidates, decide_status


def run():
    catalogue = load_sample_catalogue()
    gold = pd.read_csv(ROOT / "evaluation" / "gold_set.csv").fillna("")
    outcomes = []
    for row in gold.to_dict(orient="records"):
        promo = {"promo_id": row["promo_id"], "displayed_title": row["displayed_title"],
                 "transcript_raw": row["transcript"], "caption": row["caption"]}
        candidates = score_candidates(promo, catalogue, top_k=5)
        status, reasons = decide_status(promo, candidates)
        expected = str(row["expected_episode_id"])
        ids = [x["episode_id"] for x in candidates]
        outcomes.append({"promo_id": row["promo_id"], "case_type": row["case_type"],
                         "expected_episode_id": expected, "top1_episode_id": ids[0] if ids else "",
                         "top1_correct": bool(expected and ids and ids[0] == expected),
                         "top3_correct": bool(expected and expected in ids[:3]),
                         "status": status, "top_score": candidates[0]["score"] if candidates else 0.0,
                         "candidate_episode_ids": ids, "reasons": reasons})
    positive = [x for x in outcomes if x["case_type"] == "positive"]
    nonpositive = [x for x in outcomes if x["case_type"] in {"negative", "ambiguous"}]
    metrics = {
        "case_count": len(outcomes), "positive_count": len(positive),
        "top1_accuracy_positive": round(sum(x["top1_correct"] for x in positive) / max(1, len(positive)), 4),
        "top3_recall_positive": round(sum(x["top3_correct"] for x in positive) / max(1, len(positive)), 4),
        "false_verified_rate_negative_and_ambiguous": round(sum(x["status"] == "VERIFIED" for x in nonpositive) / max(1, len(nonpositive)), 4),
        "caveat": "Synthetic evaluation only. Scores are not calibrated probabilities or production metrics."
    }
    payload = {"metrics": metrics, "outcomes": outcomes}
    out = ROOT / "raw_outputs" / "evaluation_run.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return payload


if __name__ == "__main__":
    run()
