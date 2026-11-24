"""识别补偿账单与收入样例。

两种输入共用同一套上传入口。补偿账单以固定的表头识别，收入样例保持
原有列名，因此按首行即可无歧义分流。
"""

import csv

from app.compensation.schema import HEADER


def is_compensation(data):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    first = text.split("\n", 1)[0].rstrip("\r")
    if not first:
        return False
    try:
        header = next(csv.reader([first], strict=True))
    except (csv.Error, StopIteration):
        return False
    return tuple(value.strip() for value in header) == HEADER
