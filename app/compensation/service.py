"""补偿抵扣：采信、去重与源行守恒。

采信口径与收入样例一致：空白行和重复表头计入忽略行，字段异常进入隔离，
同一补偿编号的冲突版本整体隔离。输出同时保留输入、采信、隔离和忽略四类
计数，供后续抵扣与对账复核。
"""

from collections import Counter

from app.business import DomainIssue
from app.compensation.reader import table
from app.compensation.resolve import partition
from app.compensation.schema import HEADER, record


def inspect(data):
    header, lines = table(data)
    normalized = tuple(value.strip() for value in header)
    if normalized != HEADER:
        raise DomainIssue("HEADER_MISMATCH")

    counted = repeated = blanks = 0
    candidates, rejected = [], []
    for line, values in lines:
        counted += 1
        if not any(value.strip() for value in values):
            blanks += 1
            continue
        if tuple(value.strip() for value in values) == HEADER:
            repeated += 1
            continue
        try:
            candidates.append((line, record(values)))
        except DomainIssue as error:
            key = values[0].strip()[:36] if values else ""
            customer = values[1].strip()[:36] if len(values) > 1 else ""
            rejected.append(
                dict(line=line, compensation=key, customer=customer, reason=error.code)
            )
    accepted, conflicts = partition(candidates)
    rejects = sorted(rejected + conflicts, key=lambda row: row["line"])
    return dict(
        input=counted,
        accepted=len(accepted),
        repeated=repeated,
        blank=blanks,
        rejected=len(rejects),
        reasons=dict(Counter(row["reason"] for row in rejects)),
        isolation=rejects,
        rows=accepted,
    )


def identifiers(data):
    """尽力读取采信后的补偿编号；结构性错误原样抛出，由调用方决定。"""
    return [row["compensation"] for row in inspect(data)["rows"]]
