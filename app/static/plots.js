import {element} from './client.js';

function zone(target, className, text) {
  const box = element('div', undefined, {class:className});
  if (text) box.append(element('span',text));
  target.append(box);
  return box;
}

function fill(layer, value, max, label) {
  const mark = zone(layer, 'mark-piece', label);
  mark.style.setProperty('--part', `${Math.max(0,Math.min(100,100*value/Math.max(1,max)))}%`);
  return mark;
}

function money(cents) {
  return (cents / 100).toFixed(2);
}

export function visualize(report, selected) {
  const target = document.querySelector('#visual');
  target.replaceChildren();
  if (report.kind === 'compensation') return compensate(target, report, selected);
  const row = report.cases?.find(item=>item.case===selected && item.measure);
  if (!row) { target.append(element('p','该分组暂无计算值')); return; }
  const {evidence:e, value, expected, unit} = row.measure;
  bridge(target, e, value, expected, unit);
}

function bridge(target,e,value,expected,unit) {
  const items=[['新增',e.new_cents],['扩张',e.expansion_cents],['收缩',e.contraction_cents],['流失',e.churn_cents]];
  const shelf=zone(target,'bridge-columns');
  const maximum=Math.max(1,...items.map(([,n])=>n));
  items.forEach(([label,n],i)=>{
    const col=zone(shelf,`bridge-tower bridge-${i}`);
    fill(col,n,maximum,`${i>1&&n?'-':''}${n}`); col.append(element('span',label));
  });
  zone(target,'bridge-total',`期末 ${value} 分`);
}

function compensate(target, report, selected) {
  const totals = report.totals;
  const item = (report.treatments || []).find(row=>row.compensation===selected);
  if (!totals) { target.append(element('p','该阶段暂无抵扣结果')); return; }
  const items = [
    ['期初余额', totals.opening_cents, true],
    ['收入冲减', totals.offset_cents, false],
    ['本期了结', totals.settled_cents, false],
    ['期末余额', totals.closing_cents, true],
  ];
  const shelf = zone(target,'bridge-columns');
  const maximum = Math.max(1, ...items.map(([,n])=>n));
  items.forEach(([label, n], i) => {
    const col = zone(shelf, `bridge-tower bridge-${i}`);
    fill(col, n, maximum, money(n));
    col.append(element('span', label));
  });
  zone(target, 'bridge-total',
    item
      ? `${item.compensation} · ${item.customer} · ${item.treatment} · 期末 ${money(item.closing_cents)} 元`
      : `期末余额 ${money(totals.closing_cents)} 元 · 冲减 ${money(totals.offset_cents)} 元`);
}
