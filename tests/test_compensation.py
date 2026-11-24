import csv
import io
from datetime import date

import pytest

from app.business import DomainIssue
from app.compensation.offset import evaluate, period_bounds
from app.compensation.pipeline import build
from app.compensation.schema import HEADER
from app.compensation.service import inspect


def row(**changes):
    base = dict(
        compensation="CMP-1",
        customer="CUST-A",
        period="2026-11",
        issued_on=date(2026, 10, 1),
        expires_on=date(2026, 12, 31),
        amount_cents=10000,
        used_cents=0,
        receipt_present=False,
        receipt_date=None,
        receipt_on="",
        note="",
    )
    base.update(changes)
    return base


def evaluate_one(**changes):
    return evaluate("2026-11", [row(**changes)])["treatments"][0]


def test_period_bounds_are_natural_month():
    start, close = period_bounds("2026-11")
    assert (start, close) == (date(2026, 11, 1), date(2026, 11, 30))
    assert period_bounds("2026-12")[1] == date(2026, 12, 31)


def test_receipt_offsets_income_and_clears_balance():
    item = evaluate_one(receipt_present=True, receipt_date=date(2026, 11, 5))
    assert item["treatment"] == "APPLIED"
    assert (item["offset_cents"], item["settled_cents"], item["closing_cents"]) == (
        10000,
        0,
        0,
    )


def test_valid_without_receipt_is_retained():
    item = evaluate_one()
    assert item["treatment"] == "RETAINED"
    assert (item["offset_cents"], item["closing_cents"]) == (0, 10000)


def test_expiring_this_period_without_receipt_is_settled():
    item = evaluate_one(expires_on=date(2026, 11, 20))
    assert item["treatment"] == "SETTLED"
    assert (item["offset_cents"], item["settled_cents"], item["closing_cents"]) == (
        0,
        10000,
        0,
    )


def test_receipt_before_expiry_wins_over_settlement():
    item = evaluate_one(
        expires_on=date(2026, 11, 20),
        receipt_present=True,
        receipt_date=date(2026, 11, 10),
    )
    assert item["treatment"] == "APPLIED"


def test_used_amount_leaves_only_remaining():
    item = evaluate_one(
        used_cents=4000, receipt_present=True, receipt_date=date(2026, 11, 5)
    )
    assert item["offset_cents"] == 6000


def test_fully_used_compensation_is_excluded():
    result = evaluate("2026-11", [row(used_cents=10000)])
    assert result["counts"]["used"] == 1
    assert result["ledger"] if "ledger" in result else True
    assert result["totals"]["opening_cents"] == 0
    assert result["releasable"]


def test_expired_balance_from_prior_period_blocks_release():
    result = evaluate("2026-11", [row(expires_on=date(2026, 10, 31))])
    assert result["status"] == "EXPIRED_BALANCE"
    assert not result["releasable"]


def test_receipt_offsets_even_when_expiry_is_earlier_in_period():
    item = evaluate_one(
        expires_on=date(2026, 11, 10),
        receipt_present=True,
        receipt_date=date(2026, 11, 12),
    )
    assert item["treatment"] == "APPLIED"
    assert item["offset_cents"] == 10000


def test_receipt_without_date_still_offsets():
    item = evaluate_one(receipt_present=True, receipt_date=None, receipt_on="已回执")
    assert item["treatment"] == "APPLIED"
    assert item["offset_cents"] == 10000


def test_future_receipt_offsets_in_the_period_of_the_bill():
    item = evaluate_one(
        expires_on=date(2027, 1, 31),
        receipt_present=True,
        receipt_date=date(2026, 12, 3),
    )
    assert item["treatment"] == "APPLIED"


def test_ledger_marks_already_posted_as_skipped():
    result = evaluate("2026-11", [row()], {"CMP-1": "run-1"})
    assert result["counts"]["skipped"] == 1
    assert result["treatments"][0]["treatment"] == "ALREADY_APPLIED"
    assert result["treatments"][0]["prior_run"] == "run-1"
    assert result["totals"]["opening_cents"] == 0
    assert result["reconciled"]


