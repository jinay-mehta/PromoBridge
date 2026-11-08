from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.catalogue import load_sample_catalogue
from src.ingest import parse_episode_file
from src.scoring import score_candidates, decide_status

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Run PromoBridge promo-to-screenplay matching from the command line.")
    parser.add_argument("--transcript", required=True, help="Promo dialogue transcript")
    parser.add_argument("--caption", default="", help="Optional ad caption")
    parser.add_argument("--title", default="", help="Optional title shown in the ad")
    parser.add_argument("--catalogue-dir", default="", help="Optional directory containing one screenplay file per episode (.txt/.docx/.pdf/.json)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--semantic", action="store_true", help="Use optional local sentence-transformer retrieval")
    parser.add_argument("--output", default="raw_outputs/cli_result.json")
    args = parser.parse_args()

    if args.catalogue_dir:
        directory = Path(args.catalogue_dir)
        files = sorted([p for p in directory.iterdir() if p.suffix.lower() in {".txt", ".md", ".docx", ".pdf", ".json"}])
        catalogue = [parse_episode_file(p.name, p.read_bytes()).to_dict() for p in files]
    else:
        catalogue = load_sample_catalogue()

    promo = {"promo_id": "CLI_PROMO", "transcript_raw": args.transcript,
             "caption": args.caption, "displayed_title": args.title,
             "platform": "CLI", "language": "Unknown", "territory": "Unknown"}
    candidates = score_candidates(promo, catalogue, top_k=max(1, min(args.top_k, 10)), use_semantic=args.semantic)
    status, reasons = decide_status(promo, candidates)
    result = {"promo": promo, "status": status, "reasons": reasons,
              "candidates": candidates, "catalogue_validation": {
                  "episodes": len(catalogue), "shows": len(set(x["show_id"] for x in catalogue))}}
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Status: {status}")
    print("Reasons:", "; ".join(reasons) or "None")
    if candidates:
        top = candidates[0]
        ev = top["evidence"]
        print(f"Top match: {top['canonical_title']} | {top['episode_id']} | score={top['score']:.3f}")
        print(f"Evidence: {ev['evidence_id']} | {ev.get('start_time') or 'timestamp unavailable'}")
    print(f"Full result saved to: {output}")


if __name__ == "__main__":
    main()
