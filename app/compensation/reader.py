"""补偿账单的原始读取。

与收入样例共用同一组输入边界：UTF-8（可带 BOM）、单文件 256 KiB、
最多 2000 条逻辑记录、引号内换行按一条逻辑记录处理、引号未闭合时整份拒收。
返回表头和带源行号的记录，表头解释交给 schema。
"""

import csv
import io

from app.business import DomainIssue
from app.config import MAX_FILE, MAX_ROWS


def table(data):
    if len(data) > MAX_FILE:
        raise DomainIssue("FILE_TOO_LARGE")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DomainIssue("ENCODING_INVALID") from error
    if not text:
        raise DomainIssue("FILE_EMPTY")
    if not text.strip():
        raise DomainIssue("FILE_BLANK")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as error:
        raise DomainIssue("HEADER_ONLY") from error
    except csv.Error as error:
        raise DomainIssue("CSV_MALFORMED") from error
    if not any(value.strip() for value in header):
        raise DomainIssue("HEADER_MISMATCH")

    rows = []
    try:
        for number, row in enumerate(reader, 1):
            if number > MAX_ROWS:
                raise DomainIssue("ROW_LIMIT")
            rows.append((reader.line_num, row))
    except csv.Error as error:
        raise DomainIssue("CSV_MALFORMED") from error
    if not rows:
        raise DomainIssue("HEADER_ONLY")
    return header, rows
