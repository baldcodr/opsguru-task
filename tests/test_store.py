from pathlib import Path

from app.ingestion import ingest_csv
from app.store import (
    load_account_snapshots,
    load_dispositions,
    load_invoices,
    load_metadata,
    write_canonical_store,
)


def test_canonical_store_round_trip(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    ingestion = ingest_csv(root / "cloudnova_invoices.csv")
    store_path = tmp_path / "canonical.sqlite3"

    write_canonical_store(store_path, ingestion)

    assert store_path.exists()
    assert not store_path.with_suffix(".sqlite3.tmp").exists()
    assert load_invoices(store_path) == ingestion.invoices
    assert load_dispositions(store_path) == ingestion.dispositions
    assert load_account_snapshots(store_path) == ingestion.account_snapshots

    metadata = load_metadata(store_path)
    assert metadata["source_sha256"] == ingestion.profile.source_sha256
    assert metadata["source_data_rows"] == str(ingestion.profile.source_data_rows)
    assert metadata["authoritative_invoice_count"] == str(
        ingestion.profile.authoritative_invoice_count
    )
    assert metadata["normalization_version"] == "1"
    assert len(metadata["structured_fingerprint"]) == 64