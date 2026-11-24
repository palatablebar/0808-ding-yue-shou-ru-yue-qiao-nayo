"""补偿账单字段解析。

补偿账单按“一笔补偿一行”提供，期间使用 YYYY-MM。日期列必须落在
发出的账单有效期内。金额一律为分，接受全角数字与完整千分位。
"""

import re
import unicodedata
from datetime import date, datetime

from app.business import DomainIssue
from app.intake.numeric import quantity

HEADER = (
    "compensation",
    "customer",
    "period",
    "issued_on",
    "expires_on",
    "amount_cents",
    "used_cents",
    "receipt_on",
    "note",
)

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,35}")
PERIOD = re.compile(r"([0-9]{4})-([0-9]{2})")
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d")
ABSENT = {"", "-", "N/A", "NULL", "未知", "N", "NO", "NONE", "否"}
PRESENT = {"Y", "YES", "TRUE", "是", "1"}


def period(value):
    text = unicodedata.normalize("NFKC", value).strip()
    found = PERIOD.fullmatch(text)
    if not found or not 1 <= int(found.group(2)) <= 12:
        raise DomainIssue("INVALID_PERIOD")
    return text


def day(value):
    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        raise DomainIssue("MISSING_DATE")
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise DomainIssue("INVALID_DATE")


def receipt(value):
    """返回 (是否收到回执, 回执日期)。空值与否定写法表示未收到。"""
    text = unicodedata.normalize("NFKC", value).strip()
    if text.upper() in ABSENT:
        return False, None
    if text.upper() in PRESENT:
        return True, None
    return True, day(text)


def identifier(value, name):
    text = value.strip()
    if not IDENTIFIER.fullmatch(text):
        raise DomainIssue("BAD_" + name)
    return text


def record(values):
    if len(values) != len(HEADER):
        raise DomainIssue("COLUMN_COUNT")
    row = dict(zip(HEADER, values))
    row["compensation"] = identifier(row["compensation"], "COMPENSATION")
    row["customer"] = identifier(row["customer"], "CUSTOMER")
    row["period"] = period(row["period"])
    row["issued_on"] = day(row["issued_on"])
    row["expires_on"] = day(row["expires_on"])
    if row["issued_on"] > row["expires_on"]:
        raise DomainIssue("DATE_ORDER")
    row["amount_cents"] = quantity(row["amount_cents"])
    raw_used = unicodedata.normalize("NFKC", row["used_cents"]).strip()
    row["used_cents"] = 0 if raw_used.upper() in ABSENT else quantity(row["used_cents"])
    if row["used_cents"] > row["amount_cents"]:
        raise DomainIssue("USED_EXCEEDS_AMOUNT")
    row["receipt_present"], row["receipt_date"] = receipt(row["receipt_on"])
    row["receipt_on"] = (
        row["receipt_date"].isoformat()
        if row["receipt_date"] is not None
        else ("已回执" if row["receipt_present"] else "")
    )
    if len(row["note"]) > 200:
        raise DomainIssue("NOTE_TOO_LONG")
    return row


def month_start(value):
    year, month = (int(part) for part in value.split("-"))
    return date(year, month, 1)
