import json


def artifact(run):
    report = run["report"]
    packet = {
        "schema": "review-evidence/1",
        "kind": report.get("kind", "mrr"),
        "manifest": report["manifest"],
        "balance": report.get("balance"),
        "cases": report.get("cases"),
        "intake": report["intake"],
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    if report.get("kind") == "compensation":
        for key in (
            "period",
            "treatments",
            "customers",
            "totals",
            "counts",
            "skipped",
            "violations",
            "ledger",
        ):
            packet[key] = report.get(key)
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
