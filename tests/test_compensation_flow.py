import io

import pytest

from app.business import DomainIssue
from app.compensation.pipeline import build
from app.compensation.service import inspect
from app.review.service import execute, review
from conftest import ROOT


@pytest.fixture
def payable():
    return (ROOT / "sample_data" / "compensation.csv").read_bytes()


@pytest.fixture
def blocked():
    return (ROOT / "sample_data" / "compensation_blocked.csv").read_bytes()


def test_payable_sample_reconciles(payable):
    report = build(payable)
    assert report["status"] == "READY"
    assert report["balance"]["balanced"]
    assert report["balance"]["reconciled"]
    assert report["balance"]["releasable"]
    assert report["totals"] == {
        "opening_cents": 137000,
        "offset_cents": 82000,
        "settled_cents": 25000,
        "closing_cents": 30000,
        "delta_cents": 0,
    }


def test_payable_sample_treatments(payable):
    items = {item["compensation"]: item for item in build(payable)["treatments"]}
    assert items["CMP-1001"]["treatment"] == "APPLIED"
    assert items["CMP-1002"]["treatment"] == "SETTLED"
    assert items["CMP-1003"]["treatment"] == "RETAINED"
    assert items["CMP-1004"]["treatment"] == "APPLIED"
    assert items["CMP-1005"]["treatment"] == "USED"
    assert items["CMP-1006"]["treatment"] == "APPLIED"


def test_income_offset_equals_balance_reduction(payable):
    report = build(payable)
    totals = report["totals"]
    assert totals["opening_cents"] - totals["offset_cents"] - totals["settled_cents"] == totals["closing_cents"]
    assert sum(c["closing_cents"] for c in report["customers"]) == totals["closing_cents"]
    assert sum(c["offset_cents"] for c in report["customers"]) == totals["offset_cents"]


def test_blocked_sample_is_rejected(blocked):
    report = build(blocked)
    assert report["status"] == "EXPIRED_BALANCE"
    reasons = {item["reason"] for item in report["violations"]}
    assert "EXPIRED_BALANCE" in reasons
    assert not report["balance"]["releasable"]


def test_blocked_sample_isolates_bad_rows(blocked):
    intake = inspect(blocked)
    assert intake["reasons"]["DUPLICATE_CONFLICT"] == 2
    assert intake["reasons"]["DUPLICATE_REPLAY"] == 1
    assert intake["reasons"]["COLUMN_COUNT"] == 1
    assert intake["reasons"]["USED_EXCEEDS_AMOUNT"] == 1
    assert intake["reasons"]["INVALID_DATE"] == 1


def test_duplicate_conflict_removes_all_copies(blocked):
    isolated = [row for row in inspect(blocked)["isolation"] if row["compensation"] == "CMP-2003"]
    assert len(isolated) == 2
    accepted = [row["compensation"] for row in inspect(blocked)["rows"]]
    assert "CMP-2003" not in accepted


def test_repeated_header_is_ignored(blocked):
    assert inspect(blocked)["repeated"] == 1


def test_approval_posts_offsets_to_ledger(store, payable):
    run = execute(store, payable)
    review(store, run["id"], dict(revision=0, status="APPROVED", note="本期抵扣核对完成"))
    entries = {row["compensation"]: row for row in store.ledger_entries()}
    assert set(entries) == {"CMP-1001", "CMP-1002", "CMP-1004", "CMP-1006"}
    assert entries["CMP-1001"]["offset_cents"] == 50000
    assert entries["CMP-1002"]["settled_cents"] == 25000


def test_release_is_refused_for_expired_balance(store, blocked):
    run = execute(store, blocked)
    with pytest.raises(DomainIssue, match="UNRESOLVED_ISSUES"):
        review(store, run["id"], dict(revision=0, status="APPROVED", note="试图签发"))
    assert store.ledger_entries() == []


def test_rerun_does_not_double_count(store, payable):
    first = execute(store, payable)
    review(store, first["id"], dict(revision=0, status="APPROVED", note="首轮抵扣核对"))
    second = execute(store, payable)
    assert second["id"] == first["id"] and second["status"] == "APPROVED"
    assert sum(row["offset_cents"] for row in store.ledger_entries()) == 82000


