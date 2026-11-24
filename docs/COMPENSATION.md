# 补偿抵扣字段与业务定义

月末关账时，补偿账单回执常常晚到。为避免提前冲减少计净收入、把已到期补偿挂在余额里，工作台按“有回执才冲减、有效就留存、本月失效即了结”的关账口径处理补偿账单。

## 输入

编码 UTF-8，允许 BOM 与全角数字。单文件 256 KiB，最多 2000 条逻辑记录。首行必须精确匹配以下列顺序；列数不符的整行隔离：

```
compensation,customer,period,issued_on,expires_on,amount_cents,used_cents,receipt_on,note
```

| 列 | 含义 | 规则 |
|---|---|---|
| `compensation` | 补偿编号（记录键） | 字母数字开头，最长 36；同号只允许一笔，保留原始字符 |
| `customer` | 客户编号 | 与补偿编号同一字符规则；决定余额归集 |
| `period` | 结算期间 `YYYY-MM` | 一份账单只允许一个期间，混期整批拒签 |
| `issued_on` | 账单签发日 | `YYYY-MM-DD`、`YYYY/MM/DD` 或 `YYYYMMDD` |
| `expires_on` | 补偿失效日 | 不得早于签发日（`DATE_ORDER`） |
| `amount_cents` | 补偿金额（分） | 非负整数，接受全角与完整千分位 |
| `used_cents` | 已使用金额（分） | 空值记 0；不得超过金额（`USED_EXCEEDS_AMOUNT`） |
| `receipt_on` | 回执日期或回执标记 | 空、`-`、`N/A`、`NULL`、`未知`、`否` 记为未回执；`Y`/`是`/`TRUE` 记为已回执但无日期；其余按日期解析 |
| `note` | 说明 | 可跨行，最长 200 字 |

`used_cents` 采用账单的累计已用金额，因此可冲减金额恒为 `amount_cents - used_cents`。不维护逐次使用流水，避免跨期重复扣减。

## 关账口径

结算期间以自然月为界，`period_end` 为当月最后一天。每笔补偿只落一种结论：

| 处理 | 条件 | 收入冲减 | 客户余额 |
|---|---|---|---|
| `APPLIED` 已冲减 | 已收到回执 | 剩余金额 | 归零 |
| `RETAINED` 留存余额 | 无回执且 `expires_on > period_end` | 0 | 剩余金额 |
| `SETTLED` 本期了结 | 无回执且 `expires_on` 在本期内 | 0 | 归零 |
| `USED` 已用尽 | 剩余金额为 0 | 0 | 归零 |
| `ALREADY_APPLIED` 已入账 | 同号补偿已在其他已签发批次处理 | 0 | 不重复计入 |
| `EXPIRED_BALANCE` 失效挂账（拒签） | `expires_on` 早于期初仍挂在账上 | 0 | 剩余金额 |

回执以账单的 `receipt_on` 列为准：有日期或有“已回执”标记即视为收到。回执晚到（`receipt_on` 晚于 `expires_on`）仍按收到处理，因为补偿已实际抵扣，只是入账时点靠后；若业务认为回执无效，应修复来源后重传。

## 对账与签发

- 逐客户核对：`期初余额 - 收入冲减 - 本期了结 = 期末余额`。
- 总计等于各客户合计，`delta_cents` 必须为 0。
- 独立不变量：期末仍挂余额的补偿必须仍在有效期内（`BALANCE_AFTER_EXPIRY`）；收入冲减必须有回执（`OFFSET_WITHOUT_RECEIPT`）。
- 任一拒签条件或对账不符时 `releasable` 为假，`PATCH` 签发返回 `UNRESOLVED_ISSUES`。
- 采信行、隔离行、忽略行与输入行必须守恒，否则同样拒绝签发。

## 幂等

- 字节相同的重复执行命中同一批次，不新增记录；未签发批次会按最新台账刷新。
- 签发时冲减与了结写入补偿台账；新批次里同号补偿被标记 `ALREADY_APPLIED` 并跳过，不会二次冲减。
- 历史已签发批次只读。
- 台账唯一键冲突时返回 `COMPENSATION_ALREADY_POSTED`；签发路径会重读台账并重试，耗尽后报错由客户端刷新重试。

## 样例

- `compensation.csv`：可签发，覆盖冲减、留存、了结、用尽与回执标记。
- `compensation_blocked.csv`：含失效挂账、冲突版本、重复回放、错误列数、超额使用和非法日期，整批拒签。
