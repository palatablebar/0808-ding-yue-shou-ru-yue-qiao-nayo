"""补偿账单去重。

同一补偿编号只允许一笔。字节完全相同的重发按重复回放处理，只保留
第一份；内容不一致的冲突版本全部隔离，避免任意一份进入抵扣。
"""

from collections import defaultdict


def _reject(line, row, reason):
    return {
        "line": line,
        "compensation": row["compensation"],
        "customer": row["customer"],
        "reason": reason,
    }


def partition(candidates):
    by_key = defaultdict(list)
    for line, row in candidates:
        by_key[row["compensation"]].append((line, row))
    accepted, rejected = [], []
    for key, items in by_key.items():
        first = items[0][1]
        if any(row != first for _, row in items):
            rejected.extend(
                _reject(line, row, "DUPLICATE_CONFLICT") for line, row in items
            )
            continue
        accepted.append(first)
        rejected.extend(
            _reject(line, row, "DUPLICATE_REPLAY") for line, row in items[1:]
        )
    return accepted, rejected
