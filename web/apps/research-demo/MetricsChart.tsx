import { useEffect, useRef, useState } from 'react';
import Chart from 'chart.js/auto';

export function MetricsChart() {
  const canvas = useRef<HTMLCanvasElement>(null);
  const instance = useRef<Chart<'line', { x: number; y: number }[], number> | null>(null);
  const [shown, setShown] = useState([true, true]);
  useEffect(() => {
    const labels = Array.from({ length: 401 }, (_, index) => index / 2);
    const baseline = labels.map((x, i) => ({ x, y: 140 * Math.exp(-x / 80) + 50 + Math.sin(i * 2.1) * 2 + Math.cos(i * .7) * 2 }));
    const candidate = labels.map((x, i) => ({ x, y: 170 * Math.exp(-x / 46) + 22 + Math.sin(i * 1.7) * 1.6 }));
    const range = (data: typeof baseline, offset: number) => data.map(point => ({ x: point.x, y: Math.min(200, Math.max(0, point.y + offset)) }));
    const chart = new Chart(canvas.current!, { type: 'line', data: { labels, datasets: [
      { label: '基线合成范围下界', data: range(baseline, -10), borderWidth: 0, pointRadius: 0 },
      { label: '基线合成范围上界', data: range(baseline, 10), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: '#3389ff1a' },
      { label: 'Baseline（现有方案）', data: baseline, borderColor: '#3389ff', backgroundColor: '#3389ff12', pointRadius: 0, borderWidth: 2, tension: .15 },
      { label: '候选合成范围下界', data: range(candidate, -8), borderWidth: 0, pointRadius: 0 },
      { label: '候选合成范围上界', data: range(candidate, 8), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: '#963df01a' },
      { label: '候选方案（实验12）', data: candidate, borderColor: '#963df0', backgroundColor: '#963df012', pointRadius: 0, borderWidth: 2, tension: .15 },
    ] }, options: { responsive: true, maintainAspectRatio: false, animation: false, layout: { padding: { left: 30, right: 6 } }, plugins: { legend: { display: false }, tooltip: { filter: item => item.datasetIndex === 2 || item.datasetIndex === 5, callbacks: { title: items => `推理步数 ${items[0].label}K`, label: item => `${item.dataset.label}：${Number(item.parsed.y).toFixed(1)} ms（合成）` } } }, interaction: { mode: 'index', intersect: false }, scales: { x: { type: 'linear', min: 0, max: 200, grid: { color: '#edf1f6' }, ticks: { color: '#7c879d', stepSize: 50, callback: value => Number(value) ? `${value}K` : '0' }, title: { display: true, text: '推理步数', color: '#778297' } }, y: { min: 0, max: 200, ticks: { stepSize: 50, color: '#7c879d' }, grid: { color: '#edf1f6' } } } } });
    instance.current = chart;
    return () => { chart.destroy(); instance.current = null; };
  }, []);
  return <div className="rd-chart"><div className="rd-chart-legend">{['Baseline（现有方案）', '候选方案（实验12）'].map((label, index) => <button key={label} type="button" aria-pressed={shown[index]} onClick={() => { const next = !shown[index]; setShown(values => values.map((value, i) => i === index ? next : value)); for (const offset of [0, 1, 2]) instance.current?.setDatasetVisibility(index * 3 + offset, next); instance.current?.update(); }}><span className={index ? 'rd-dot purple' : 'rd-dot blue'}/>{label}</button>)}</div><p className="rd-axis-title">推理延迟 (ms)</p><div className="rd-chart-canvas"><canvas ref={canvas} role="img" aria-label="合成指标：现有方案延迟约190降至61毫秒，候选方案约192降至24毫秒；阴影为合成示意范围，并非测量置信区间；尚未验证科学结论。"/></div></div>;
}
