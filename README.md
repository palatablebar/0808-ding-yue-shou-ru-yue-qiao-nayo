# 订阅收入月桥

订阅收入分析员可在工作台上传来源 CSV，对照规则判断差异，签发合格批次或记录暂缓意见。

按月初月末及月内事件拆分新增、扩张、收缩和流失。

同一工作台还支持月末补偿抵扣：有回执的补偿冲减本月收入，仍在有效期的留在客户余额，本月失效的在本期了结；失效仍挂账、回执倒挂时拒绝签发，重复执行不二次冲减。

## 启动

```sh
docker compose up --build -d --wait
```

打开 <http://localhost:18302>。页面预览带异常样例。选中阶段查看计算证据，选择可签发样例并执行批次，然后提交复核意见。补偿样例在工作台的输入样例下拉框中切换。

## 核验

```sh
docker compose exec -T app pytest -q
```

[输入字段](docs/DATA-DICTIONARY.md) · [补偿抵扣](docs/COMPENSATION.md) · [阶段接口](docs/HTTP.md) · [操作步骤](docs/OPERATIONS.md) · [规则与测试](docs/DEPTH.md)
