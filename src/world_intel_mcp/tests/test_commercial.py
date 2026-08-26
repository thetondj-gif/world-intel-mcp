from pathlib import Path

from world_intel_mcp.commercial import (
    CommercialStore,
    delivery_pressure,
    factual_record,
    normalise_notice,
    supplier_momentum,
)


def test_factual_record_keeps_raw_and_provenance_separate():
    record = factual_record(
        "contracts_finder",
        "https://example.test/source",
        {"releases": [{"ocid": "ocds-1"}]},
        stable_identifier="ocds-1",
    )
    assert record["record_kind"] == "factual-source-record"
    assert record["raw"]["releases"][0]["ocid"] == "ocds-1"
    assert record["provenance"]["stable_identifier"] == "ocds-1"
    assert len(record["provenance"]["payload_sha256"]) == 64
    assert record["derived_signals"] == []


def test_notice_and_scores_are_explicit_inference():
    release = {
        "ocid": "ocds-award-1",
        "date": "2026-08-25T10:00:00Z",
        "tag": ["award"],
        "buyer": {"name": "Example Council"},
        "tender": {"title": "Digital transformation", "value": {"amount": 250000, "currency": "GBP"}},
        "awards": [{"value": {"amount": 250000}, "suppliers": [{"name": "Example Supplier Ltd"}]}],
    }
    notice = normalise_notice(release, "contracts_finder", "a" * 64)
    momentum = supplier_momentum([notice])
    pressure = delivery_pressure([notice])
    assert notice["supplier"] == "Example Supplier Ltd"
    assert momentum[0]["is_inference"] is True
    assert pressure[0]["is_inference"] is True
    assert momentum[0]["evidence_refs"] == ["a" * 64]
    assert pressure[0]["evidence_refs"] == ["a" * 64]


def test_store_deduplicates_observations_and_persists_watchlist(tmp_path: Path):
    store = CommercialStore(tmp_path / "commercial.db")
    record = factual_record("ons", "https://example.test/ons", {"items": []})
    store.save_record(record)
    store.save_record(record)
    assert len(store.ledger()) == 1
    item = store.add_watch("company", "01234567", "Example Ltd")
    assert item["external_id"] == "01234567"
    assert store.watchlist()[0]["label"] == "Example Ltd"