def test_new_batch_skips_already_posted(store, payable):
    first = execute(store, payable)
    review(store, first["id"], dict(revision=0, status="APPROVED", note="首轮抵扣核对"))
    extra = payable + "CMP-1007,CUST-D,2026-11,2026-11-01,2027-01-31,5000,0,2026-11-10,新增\n".encode()
    second = execute(store, extra)
    report = second["report"]
    assert report["counts"]["skipped"] == 4
    assert {item["compensation"] for item in report["skipped"]} == {
        "CMP-1001",
        "CMP-1002",
        "CMP-1004",
        "CMP-1006",
    }
    assert report["totals"]["offset_cents"] == 5000
    assert report["balance"]["releasable"]


def test_second_release_same_compensation_cannot_double_offset(store, payable):
    first = execute(store, payable)
    review(store, first["id"], dict(revision=0, status="APPROVED", note="首轮抵扣核对"))
    replay = execute(store, payable)
    assert replay["report"]["ledger"] == first["report"]["ledger"]
    assert sum(row["offset_cents"] for row in store.ledger_entries()) == 82000


def test_compensation_detected_independently_of_mrr(client, payable):
    preview = client.post(
        "/api/stages/calculate",
        data={"file": (io.BytesIO(payable), "comp.csv")},
    )
    assert preview.status_code == 200
    assert preview.json["kind"] == "compensation"
    assert preview.json["counts"]["applied"] == 3


def test_ledger_endpoint_reports_totals(client):
    run = client.post("/api/runs", data={"sample": "compensation"}).json
    client.patch(
        f"/api/runs/{run['id']}",
        json=dict(revision=0, status="APPROVED", note="本期抵扣核对完成"),
    )
    ledger = client.get("/api/ledger").json
    assert ledger["offset_cents"] == 82000
    assert ledger["settled_cents"] == 25000


def test_evidence_carries_compensation_detail(store, payable):
    from app.evidence.render import artifact
    import json

    run = execute(store, payable)
    packet = json.loads(artifact(run))
    assert packet["kind"] == "compensation"
    assert len(packet["treatments"]) == 6
    assert packet["totals"]["offset_cents"] == 82000


def test_stage_preview_does_not_write_ledger(client, payable):
    response = client.post(
        "/api/stages/policy", data={"file": (io.BytesIO(payable), "comp.csv")}
    )
    assert response.status_code == 200
    assert client.get("/api/ledger").json["items"] == []


def test_overlapping_approvals_do_not_double_post(store, payable):
    extra = payable + "CMP-1007,CUST-D,2026-11,2026-11-01,2027-01-31,5000,0,2026-11-10,新增\n".encode()
    extended = execute(store, extra)
    review(store, extended["id"], dict(revision=0, status="APPROVED", note="先签发扩展批次"))
    original = execute(store, payable)
    approved = review(
        store, original["id"], dict(revision=0, status="APPROVED", note="再签发原批次")
    )
    assert {item["compensation"] for item in approved["report"]["skipped"]} == {
        "CMP-1001",
        "CMP-1002",
        "CMP-1004",
        "CMP-1006",
    }
    assert sum(row["offset_cents"] for row in store.ledger_entries()) == 87000
    assert len(store.ledger_entries()) == 5


def test_approval_refuses_when_balance_became_stale(store, payable):
    original = execute(store, payable)
    review(store, original["id"], dict(revision=0, status="HELD", note="先暂缓待核"))
    extended = execute(
        store,
        payable + "CMP-1007,CUST-D,2026-11,2026-11-01,2027-01-31,5000,0,2026-11-10,新增\n".encode(),
    )
    review(store, extended["id"], dict(revision=0, status="APPROVED", note="先签发扩展批次"))
    approved = review(
        store, original["id"], dict(revision=1, status="APPROVED", note="再签发原批次")
    )
    assert approved["report"]["totals"]["offset_cents"] == 0
    assert approved["report"]["balance"]["reconciled"]
