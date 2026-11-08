from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

import pandas as pd

from .ingest import EpisodeRecord, parse_episode_file

SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf", ".json"}


def parse_uploaded_files(uploaded_files: list[Any], overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    overrides = overrides or {}
    for file in uploaded_files:
        name = getattr(file, "name", None) or file.get("name")
        payload = file.getvalue() if hasattr(file, "getvalue") else file.get("bytes", b"")
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        record = parse_episode_file(name, payload, overrides.get(name))
        records.append(record.to_dict())
    return records


def load_sample_catalogue(root: Path | None = None) -> list[dict[str, Any]]:
    root = root or Path(__file__).resolve().parents[1] / "data" / "sample_catalogue"
    records: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.txt")):
        records.append(parse_episode_file(path.name, path.read_bytes()).to_dict())
    return records


def validate_catalogue(records: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if any(not isinstance(x, dict) for x in records):
        return {"valid": False, "errors": ["Catalogue contains a record that is not a JSON object."], "warnings": [],
                "show_count": 0, "episode_count": len(records), "evidence_count": 0}
    show_ids = [str(x.get("show_id", "")).strip() for x in records]
    episode_ids = [str(x.get("episode_id", "")).strip() for x in records]
    if not records:
        errors.append("Catalogue is empty. Load the demo catalogue or upload screenplay files.")
    if any(not x for x in show_ids):
        errors.append("One or more episodes have a blank show_id.")
    if any(not x for x in episode_ids):
        errors.append("One or more episodes have a blank episode_id.")
    if len(episode_ids) != len(set(episode_ids)):
        errors.append("Duplicate episode_id values detected. Episode IDs must be unique.")
    # Repeated canonical titles under different IDs are suspicious, not always invalid.
    title_to_ids: dict[str, set[str]] = {}
    for rec in records:
        title = str(rec.get("canonical_title", "")).strip().casefold()
        if not title:
            errors.append(f"{rec.get('episode_id', 'Unknown episode')}: canonical title is blank.")
        title_to_ids.setdefault(title, set()).add(str(rec.get("show_id", "")))
        evidence = rec.get("evidence")
        if not isinstance(evidence, list):
            errors.append(f"{rec.get('episode_id')}: evidence must be a list of spans.")
        elif not evidence:
            warnings.append(f"{rec.get('episode_id')}: no evidence spans were extracted.")
        else:
            for ev in evidence:
                if not isinstance(ev, dict) or not ev.get("evidence_id") or not isinstance(ev.get("text"), str):
                    errors.append(f"{rec.get('episode_id')}: malformed evidence span; each span needs evidence_id and text.")
                    break
        destination = str(rec.get("destination_url", "") or "").strip()
        if destination:
            parsed = urlparse(destination)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{rec.get('episode_id')}: destination_url must be a full http(s) URL or blank.")
        warning_items = rec.get("warnings", [])
        if isinstance(warning_items, list):
            for warning in warning_items:
                warnings.append(f"{rec.get('episode_id')}: {warning}")
    for title, ids in title_to_ids.items():
        if title and len(ids) > 1:
            warnings.append(f"Canonical title '{title}' appears under multiple show IDs.")
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "show_count": len(set(show_ids)), "episode_count": len(records),
            "evidence_count": sum(len(x.get("evidence", [])) if isinstance(x.get("evidence", []), list) else 0 for x in records)}


def catalogue_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for x in records:
        rows.append({
            "show_id": x.get("show_id"), "canonical_title": x.get("canonical_title"),
            "aliases": ", ".join(x.get("aliases", [])) if isinstance(x.get("aliases", []), list) else str(x.get("aliases", "")), "episode_id": x.get("episode_id"),
            "episode_number": x.get("episode_number"), "episode_title": x.get("episode_title"),
            "language": x.get("language", "Unknown"), "territory": x.get("territory", "Unknown"),
            "release_status": x.get("release_status", "Unknown"),
            "destination_url": x.get("destination_url", ""),
            "evidence_spans": len(x.get("evidence", [])) if isinstance(x.get("evidence", []), list) else 0, "source_filename": x.get("source_filename", ""),
        })
    return pd.DataFrame(rows)


def apply_catalogue_edits(records: list[dict[str, Any]], edited: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    rows = edited.to_dict(orient="records")
    for idx, rec in enumerate(records):
        row = rows[idx] if idx < len(rows) else {}
        updated = dict(rec)
        for key in ("show_id", "canonical_title", "episode_id", "episode_title", "language", "territory", "release_status", "destination_url"):
            value = row.get(key)
            if value is not None and not pd.isna(value) and str(value).strip():
                updated[key] = str(value).strip()
        number = row.get("episode_number")
        if number is not None and not pd.isna(number) and str(number).strip():
            updated["episode_number"] = int(number)
        aliases = row.get("aliases", "")
        updated["aliases"] = [] if aliases is None or pd.isna(aliases) or not str(aliases).strip() else [x.strip() for x in str(aliases).split(",") if x.strip()]
        # Keep evidence IDs stable only when the episode ID is unchanged. If an ID is edited, cascade it.
        old_id = str(rec.get("episode_id"))
        new_id = str(updated["episode_id"])
        if new_id != old_id:
            for ev in updated.get("evidence", []):
                ev["episode_id"] = new_id
                ev["evidence_id"] = ev["evidence_id"].replace(old_id, new_id, 1)
        out.append(updated)
    return out


def save_catalogue_json(records: list[dict[str, Any]]) -> str:
    return json.dumps(records, ensure_ascii=False, indent=2)


def load_catalogue_json(payload: bytes) -> list[dict[str, Any]]:
    data = json.loads(payload.decode("utf-8-sig"))
    if isinstance(data, dict) and isinstance(data.get("catalogue"), list):
        data = data["catalogue"]
    if not isinstance(data, list):
        raise ValueError("Workspace catalogue JSON must contain a list of episode records.")
    required = {"show_id", "canonical_title", "episode_id", "evidence"}
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict) or not required.issubset(item) or not isinstance(item.get("evidence"), list):
            raise ValueError(f"Record {index} is not a valid PromoBridge episode record.")
        if isinstance(item.get("aliases"), str):
            item["aliases"] = [x.strip() for x in item["aliases"].split(",") if x.strip()]
        elif not isinstance(item.get("aliases", []), list):
            item["aliases"] = []
        item.setdefault("language", "Unknown")
        item.setdefault("territory", "Unknown")
        item.setdefault("release_status", "Unknown")
        item.setdefault("warnings", [])
    return data
