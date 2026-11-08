from pathlib import Path

from src.catalogue import load_sample_catalogue, validate_catalogue
from src.ingest import parse_episode_file
from src.scoring import score_candidates, decide_status


def test_demo_catalogue_has_three_shows_and_at_least_ten_episodes():
    records = load_sample_catalogue()
    info = validate_catalogue(records)
    assert info["valid"]
    assert info["show_count"] >= 3
    assert info["episode_count"] >= 10
    assert info["evidence_count"] >= 25


def test_kuku_screenplay_pack_integration():
    records = load_sample_catalogue()
    kuku_eps = [x for x in records if "broken soldier" in x["canonical_title"].lower()]
    assert len(kuku_eps) == 50
    ep1 = next(x for x in kuku_eps if x["episode_number"] == 1)
    assert ep1["episode_id"] == "I_MARRIED_A_BROKEN_SOLDIER_HE_WAS_A_DUKE_EP_001"
    assert len(ep1["evidence"]) > 10

    promo = {
        "transcript_raw": "You let me believe I was walking toward my husband!",
        "caption": "",
        "displayed_title": "I Married a Broken Soldier"
    }
    candidates = score_candidates(promo, records)
    status, reasons = decide_status(promo, candidates)
    assert candidates[0]["episode_id"] == "I_MARRIED_A_BROKEN_SOLDIER_HE_WAS_A_DUKE_EP_001"
    assert status == "VERIFIED"


def test_exact_dialogue_match_returns_correct_episode_and_evidence():
    records = load_sample_catalogue()
    promo = {"transcript_raw": "Stop the ceremony! This groom is already married.",
             "caption": "", "displayed_title": "The Last Promise"}
    candidates = score_candidates(promo, records)
    status, reasons = decide_status(promo, candidates)
    assert candidates[0]["episode_id"] == "THE_LAST_PROMISE_EP_001"
    assert candidates[0]["evidence"]["evidence_id"].endswith("SC_003")
    assert status == "VERIFIED"


def test_unrelated_ad_abstains():
    records = load_sample_catalogue()
    promo = {"transcript_raw": "A spaceship captain discovers a new planet after the engine fails.",
             "caption": "", "displayed_title": ""}
    candidates = score_candidates(promo, records)
    status, reasons = decide_status(promo, candidates)
    assert status == "NO MATCH"


def test_very_short_transcript_never_verifies():
    records = load_sample_catalogue()
    promo = {"transcript_raw": "Tell me the truth.", "caption": "", "displayed_title": "The Last Promise"}
    candidates = score_candidates(promo, records)
    status, reasons = decide_status(promo, candidates)
    assert status != "VERIFIED"
    assert status == "NEEDS REVIEW"


def test_parser_preserves_scene_timestamps():
    path = Path(__file__).resolve().parents[1] / "data" / "sample_catalogue" / "The Last Promise - E01 - The Wedding Deal.txt"
    record = parse_episode_file(path.name, path.read_bytes()).to_dict()
    assert len(record["evidence"]) == 3
    assert record["evidence"][0]["start_time"] == "00:00:03"
    assert record["evidence"][1]["start_time"] == "00:00:38"
    assert record["evidence"][2]["start_time"] == "00:01:11"


def test_supplied_destination_url_must_be_http_or_https():
    from src.catalogue import validate_catalogue
    records = load_sample_catalogue()
    records[0]["destination_url"] = "javascript:alert(1)"
    validation = validate_catalogue(records)
    assert not validation["valid"]
    assert any("destination_url" in x for x in validation["errors"])
