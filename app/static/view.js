import {element, pretty} from './client.js';

const labels = {
  READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓',
  APPLIED:'已冲减', RETAINED:'留存余额', SETTLED:'本期了结', USED:'已用尽',
  ALREADY_APPLIED:'已入账', EXPIRED_BALANCE:'失效挂账',
  RECONCILE_MISMATCH:'对账不符', BALANCE_AFTER_EXPIRY:'失效仍挂账',
  OFFSET_WITHOUT_RECEIPT:'无回执冲减',
  NO_COMPENSATION:'无补偿账单', MIXED_PERIOD:'多期间混入',
};

const titles = {
  mrr: {name:'订阅收入月桥', actor:'订阅收入分析员', stages:['样例采信','变更排序','月桥拆解','余额平衡','运行对账'], chart:'净变动'},
  compensation: {name:'补偿抵扣月结', actor:'收入会计', stages:['账单采信','账单校验','抵扣计算','余额判定','抵扣对账'], chart:'客户余额桥'},
};

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

function money(cents) {
  return cents === null || cents === undefined ? '—' : (cents / 100).toFixed(2);
}

function heading(kind) {
  const meta = titles[kind] || titles.mrr;
  document.querySelector('.mast h1').textContent = meta.name;
  document.querySelector('.mast .role').textContent = meta.actor;
  const stages = [...document.querySelectorAll('[data-stage]')];
  meta.stages.forEach((label, index) => {
    if (stages[index]) stages[index].textContent = label;
  });
  document.querySelector('.chart h2').textContent = meta.chart;
  document.documentElement.dataset.kind = kind;
}

export function snapshot(report, selected, stage) {
  const kind = report.kind === 'compensation' ? 'compensation' : 'mrr';
  heading(kind);
  const stats = report.intake;
  const counts = report.counts || report.balance?.counts || {};
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent =
    report.cases?.length ?? counts.compensations ?? (report.prepare?.count ?? '—');
  const caseLabel = document.querySelector('[data-metric-label="cases"]');
  if (caseLabel) caseLabel.textContent = kind === 'compensation' ? '补偿笔数' : '业务组';

  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组 / 客户', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line, item.record ?? item.compensation, item.case ?? item.customer, item.reason].map(value=>element('td',value ?? '—')));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
  } else if (kind === 'compensation') {
    compensationRows(head, body, report, stage, selected);
  } else {
    head.append(...['业务分组', '输入行', '计算值', '参考值', '判定'].map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button',row.case,{type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
    }
  }
  table.createTHead().append(head);
  detailFor(report, kind, selected, stage);
  document.querySelector('#counts').textContent = summary(report, kind, stats);
}

function compensationRows(head, body, report, stage, selected) {
  const fields = [['补偿编号','compensation'],['客户','customer'],['到期','expires_on'],['回执','receipt_on'],['剩余','remaining_cents'],['冲减','offset_cents'],['了结','settled_cents'],['期末','closing_cents'],['处理',null]];
  head.append(...fields.map(([,key], index) => element('th', fields[index][0], {scope:'col'})));
  const items = report.treatments || [];
  if (!items.length) {
    body.insertRow().insertCell().colSpan = fields.length;
    body.rows[0].cells[0].textContent = stage === 'balance' ? '本批次没有可处理补偿' : '该阶段暂无计算结果';
    return;
  }
  for (const item of items) {
    const tr = body.insertRow();
    const button = element('button', item.compensation, {type:'button','data-case':item.compensation,'aria-pressed':String(item.compensation===selected)});
    tr.insertCell().append(button);
    tr.insertCell().textContent = item.customer;
    tr.insertCell().textContent = item.expires_on;
    tr.insertCell().textContent = item.receipt_on || '未回执';
    for (const key of ['remaining_cents','offset_cents','settled_cents','closing_cents']) {
      const cell = tr.insertCell();
      cell.textContent = money(item[key]);
    }
    tr.insertCell().append(badge(item.treatment));
  }
}

function detailFor(report, kind, selected, stage) {
  const picked = report.cases?.find(row=>row.case===selected);
  if (kind === 'compensation') {
    const item = (report.treatments || []).find(row=>row.compensation===selected);
    document.querySelector('#detail-title').textContent = item ? `补偿 ${item.compensation}` : '账单摘要';
    document.querySelector('#detail').textContent = pretty(
      item || (stage === 'intake' ? report.intake.reasons : report.prepare?.details || {})
    );
    return;
  }
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case}` : '采信摘要';
  const shown = picked ? picked.measure?.evidence ?? picked.prep?.details ?? {原因:picked.status} : report.intake.reasons;
  document.querySelector('#detail').textContent = pretty(shown);
}

function summary(report, kind, stats) {
  if (kind === 'compensation') {
    const totals = report.totals;
    if (totals) {
      return `冲减 ${money(totals.offset_cents)} · 了结 ${money(totals.settled_cents)} · 期末余额 ${money(totals.closing_cents)}`;
    }
    return `采信 ${stats.accepted} 笔 · 隔离 ${stats.rejected} 笔`;
  }
  return report.balance
    ? `行数 ${report.balance.accounted}/${report.balance.input} · ${report.balance.ready} 组通过`
    : `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行`;
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    item.append(button, badge(run.status));
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
