from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.business import DomainIssue
from app.review.service import execute, review


def test_parallel_rerun_commits_single_row(store, clean):
    start = Barrier(4)

    def load():
        start.wait(3)
        return execute(store, clean)

    with ThreadPoolExecutor(max_workers=4) as threads:
        results = list(threads.map(lambda _: load(), range(4)))
    assert all(result == results[0] for result in results)
    assert len(store.list()) == 1


def test_parallel_review_has_one_winner(store, dirty):
    run = execute(store, dirty)
    start = Barrier(2)

    def attempt(note):
        start.wait(3)
        try:
            return review(store, run["id"], dict(revision=0, status="HELD", note=note))[
                "status"
            ]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(attempt, ["来源待检查", "分组待处理"]))
    assert sorted(results) == ["HELD", "STALE_REVIEW"]
    assert store.load(run["id"])["revision"] == 1


def test_parallel_approval_of_overlapping_batches_posts_once(store, clean):
    from conftest import ROOT

    payable = (ROOT / "sample_data" / "compensation.csv").read_bytes()
    extra = payable + "CMP-1007,CUST-D,2026-11,2026-11-01,2027-01-31,5000,0,2026-11-10,新增\n".encode()
    first = execute(store, payable)
    second = execute(store, extra)
    start = Barrier(2)

    def approve(run):
        start.wait(3)
        try:
            return review(
                store, run["id"], dict(revision=0, status="APPROVED", note="并发签发核对")
            )["status"]
        except DomainIssue as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as threads:
        results = list(threads.map(approve, [first, second]))
    assert results.count("APPROVED") == 2
    posted = store.ledger_entries()
    assert len({row["compensation"] for row in posted}) == len(posted)
    assert sum(row["offset_cents"] for row in posted) == 87000
