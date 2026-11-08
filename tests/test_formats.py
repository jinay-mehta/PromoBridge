from io import BytesIO

from docx import Document

from src.ingest import parse_episode_file
from src.catalogue import save_catalogue_json, load_catalogue_json, load_sample_catalogue


def test_docx_parser_extracts_screenplay_text():
    doc = Document()
    doc.add_paragraph("[00:00:03] SCENE 1 - INT. ROOM - NIGHT")
    doc.add_paragraph("MAYA: The secret is inside the letter.")
    stream = BytesIO()
    doc.save(stream)
    record = parse_episode_file("Test Show - E01 - Pilot.docx", stream.getvalue()).to_dict()
    assert "secret is inside the letter" in record["evidence"][0]["text"].lower()


def test_workspace_catalogue_export_can_be_restored():
    original = load_sample_catalogue()
    restored = load_catalogue_json(save_catalogue_json(original).encode("utf-8"))
    assert len(restored) == len(original)
    assert restored[0]["episode_id"] == original[0]["episode_id"]


def test_duplicate_episode_ids_are_rejected():
    from src.catalogue import validate_catalogue
    records = load_sample_catalogue()
    duplicate = dict(records[0])
    duplicate["evidence"] = [dict(x) for x in records[0]["evidence"]]
    records.append(duplicate)
    result = validate_catalogue(records)
    assert not result["valid"]
    assert any("Duplicate episode_id" in x for x in result["errors"])
