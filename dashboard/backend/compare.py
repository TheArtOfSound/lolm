"""Self-contained comparison page for LOLM vs Baseline training."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/compare", response_class=HTMLResponse)
async def compare_page():
    return COMPARE_HTML


COMPARE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LOLM vs Baseline — Live Comparison</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f1117;color:#e0e0e0;font-family:'JetBrains Mono',monospace;font-size:13px}
a{color:#a78bfa;text-decoration:none}
.header{display:flex;align-items:center;justify-content:space-between;padding:12px 24px;border-bottom:1px solid #1e2130}
.header h1{font-size:18px;color:#fff}
.header .back{font-size:13px;opacity:0.6}
.header .back:hover{opacity:1}
.status-strip{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px 24px}
.status-card{background:#161824;border:1px solid #1e2130;border-radius:8px;padding:16px}
.status-card.lolm{border-left:3px solid #a78bfa}
.status-card.baseline{border-left:3px solid #34d399}
.status-card h3{font-size:14px;margin-bottom:8px}
.status-card .meta{color:#888;font-size:11px}
.status-card .step{font-size:24px;font-weight:bold;margin:4px 0}
.status-card .step.lolm-color{color:#a78bfa}
.status-card .step.baseline-color{color:#34d399}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:bold;margin-left:8px}
.badge.running{background:#1a3a2a;color:#34d399}
.badge.stopped{background:#3a1a1a;color:#f87171}
.badge.compiling{background:#2a2a1a;color:#fbbf24}
.chart-container{padding:16px 24px}
.chart-box{background:#161824;border:1px solid #1e2130;border-radius:8px;padding:16px}
.chart-box h3{margin-bottom:12px;font-size:14px}
.metrics-table{padding:0 24px 16px}
.metrics-table table{width:100%;border-collapse:collapse;background:#161824;border:1px solid #1e2130;border-radius:8px}
.metrics-table th,.metrics-table td{padding:8px 16px;text-align:left;border-bottom:1px solid #1e2130}
.metrics-table th{color:#888;font-size:11px;text-transform:uppercase}
.metrics-table .better{color:#34d399}
.metrics-table .worse{color:#f87171}
.logs-strip{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0 24px 24px}
.log-pane{background:#161824;border:1px solid #1e2130;border-radius:8px;padding:12px;max-height:200px;overflow-y:auto;font-size:11px;line-height:1.6}
.log-pane h4{margin-bottom:8px;font-size:12px;color:#888}
.log-pane pre{white-space:pre-wrap;word-break:break-all;color:#aaa}
.no-data{text-align:center;padding:40px;color:#555}
</style>
</head>
<body>

<div class="header">
  <h1>LOLM vs Baseline <span style="color:#888;font-size:13px">— Live Comparison</span></h1>
  <a href="/" class="back">← Back to Dashboard</a>
</div>

<div class="status-strip">
  <div class="status-card lolm" id="card-lolm">
    <h3>LOLM <span class="badge compiling" id="badge-lolm">LOADING</span></h3>
    <div class="step lolm-color" id="step-lolm">—</div>
    <div class="meta" id="meta-lolm">—</div>
  </div>
  <div class="status-card baseline" id="card-baseline">
    <h3>Baseline <span class="badge compiling" id="badge-baseline">LOADING</span></h3>
    <div class="step baseline-color" id="step-baseline">—</div>
    <div class="meta" id="meta-baseline">—</div>
  </div>
</div>

<div class="chart-container">
  <div class="chart-box">
    <h3>Token Loss — LOLM vs Baseline</h3>
    <canvas id="lossChart" height="80"></canvas>
  </div>
</div>

<div class="metrics-table">
  <table>
    <thead><tr><th>Metric</th><th>LOLM</th><th>Baseline</th><th>Delta</th></tr></thead>
    <tbody id="metrics-body">
      <tr><td colspan="4" class="no-data">Waiting for data...</td></tr>
    </tbody>
  </table>
</div>

<div class="logs-strip">
  <div class="log-pane" id="log-lolm"><h4>LOLM Log</h4><pre>Connecting...</pre></div>
  <div class="log-pane" id="log-baseline"><h4>Baseline Log</h4><pre>Connecting...</pre></div>
</div>

<script>
const API_KEY = localStorage.getItem('lolm_password') || '';
const headers = {'X-API-Key': API_KEY};

// Chart setup
const ctx = document.getElementById('lossChart').getContext('2d');
const chart = new Chart(ctx, {
  type: 'line',
  data: {
    datasets: [
      {label:'LOLM Token Loss', data:[], borderColor:'#a78bfa', borderWidth:1.5, pointRadius:0, tension:0.1},
      {label:'Baseline Token Loss', data:[], borderColor:'#34d399', borderWidth:1.5, pointRadius:0, tension:0.1}
    ]
  },
  options: {
    responsive: true,
    animation: false,
    scales: {
      x: {type:'linear', title:{display:true, text:'Step', color:'#888'}, grid:{color:'#1e2130'}, ticks:{color:'#888'}},
      y: {title:{display:true, text:'Token Loss', color:'#888'}, grid:{color:'#1e2130'}, ticks:{color:'#888'}}
    },
    interaction: {mode:'nearest', axis:'x', intersect:false},
    plugins: {
      tooltip: {mode:'index'},
      legend: {labels:{color:'#ccc'}}
    }
  }
});

function updateCard(label, job) {
  const badge = document.getElementById('badge-' + label);
  const step = document.getElementById('step-' + label);
  const meta = document.getElementById('meta-' + label);
  if (!job || !job.latest || !job.latest.step) {
    badge.textContent = job ? (job.status || 'UNKNOWN').toUpperCase() : 'NO DATA';
    badge.className = 'badge stopped';
    return;
  }
  const s = job.status || 'unknown';
  badge.textContent = s.toUpperCase();
  badge.className = 'badge ' + (s === 'running' ? 'running' : 'stopped');
  step.textContent = 'Step ' + job.latest.step.toLocaleString();
  const ppl = job.latest.ppl ? (job.latest.ppl > 1e6 ? '∞' : job.latest.ppl.toFixed(1)) : '—';
  meta.textContent = 'Loss: ' + (job.latest.loss_tok||0).toFixed(4) + ' | PPL: ' + ppl +
    ' | ' + (job.latest.steps_per_sec||0).toFixed(1) + ' steps/s' +
    (job.latest.gate ? ' | Gate: ' + job.latest.gate.toFixed(3) : '') +
    ' | TPU: ' + (job.tpu_name||'—');
}

function updateMetrics(lolm, baseline) {
  const tbody = document.getElementById('metrics-body');
  if (!lolm?.latest?.step && !baseline?.latest?.step) return;
  const l = lolm?.latest || {};
  const b = baseline?.latest || {};
  const rows = [
    ['Step', l.step, b.step, null],
    ['Token Loss', l.loss_tok, b.loss_tok, 'lower'],
    ['Perplexity', l.ppl > 1e6 ? '∞' : l.ppl, b.ppl > 1e6 ? '∞' : b.ppl, 'lower'],
    ['Total Loss', l.loss, b.loss, 'lower'],
    ['CPC Future', l.loss_future, b.loss_future, 'lower'],
    ['Gate Mean', l.gate, '—', null],
    ['Regimes', l.regimes, '—', null],
    ['Steps/s', l.steps_per_sec, b.steps_per_sec, 'higher'],
    ['LR', l.lr, b.lr, null],
  ];
  tbody.innerHTML = rows.map(([name, lv, bv, better]) => {
    let lStr = lv != null ? (typeof lv === 'number' ? (lv < 0.01 ? lv.toExponential(2) : lv.toFixed(4)) : lv) : '—';
    let bStr = bv != null ? (typeof bv === 'number' ? (bv < 0.01 ? bv.toExponential(2) : bv.toFixed(4)) : bv) : '—';
    let delta = '';
    if (better && typeof lv === 'number' && typeof bv === 'number') {
      const d = lv - bv;
      const cls = (better === 'lower' && d < 0) || (better === 'higher' && d > 0) ? 'better' : 'worse';
      delta = '<span class="' + cls + '">' + (d > 0 ? '+' : '') + d.toFixed(4) + '</span>';
    }
    return '<tr><td>' + name + '</td><td>' + lStr + '</td><td>' + bStr + '</td><td>' + delta + '</td></tr>';
  }).join('');
}

async function fetchLogs(label) {
  try {
    const res = await fetch('/api/training/compare-logs?label=' + label + '&lines=20', {headers});
    const data = await res.json();
    const pane = document.getElementById('log-' + label);
    if (data.lines && data.lines.length > 0) {
      pane.innerHTML = '<h4>' + label.toUpperCase() + ' Log</h4><pre>' +
        data.lines.map(l => l.replace(/</g,'&lt;')).join('\\n') + '</pre>';
      pane.scrollTop = pane.scrollHeight;
    }
  } catch(e) {}
}

async function update() {
  try {
    const res = await fetch('/api/training/compare', {headers});
    const data = await res.json();
    const lolm = data.jobs?.lolm;
    const baseline = data.jobs?.baseline;

    updateCard('lolm', lolm);
    updateCard('baseline', baseline);

    // Update chart
    if (lolm?.history) chart.data.datasets[0].data = lolm.history.map(h => ({x:h.step, y:h.loss_tok}));
    if (baseline?.history) chart.data.datasets[1].data = baseline.history.map(h => ({x:h.step, y:h.loss_tok}));
    chart.update();

    updateMetrics(lolm, baseline);

    fetchLogs('lolm');
    fetchLogs('baseline');
  } catch(e) {
    console.error('Compare update failed:', e);
  }
}

// Auth check — if no password stored, show prompt
if (!API_KEY) {
  const pw = prompt('Dashboard password:');
  if (pw) {
    localStorage.setItem('lolm_password', pw);
    location.reload();
  }
}

setInterval(update, 15000);
update();
</script>
</body>
</html>"""
