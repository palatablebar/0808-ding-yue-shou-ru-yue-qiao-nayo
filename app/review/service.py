from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.compensation.detect import is_compensation
from app.compensation.pipeline import build as build_compensation
from app.compensation.service import identifiers
from app.config import RULE_VERSION
from app.modules.pipeline import run


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _report(store, data):
    if not is_compensation(data):
        return run(data)
    return build_compensation(data, 5, store.ledger(identifiers(data)))


def _body(report):
    return {key: value for key, value in report.items() if key != "manifest"}


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f"{RULE_VERSION}:{fingerprint}".encode()).hexdigest()
    try:
        existing = store.load(run_id)
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise
    else:
        if (
            existing["report"].get("kind") != "compensation"
            or existing["status"] == "APPROVED"
        ):
            return existing
        report = _report(store, data)
        report["manifest"] = existing["report"]["manifest"]
        if _body(report) == _body(existing["report"]):
            return existing
        return store.refresh(run_id, report)
    report = _report(store, data)
    report["manifest"] = dict(
        sha256=fingerprint,
        version=RULE_VERSION,
        created=now(),
        duration_ms=round((monotonic() - start) * 1000, 3),
        bytes=len(data),
        run_id=run_id,
        kind=report.get("kind", "mrr"),
    )
    return store.register(run_id, report, data)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in ("APPROVED", "HELD")
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = store.load(run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] == "APPROVED":
        raise DomainIssue("RUN_FINALIZED")
    if status == "APPROVED":
        for attempt in range(3):
            report = _approval_report(store, run_id, current)
            if not report["balance"]["releasable"]:
                raise DomainIssue("UNRESOLVED_ISSUES")
            try:
                return store.revise(
                    run_id, revision, status, note.strip(), now(), report=report
                )
            except DomainIssue as error:
                if error.code != "COMPENSATION_ALREADY_POSTED" or attempt == 2:
                    raise
                current = store.load(run_id)
                if current["status"] == "APPROVED":
                    raise DomainIssue("RUN_FINALIZED") from error
                if current["revision"] != revision:
                    raise DomainIssue("STALE_REVIEW") from error
    return store.revise(run_id, revision, status, note.strip(), now())


def _approval_report(store, run_id, current):
    """签发前用当前台账重算，防止并发或新增台账导致重复冲减。"""
    report = current["report"]
    if report.get("kind") != "compensation":
        return report
    data = store.source(run_id)
    if data is None:
        return report
    fresh = build_compensation(data, 5, store.ledger(identifiers(data)))
    fresh["manifest"] = report["manifest"]
    return fresh
