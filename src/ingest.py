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


def infer_metadata(filename: str, text: str = "") -> dict[str, Any]:
    path = Path(filename)
    stem = _clean_filename(filename)
    match = EPISODE_RE.search(stem)

    parent_title = ""
    for parent in path.parents:
        pname = parent.name.strip()
        if pname and pname not in {"kuku_screenplay_pack", "sample_catalogue", "data", ".", "upload", "temp"}:
            parent_title = pname
            break

    if match:
        number = int(match.group(1))
        before = stem[:match.start()].strip(" _-")
        after = stem[match.end():].strip(" _-")
        title = before or parent_title or "Untitled Show"
        episode_title = after or f"Episode {number}"
    else:
        number = 1
        title = parent_title or stem or "Untitled Show"
        episode_title = "Episode 1"

    if text:
        ep_num_m = re.search(r"(?i)^EPISODE\s+NUMBER:\s*(?:Episode\s*)?(\d+)", text, re.MULTILINE)
        if ep_num_m:
            number = int(ep_num_m.group(1))
            if not match or not after:
                episode_title = f"Episode {number}"

    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_").upper() or "UNKNOWN_SHOW"
    episode_id = f"{slug}_EP_{number:03d}"

    aliases = []
    if "broken soldier" in title.lower() or "duke" in title.lower():
        aliases = ["I Married a Broken Soldier", "Broken Soldier", "He was a Duke"]

    return {
        "show_id": slug,
        "canonical_title": title,
        "aliases": aliases,
        "language": "English" if "broken soldier" in title.lower() else "Unknown",
        "territory": "Global" if "broken soldier" in title.lower() else "Unknown",
        "release_status": "Available" if "broken soldier" in title.lower() else "Unknown",
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


def _is_kuku_script(text: str) -> bool:
    return bool(
        re.search(r"^\s*SCENE\s+\d+", text, re.MULTILINE) and
        re.search(r"(?i)Scene heading:|Actions and dialogue:|\*\*CAMERA:|\*\*ACTION:|\*\*[A-Z\s._-]+:\*\*", text)
    )


def _split_kuku_evidence(text: str, episode_id: str, source_filename: str) -> tuple[list[EvidenceSpan], list[str]]:
    warnings: list[str] = []
    spans: list[EvidenceSpan] = []
    lines = text.splitlines()

    # 1. Preamble/Logline span
    preamble = []
    preamble_end = 1
    for idx, l in enumerate(lines[:25], start=1):
        if l.strip().startswith("---"):
            preamble_end = idx
            break
        if l.strip():
            preamble.append(l.strip())
            preamble_end = idx
    if preamble:
        spans.append(EvidenceSpan(
            evidence_id=f"{episode_id}_LOGLINE",
            episode_id=episode_id,
            scene_index=0,
            start_time="00:00.00",
            end_time=None,
            speaker="LOGLINE",
            text=" ".join(preamble),
            source_line_start=1,
            source_line_end=preamble_end,
        ))

    # 2. Scene blocks
    scene_blocks = re.split(r"(?=SCENE\s+\d+)", text)
    if len(scene_blocks) <= 1 and not text.strip().startswith("SCENE"):
        scene_blocks = [text]

    span_counter = len(spans)

    for sc_text in scene_blocks:
        if not sc_text.strip():
            continue
        sc_match = re.search(r"SCENE\s+(\d+)", sc_text)
        sc_num = int(sc_match.group(1)) if sc_match else 1

        heading_m = re.search(r"Scene heading:\s*(.*)", sc_text)
        heading = heading_m.group(1).strip() if heading_m else ""

        start_m = re.search(r"Scene start:\s*(\d+:\d+(?:\.\d+)?)", sc_text)
        sc_start = start_m.group(1) if start_m else None

        end_m = re.search(r"Scene end:\s*(\d+:\d+(?:\.\d+)?)", sc_text)
        sc_end = end_m.group(1) if end_m else None

        dialogues = []
        actions = []
        cur_speaker = None
        cur_time_start = None
        cur_time_end = None
        is_action = False

        for line_idx, line in enumerate(sc_text.splitlines(), start=1):
            line_str = line.strip()
            if not line_str:
                continue

            spk_m = re.match(r"^\*\*([A-Za-z0-9\s._-]+?)(?:\s*\([^)]*\))?:\*\*", line_str)
            if spk_m:
                tag = spk_m.group(1).strip().upper()
                if tag == "ACTION":
                    is_action = True
                    cur_speaker = None
                elif tag == "CAMERA":
                    is_action = False
                    cur_speaker = None
                else:
                    is_action = False
                    cur_speaker = spk_m.group(1).strip()
                continue

            time_m = re.search(r"Start:\s*\(([^)]+)\)\s*\|\s*End:\s*\(([^)]+)\)", line_str)
            if time_m:
                cur_time_start = time_m.group(1).strip()
                cur_time_end = time_m.group(2).strip()
                continue

            quote_m = re.match(r'^[\"|\u201c]([^\"]+)[\"|\u201d]', line_str)
            if quote_m and cur_speaker:
                clean_q = quote_m.group(1).strip()
                dialogues.append({
                    "speaker": cur_speaker,
                    "start_time": cur_time_start or sc_start,
                    "end_time": cur_time_end or sc_end,
                    "text": f'{cur_speaker}: "{clean_q}"',
                    "raw_text": clean_q,
                    "line_start": line_idx,
                    "line_end": line_idx,
                })
                cur_speaker = None
                cur_time_start = None
                cur_time_end = None
                continue

            if is_action and line_str and not line_str.startswith("**"):
                actions.append({
                    "start_time": cur_time_start or sc_start,
                    "end_time": cur_time_end or sc_end,
                    "text": f"ACTION: {line_str}",
                    "line_start": line_idx,
                    "line_end": line_idx,
                })
                is_action = False
                cur_time_start = None
                cur_time_end = None

        # Add individual dialogue lines as evidence spans
        for d in dialogues:
            span_counter += 1
            spans.append(EvidenceSpan(
                evidence_id=f"{episode_id}_SC_{span_counter:03d}",
                episode_id=episode_id,
                scene_index=sc_num,
                start_time=d["start_time"],
                end_time=d["end_time"],
                speaker=d["speaker"],
                text=d["text"],
                source_line_start=d["line_start"],
                source_line_end=d["line_end"],
            ))

        # Add conversational beats (windows of 3 dialogue lines)
        window_size = 3
        step = 2
        if len(dialogues) > 2:
            for i in range(0, len(dialogues), step):
                chunk = dialogues[i:i + window_size]
                if len(chunk) < 2:
                    continue
                span_counter += 1
                joined = " ".join(item["text"] for item in chunk)
                spans.append(EvidenceSpan(
                    evidence_id=f"{episode_id}_BEAT_{span_counter:03d}",
                    episode_id=episode_id,
                    scene_index=sc_num,
                    start_time=chunk[0]["start_time"],
                    end_time=chunk[-1]["end_time"],
                    speaker=chunk[0]["speaker"],
                    text=joined,
                    source_line_start=chunk[0]["line_start"],
                    source_line_end=chunk[-1]["line_end"],
                ))

        # Add key action cues if available
        for a in actions:
            span_counter += 1
            spans.append(EvidenceSpan(
                evidence_id=f"{episode_id}_ACT_{span_counter:03d}",
                episode_id=episode_id,
                scene_index=sc_num,
                start_time=a["start_time"],
                end_time=a["end_time"],
                speaker="ACTION",
                text=a["text"],
                source_line_start=a["line_start"],
                source_line_end=a["line_end"],
            ))

    if not spans:
        warnings.append("No structured dialogue/action spans extracted from Kuku script; using full text.")
        spans.append(EvidenceSpan(
            evidence_id=f"{episode_id}_SC_001",
            episode_id=episode_id,
            scene_index=1,
            start_time=None,
            end_time=None,
            speaker=None,
            text=text[:2000],
            source_line_start=1,
            source_line_end=len(lines),
        ))

    return spans, warnings


def split_evidence(text: str, episode_id: str, source_filename: str) -> tuple[list[EvidenceSpan], list[str]]:
    if _is_kuku_script(text):
        return _split_kuku_evidence(text, episode_id, source_filename)

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
    meta = infer_metadata(filename, text)
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