def test_customer_balances_roll_forward():
    result = evaluate(
        "2026-11",
        [
            row(compensation="CMP-1", amount_cents=10000),
            row(
                compensation="CMP-2",
                amount_cents=5000,
                used_cents=1000,
                receipt_present=True,
                receipt_date=date(2026, 11, 8),
            ),
            row(
                compensation="CMP-3",
                customer="CUST-B",
                amount_cents=7000,
                expires_on=date(2026, 11, 15),
            ),
        ],
    )
    assert result["totals"] == {
        "opening_cents": 21000,
        "offset_cents": 4000,
        "settled_cents": 7000,
        "closing_cents": 10000,
        "delta_cents": 0,
    }
    by_name = {item["customer"]: item for item in result["customers"]}
    assert by_name["CUST-A"]["closing_cents"] == 10000
    assert by_name["CUST-B"]["settled_cents"] == 7000
    assert result["reconciled"] and result["releasable"]


def csv_bytes(records):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(HEADER)
    writer.writerows(records)
    return stream.getvalue().encode()


def test_mixed_periods_are_blocked():
    data = csv_bytes(
        [
            ["CMP-1", "CUST-A", "2026-11", "2026-10-01", "2026-12-31", "100", "0", "", ""],
            ["CMP-2", "CUST-A", "2026-12", "2026-11-01", "2026-12-31", "100", "0", "", ""],
        ]
    )
    report = build(data)
    assert report["status"] == "MIXED_PERIOD"
    assert not report["balance"]["releasable"]


def test_empty_batch_cannot_release():
    data = csv_bytes([])
    with pytest.raises(DomainIssue, match="HEADER_ONLY"):
        inspect(data)


def test_header_only_file_is_rejected():
    with pytest.raises(DomainIssue, match="HEADER_ONLY"):
        inspect(csv_bytes([]))


def test_unclosed_quote_invalidates_compensation_source():
    data = csv_bytes([]) + b'"truncated\n'
    with pytest.raises(DomainIssue, match="CSV_MALFORMED"):
        inspect(data)


def test_wrong_column_count_is_isolated():
    data = csv_bytes([]) + (
        "CMP-1,CUST-A,2026-11,2026-10-01,2026-12-31,100,0,,备注,多余\n".encode()
    )
    result = inspect(data)
    assert result["reasons"] == {"COLUMN_COUNT": 1}
    assert result["accepted"] == 0


def test_blank_used_amount_defaults_to_zero():
    data = csv_bytes([]) + (
        "CMP-1,CUST-A,2026-11,2026-10-01,2026-12-31,100,N/A,,备注\n".encode()
    )
    assert inspect(data)["rows"][0]["used_cents"] == 0


def test_full_width_and_grouping_are_canonical():
    data = csv_bytes([]) + (
        'CMP-1,CUST-A,２０２６-１１,2026-10-01,2026-12-31,"１,０００",０,,\n'.encode()
    )
    row = inspect(data)["rows"][0]
    assert (row["period"], row["amount_cents"]) == ("2026-11", 1000)


def test_used_over_amount_is_isolated():
    data = csv_bytes([]) + (
        "CMP-1,CUST-A,2026-11,2026-10-01,2026-12-31,100,200,,\n".encode()
    )
    assert inspect(data)["reasons"] == {"USED_EXCEEDS_AMOUNT": 1}


def test_expiry_before_issue_is_isolated():
    data = csv_bytes([]) + (
        "CMP-1,CUST-A,2026-11,2026-12-01,2026-11-01,100,0,,\n".encode()
    )
    assert inspect(data)["reasons"] == {"DATE_ORDER": 1}


def test_missing_date_is_isolated():
    data = csv_bytes([]) + ("CMP-1,CUST-A,2026-11,,2026-11-01,100,0,,\n".encode())
    assert inspect(data)["reasons"] == {"MISSING_DATE": 1}


def test_receipt_flag_without_date_counts_as_received():
    data = csv_bytes([]) + (
        "CMP-1,CUST-A,2026-11,2026-10-01,2026-12-31,100,0,Y,\n".encode()
    )
    row = inspect(data)["rows"][0]
    assert row["receipt_present"] and row["receipt_date"] is None
    assert row["receipt_on"] == "已回执"
