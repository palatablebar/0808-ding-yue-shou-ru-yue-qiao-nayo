COLUMNS = ("minute", "mrr_cents", "sequence")
KINDS = ("opening", "change", "close")
PROJECT = {
    "name": "订阅收入月桥",
    "actor": "订阅收入分析员",
    "stages": [
        ("intake", "样例采信"),
        ("prepare", "变更排序"),
        ("calculate", "月桥拆解"),
        ("policy", "余额平衡"),
        ("balance", "运行对账"),
    ],
    "chart": "净变动",
}
COMPENSATION = {
    "name": "补偿抵扣月结",
    "actor": "收入会计",
    "stages": [
        ("intake", "账单采信"),
        ("prepare", "账单校验"),
        ("calculate", "抵扣计算"),
        ("policy", "余额判定"),
        ("balance", "抵扣对账"),
    ],
    "chart": "客户余额桥",
}
