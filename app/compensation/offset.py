"""补偿抵扣计算与每期客户余额。

关账口径：

- 有回执：按剩余金额（金额减已用）冲减本月收入，余额归零。
- 无回执且在本期结束后仍有效：保留在客户余额，不冲减收入。
- 无回执且在本期失效：本期了结，余额归零，不冲减收入。
- 本期开始前已失效：不应再挂余额，拒绝签发，等待人工处理。
- 同一补偿已在其他已签发批次处理：跳过，避免重复冲减。

签发前还会独立复核两条不变量：期末仍挂余额的补偿必须仍在有效期内，收入
冲减必须有回执；再逐客户核对“期初 - 冲减 - 了结 = 期末”。
"""

from collections import defaultdict
from datetime import date, timedelta

from app.compensation.schema import month_start

APPLIED = "APPLIED"
RETAINED = "RETAINED"
SETTLED = "SETTLED"
USED = "USED"
ALREADY_APPLIED = "ALREADY_APPLIED"
EXPIRED_BALANCE = "EXPIRED_BALANCE"
RECONCILE_MISMATCH = "RECONCILE_MISMATCH"
OFFSET_WITHOUT_RECEIPT = "OFFSET_WITHOUT_RECEIPT"
BALANCE_AFTER_EXPIRY = "BALANCE_AFTER_EXPIRY"

BLOCKING = (EXPIRED_BALANCE,)
CONSUMING = (APPLIED, SETTLED)


def period_bounds(period):
    start = month_start(period)
    following = (
        date(start.year + 1, 1, 1)
        if start.month == 12
        else date(start.year, start.month + 1, 1)
    )
    return start, following - timedelta(days=1)


def classify(row, start, close, ledger):
    """返回 (处理结论, 已签发批次)。"""
    if row["compensation"] in ledger:
        return ALREADY_APPLIED, ledger[row["compensation"]]
    remaining = row["amount_cents"] - row["used_cents"]
    if remaining <= 0:
        return USED, None
    if row["receipt_present"]:
        return APPLIED, None
    if row["expires_on"] > close:
        return RETAINED, None
    if row["expires_on"] >= start:
        return SETTLED, None
    return EXPIRED_BALANCE, None


def treatment(row, start, close, ledger):
    kind, prior = classify(row, start, close, ledger)
    remaining = row["amount_cents"] - row["used_cents"]
    return {
        "compensation": row["compensation"],
        "customer": row["customer"],
        "period": row["period"],
        "issued_on": row["issued_on"].isoformat(),
        "expires_on": row["expires_on"].isoformat(),
        "receipt_on": row["receipt_on"],
        "receipt_date": row["receipt_date"].isoformat()
        if row["receipt_date"]
        else None,
        "receipt_present": row["receipt_present"],
        "amount_cents": row["amount_cents"],
        "used_cents": row["used_cents"],
        "remaining_cents": remaining,
        "opening_cents": remaining,
        "offset_cents": remaining if kind == APPLIED else 0,
        "settled_cents": remaining if kind == SETTLED else 0,
        "closing_cents": remaining if kind in (RETAINED, *BLOCKING) else 0,
        "treatment": kind,
        "prior_run": prior,
        "expired": row["expires_on"] <= close,
        "note": row["note"],
    }


def _invariants(item):
    """不依赖处理结论、直接从原始字段复核的拒签条件。"""
    found = []
    if item["treatment"] in BLOCKING:
        found.append(item["treatment"])
    elif item["closing_cents"] > 0 and item["expired"]:
        found.append(BALANCE_AFTER_EXPIRY)
    if item["offset_cents"] > 0 and not item["receipt_present"]:
        found.append(OFFSET_WITHOUT_RECEIPT)
    unique = []
    for reason in found:
        if reason not in unique:
            unique.append(reason)
    return unique


def evaluate(period, rows, ledger=None):
    ledger = ledger or {}
    start, close = period_bounds(period)
    treatments = [treatment(row, start, close, ledger) for row in rows]
    skipped = [item for item in treatments if item["treatment"] == ALREADY_APPLIED]
    counted = [item for item in treatments if item["treatment"] != ALREADY_APPLIED]

    opening = sum(item["opening_cents"] for item in counted)
    offset = sum(item["offset_cents"] for item in counted)
    settled = sum(item["settled_cents"] for item in counted)
    closing = sum(item["closing_cents"] for item in counted)
    delta = opening - offset - settled - closing

    by_customer = defaultdict(list)
    for item in counted:
        by_customer[item["customer"]].append(item)
    customers = []
    for name in sorted(by_customer):
        items = by_customer[name]
        customers.append(
            {
                "customer": name,
                "compensations": len(items),
                "opening_cents": sum(item["opening_cents"] for item in items),
                "offset_cents": sum(item["offset_cents"] for item in items),
                "settled_cents": sum(item["settled_cents"] for item in items),
                "closing_cents": sum(item["closing_cents"] for item in items),
            }
        )
    customer_delta = sum(
        item["opening_cents"]
        - item["offset_cents"]
        - item["settled_cents"]
        - item["closing_cents"]
        for item in customers
    )

    violations = []
    for item in counted:
        for reason in _invariants(item):
            violations.append(
                {
                    "compensation": item["compensation"],
                    "customer": item["customer"],
                    "reason": reason,
                    "closing_cents": item["closing_cents"],
                }
            )
    reconciled = delta == 0 and customer_delta == 0
    if not reconciled:
        violations.append(
            {
                "compensation": None,
                "customer": None,
                "reason": RECONCILE_MISMATCH,
                "closing_cents": closing,
            }
        )

    return {
        "period": period,
        "period_start": start.isoformat(),
        "period_end": close.isoformat(),
        "records": [item["compensation"] for item in treatments],
        "counts": {
            "compensations": len(treatments),
            "applied": sum(1 for item in counted if item["treatment"] == APPLIED),
            "retained": sum(1 for item in counted if item["treatment"] == RETAINED),
            "settled": sum(1 for item in counted if item["treatment"] == SETTLED),
            "used": sum(1 for item in counted if item["treatment"] == USED),
            "skipped": len(skipped),
        },
        "treatments": treatments,
        "skipped": skipped,
        "customers": customers,
        "totals": {
            "opening_cents": opening,
            "offset_cents": offset,
            "settled_cents": settled,
            "closing_cents": closing,
            "delta_cents": delta,
        },
        "violations": violations,
        "reconciled": reconciled,
        "status": violations[0]["reason"] if violations else "READY",
        "releasable": reconciled and not violations,
    }
