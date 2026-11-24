"""补偿账单的批次编排。

阶段与收入样例一致：采信、校验、计算、判定、对账。补偿按笔处理，
每笔在关账口径下只会落到一种处理结论，报告保留逐笔处理与逐客户余额。
"""

from app.compensation.offset import CONSUMING, evaluate
from app.compensation.service import inspect
from app.spec import COMPENSATION


def _counts(intake):
    return {key: value for key, value in intake.items() if key != "rows"}


def _gate(intake, *, status, releasable=False, reconciled=False, extra=None):
    accounted = (
        intake["accepted"] + intake["rejected"] + intake["blank"] + intake["repeated"]
    )
    return {
        "input": intake["input"],
        "accepted": intake["accepted"],
        "isolated": intake["rejected"],
        "ignored": intake["blank"] + intake["repeated"],
        "accounted": accounted,
        "balanced": accounted == intake["input"],
        "reconciled": reconciled,
        "releasable": bool(releasable)
        and accounted == intake["input"]
        and intake["rejected"] == 0,
        "status": status,
        "violations": [],
        **(extra or {}),
    }


def _violation(reason):
    return {"compensation": None, "customer": None, "reason": reason}


def build(data, stage=5, ledger=None):
    intake = inspect(data)
    report = {
        "kind": "compensation",
        "project": {"name": COMPENSATION["name"], "actor": COMPENSATION["actor"]},
        "stages": [list(item) for item in COMPENSATION["stages"]],
        "chart": COMPENSATION["chart"],
        "intake": _counts(intake),
    }
    if stage == 1:
        return report

    rows = intake["rows"]
    periods = sorted({row["period"] for row in rows})
    report["prepare"] = {"count": len(rows), "details": {"periods": periods}}

    if not rows:
        if stage >= 4:
            report["status"] = "NO_COMPENSATION"
        if stage >= 5:
            report["balance"] = _gate(intake, status="NO_COMPENSATION")
        return report
    if len(periods) > 1:
        if stage >= 4:
            report["status"] = "MIXED_PERIOD"
            report["violations"] = [_violation("MIXED_PERIOD")]
        if stage >= 5:
            report["balance"] = _gate(
                intake,
                status="MIXED_PERIOD",
                extra={
                    "periods": periods,
                    "violations": report.get("violations", []),
                },
            )
        return report

    period = periods[0]
    result = evaluate(period, rows, ledger)
    report["prepare"]["details"].update(
        start=result["period_start"], end=result["period_end"]
    )
    if stage >= 3:
        report["period"] = period
        report["treatments"] = result["treatments"]
        report["customers"] = result["customers"]
        report["totals"] = result["totals"]
        report["counts"] = result["counts"]
        report["skipped"] = result["skipped"]
        report["reconciled"] = result["reconciled"]
        report["ledger"] = [
            item["compensation"]
            for item in result["treatments"]
            if item["treatment"] in CONSUMING
        ]
    if stage >= 4:
        report["status"] = result["status"]
        report["violations"] = result["violations"]
    if stage >= 5:
        report["balance"] = _gate(
            intake,
            status=result["status"],
            releasable=result["releasable"],
            reconciled=result["reconciled"],
            extra={
                "period": period,
                "period_start": result["period_start"],
                "period_end": result["period_end"],
                "counts": result["counts"],
                "totals": result["totals"],
                "violations": result["violations"],
            },
        )
    return report
