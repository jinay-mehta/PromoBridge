from __future__ import annotations

import io
import json
import re
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TIME_RE = re.compile(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d{1,3})?)(?!\d)")
SCENE_RE = re.compile(r"(?i)^\s*(?:scene\s+\d+|(?:int\.?|ext\.?|int/ext|ext/int)\b.*|\[?scene\s*[:#-].*)")
EPISODE_RE = re.compile(r"(?i)(?:^|[\s_-])(?:episode|ep|e)\s*0*(\d+)(?:\b|[_-])")


@dataclass
class EvidenceSpan:
    evidence_id: str
    episode_id: str
    scene_index: int
    start_time: str | None
    end_time: str | None
    speaker: str | None
    text: str
    source_line_start: int
    source_line_end: int


@dataclass
class EpisodeRecord:
    show_id: str
    canonical_title: str
    aliases: list[str]
    language: str
    territory: str
    release_status: str
    episode_id: str
    episode_number: int
    episode_title: str
    source_filename: str
    source_file_id: str
    screenplay_text: str
    evidence: list[EvidenceSpan]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        item = asdict(self)
        return item


def _decode_text(filename: str, payload: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md", ".csv"}:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        return payload.decode("utf-8", errors="replace")
    if suffix == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(payload))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        return "\n".join(parts)
    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(payload))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".json":
        data = json.loads(payload.decode("utf-8-sig"))
        if isinstance(data, dict):
            if "screenplay_text" in data:
                return str(data["screenplay_text"])
            if "text" in data:
                return str(data["text"])
            if "scenes" in data and isinstance(data["scenes"], list):
                return "\n\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in data["scenes"])
        if isinstance(data, list):
            return "\n\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in data)
        return str(data)
    raise ValueError(f"Unsupported file type: {suffix}. Use TXT, DOCX, PDF or JSON.")


def _clean_filename(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()


def infer_metadata(filename: str) -> dict[str, Any]:
    stem = _clean_filename(filename)
    match = EPISODE_RE.search(stem)
    if match:
        number = int(match.group(1))
        before = stem[:match.start()].strip(" _-")
        after = stem[match.end():].strip(" _-")
        title = before or "Untitled Show"
        episode_title = after or f"Episode {number}"
    else:
        number = 1
        title = stem or "Untitled Show"
        episode_title = "Episode 1"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").upper() or "UNKNOWN_SHOW"
    episode_id = f"{slug}_EP_{number:03d}"
    return {
        "show_id": slug,
        "canonical_title": title,
        "aliases": [],
        "language": "Unknown",
        "territory": "Unknown",
        "release_status": "Unknown",
        "episode_id": episode_id,
        "episode_number": number,
        "episode_title": episode_title,
    }


def _speaker_and_text(line: str) -> tuple[str | None, str]:
    clean = TIME_RE.sub("", line).strip(" -|\t[]")
    # Typical screenplay dialogue line: CHARACTER: spoken words
    m = re.match(r"^([A-Z][A-Z0-9 _.'-]{1,30}):\s*(.+)$", clean)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, clean


def split_evidence(text: str, episode_id: str, source_filename: str) -> tuple[list[EvidenceSpan], list[str]]:
    lines = text.splitlines()
    warnings: list[str] = []
    spans: list[EvidenceSpan] = []
    current: list[str] = []
    current_start: int | None = None
    current_time: str | None = None
    scene_index = 0
    last_time: str | None = None

    def flush(end_line: int, next_time: str | None = None) -> None:
        nonlocal current, current_start, current_time, scene_index
        joined = " ".join(part.strip() for part in current if part.strip())
        joined = re.sub(r"\s+", " ", joined).strip()
        if joined:
            scene_index += 1
            speakers = re.findall(r"\b([A-Z][A-Z0-9 _.'-]{1,25}):", joined)
            speaker = speakers[0].strip() if speakers else None
            spans.append(EvidenceSpan(
                evidence_id=f"{episode_id}_SC_{scene_index:03d}",
                episode_id=episode_id,
                scene_index=scene_index,
                start_time=current_time,
                end_time=next_time,
                speaker=speaker,
                text=joined,
                source_line_start=current_start or 1,
                source_line_end=max(current_start or 1, end_line),
            ))
        current = []
        current_start = None
        current_time = None

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        time_match = TIME_RE.search(line)
        timestamp = time_match.group(1) if time_match else None
        is_scene_heading = bool(SCENE_RE.match(line))
        # A new timecode or scene heading closes the previous evidence span.
        if timestamp or is_scene_heading:
            if current:
                # Ignore file-level title/preamble lines before the first timestamp.
                if timestamp and current_time is None:
                    current = []
                    current_start = None
                else:
                    flush(idx - 1, timestamp)
            if timestamp:
                current_time = timestamp
                last_time = timestamp
                content = TIME_RE.sub("", line).strip(" -|[]")
                if content and not SCENE_RE.match(content):
                    if current_start is None:
                        current_start = idx
                    current.append(content)
                continue
            if is_scene_heading:
                current_time = last_time if not spans else None
                current_start = idx
                current.append(line)
                continue
        if current_start is None:
            current_start = idx
        current.append(line)
    if current:
        flush(len(lines))

    if not spans:
        warnings.append("No structured scene/timestamp markers detected; used the full screenplay as one evidence span.")
        nonempty = [x.strip() for x in lines if x.strip()]
        joined = re.sub(r"\s+", " ", " ".join(nonempty)).strip()
        if joined:
            spans = [EvidenceSpan(
                evidence_id=f"{episode_id}_SC_001", episode_id=episode_id, scene_index=1,
                start_time=None, end_time=None, speaker=None, text=joined,
                source_line_start=1, source_line_end=max(1, len(lines)),
            )]
    if spans and not any(s.start_time for s in spans):
        warnings.append("No timestamps found; matching is available with source line offsets only.")
    return spans, warnings


def parse_episode_file(filename: str, payload: bytes, overrides: dict[str, Any] | None = None) -> EpisodeRecord:
    text = _decode_text(filename, payload).strip()
    if not text:
        raise ValueError(f"{filename}: file contains no readable text.")
    meta = infer_metadata(filename)
    if overrides:
        meta.update({k: v for k, v in overrides.items() if v is not None})
    evidence, warnings = split_evidence(text, str(meta["episode_id"]), filename)
    return EpisodeRecord(
        show_id=str(meta["show_id"]), canonical_title=str(meta["canonical_title"]),
        aliases=list(meta.get("aliases", [])) if not isinstance(meta.get("aliases"), str) else [x.strip() for x in meta["aliases"].split(",") if x.strip()],
        language=str(meta.get("language", "Unknown")), territory=str(meta.get("territory", "Unknown")),
        release_status=str(meta.get("release_status", "Unknown")), episode_id=str(meta["episode_id"]),
        episode_number=int(meta.get("episode_number", 1)), episode_title=str(meta.get("episode_title", "")),
        source_filename=filename, source_file_id=f"FILE_{hashlib.sha256(filename.encode('utf-8') + payload).hexdigest()[:12].upper()}",
        screenplay_text=text, evidence=evidence, warnings=warnings,
    )
