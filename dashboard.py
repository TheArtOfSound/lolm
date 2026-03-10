# Copyright 2026 Bryan Leonard & Brandyn Leonard
#
# Licensed under the LOLM Community License Agreement, Version 1.0
# (the "License"); you may not use this file except in compliance
# with the License. You may obtain a copy of the License in the
# LICENSE file at the root of this repository.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for specific terms and conditions.

"""Slim training dashboard for LOLM.

Single-file web server that serves a live dashboard showing training
metrics, loss curves, regime usage, gate statistics, and generated samples.

Usage: python3 dashboard.py [--port 8501] [--run-dir runs/base]
"""

import argparse
import json
import os
import http.server
import threading
import time
from pathlib import Path

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LOLM Training Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    background: #0a0a0f;
    color: #c8c8d0;
    min-height: 100vh;
  }
  .header {
    background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
    border-bottom: 1px solid #2a2a3e;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header h1 {
    font-size: 18px;
    font-weight: 600;
    color: #e8e8f0;
    letter-spacing: 2px;
  }
  .header h1 span { color: #7c6ff0; }
  .status {
    font-size: 12px;
    padding: 4px 12px;
    border-radius: 12px;
    background: #1a2e1a;
    color: #4ade80;
    border: 1px solid #2a4e2a;
  }
  .status.offline { background: #2e1a1a; color: #f87171; border-color: #4e2a2a; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
    padding: 20px 24px;
  }
  .card {
    background: #12121a;
    border: 1px solid #1e1e2e;
    border-radius: 8px;
    padding: 16px;
  }
  .card h3 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #6b6b80;
    margin-bottom: 12px;
  }
  .metric {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
  }
  .metric .label { font-size: 13px; color: #8888a0; }
  .metric .value { font-size: 20px; font-weight: 600; color: #e8e8f0; }
  .metric .value.accent { color: #7c6ff0; }
  .metric .value.green { color: #4ade80; }
  .metric .value.amber { color: #fbbf24; }
  .chart-container {
    background: #12121a;
    border: 1px solid #1e1e2e;
    border-radius: 8px;
    padding: 16px;
    margin: 0 24px 16px;
  }
  .chart-container h3 {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #6b6b80;
    margin-bottom: 12px;
  }
  canvas { width: 100% !important; height: 200px !important; }
  .regime-bar {
    display: flex;
    height: 24px;
    border-radius: 4px;
    overflow: hidden;
    margin-top: 8px;
  }
  .regime-bar div {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    color: #fff;
    min-width: 20px;
  }
  .log-box {
    background: #0a0a10;
    border: 1px solid #1e1e2e;
    border-radius: 4px;
    padding: 12px;
    max-height: 200px;
    overflow-y: auto;
    font-size: 11px;
    line-height: 1.6;
    color: #8888a0;
  }
  .log-box .step { color: #7c6ff0; }
  .log-box .loss { color: #4ade80; }
  .wide { grid-column: 1 / -1; }
  .footer {
    text-align: center;
    padding: 16px;
    font-size: 11px;
    color: #4a4a5e;
    border-top: 1px solid #1e1e2e;
  }
</style>
</head>
<body>
<div class="header">
  <h1><span>LOLM</span> Training Dashboard</h1>
  <div class="status" id="status">Connecting...</div>
</div>

<div class="grid">
  <div class="card">
    <h3>Training Progress</h3>
    <div class="metric">
      <span class="label">Step</span>
      <span class="value accent" id="step">-</span>
    </div>
    <div class="metric">
      <span class="label">Progress</span>
      <span class="value" id="progress">-</span>
    </div>
    <div class="metric">
      <span class="label">Speed</span>
      <span class="value" id="speed">-</span>
    </div>
    <div class="metric">
      <span class="label">Learning Rate</span>
      <span class="value" id="lr">-</span>
    </div>
  </div>

  <div class="card">
    <h3>Loss Breakdown</h3>
    <div class="metric">
      <span class="label">Total</span>
      <span class="value green" id="loss_total">-</span>
    </div>
    <div class="metric">
      <span class="label">Token (CE)</span>
      <span class="value" id="loss_tok">-</span>
    </div>
    <div class="metric">
      <span class="label">Future</span>
      <span class="value" id="loss_future">-</span>
    </div>
    <div class="metric">
      <span class="label">Regime</span>
      <span class="value" id="loss_regime">-</span>
    </div>
    <div class="metric">
      <span class="label">Memory</span>
      <span class="value" id="loss_mem">-</span>
    </div>
    <div class="metric">
      <span class="label">Manifest</span>
      <span class="value" id="loss_manifest">-</span>
    </div>
  </div>

  <div class="card">
    <h3>Model Health</h3>
    <div class="metric">
      <span class="label">Perplexity</span>
      <span class="value amber" id="ppl">-</span>
    </div>
    <div class="metric">
      <span class="label">Gate Mean</span>
      <span class="value" id="gate_mean">-</span>
    </div>
    <div class="metric">
      <span class="label">Temperature</span>
      <span class="value" id="temp">-</span>
    </div>
  </div>
</div>

<div class="chart-container">
  <h3>Loss Curves</h3>
  <canvas id="lossChart"></canvas>
</div>

<div class="grid">
  <div class="card wide">
    <h3>Recent Training Log</h3>
    <div class="log-box" id="logBox"></div>
  </div>
</div>

<div class="footer">
  LOLM &mdash; Latent Order Language Model &mdash; Copyright 2026 Bryan Leonard &amp; Brandyn Leonard
</div>

<script>
const MAX_POINTS = 500;
let lossData = { steps: [], total: [], tok: [], future: [] };

function drawChart() {
  const canvas = document.getElementById('lossChart');
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const W = rect.width, H = rect.height;
  const pad = { t: 10, r: 10, b: 25, l: 50 };
  const plotW = W - pad.l - pad.r;
  const plotH = H - pad.t - pad.b;

  ctx.clearRect(0, 0, W, H);

  if (lossData.steps.length < 2) {
    ctx.fillStyle = '#4a4a5e';
    ctx.font = '12px monospace';
    ctx.textAlign = 'center';
    ctx.fillText('Waiting for data...', W/2, H/2);
    return;
  }

  const xMin = lossData.steps[0];
  const xMax = lossData.steps[lossData.steps.length - 1];
  const allVals = [...lossData.total, ...lossData.tok];
  const yMax = Math.max(...allVals) * 1.1;
  const yMin = Math.min(...allVals) * 0.9;

  function toX(v) { return pad.l + (v - xMin) / (xMax - xMin) * plotW; }
  function toY(v) { return pad.t + (1 - (v - yMin) / (yMax - yMin)) * plotH; }

  // Grid
  ctx.strokeStyle = '#1e1e2e';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + i * plotH / 4;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    const val = yMax - i * (yMax - yMin) / 4;
    ctx.fillStyle = '#4a4a5e';
    ctx.font = '10px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(val.toFixed(1), pad.l - 5, y + 3);
  }

  // Lines
  function drawLine(data, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const x = toX(lossData.steps[i]);
      const y = toY(data[i]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  drawLine(lossData.total, '#7c6ff0');
  drawLine(lossData.tok, '#4ade80');
  drawLine(lossData.future, '#fbbf24');

  // Legend
  const legends = [['Total', '#7c6ff0'], ['Token', '#4ade80'], ['Future', '#fbbf24']];
  let lx = pad.l + 10;
  legends.forEach(([label, color]) => {
    ctx.fillStyle = color;
    ctx.fillRect(lx, pad.t + 5, 12, 3);
    ctx.fillStyle = '#8888a0';
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    ctx.fillText(label, lx + 16, pad.t + 10);
    lx += 70;
  });
}

let knownLines = 0;

async function fetchData() {
  try {
    const res = await fetch('/api/data');
    const data = await res.json();

    if (!data.entries || data.entries.length === 0) {
      document.getElementById('status').textContent = 'Waiting for data...';
      document.getElementById('status').className = 'status offline';
      return;
    }

    document.getElementById('status').textContent = 'Training';
    document.getElementById('status').className = 'status';

    const last = data.entries[data.entries.length - 1];
    document.getElementById('step').textContent = last.step.toLocaleString();
    document.getElementById('progress').textContent =
      (last.step / 100000 * 100).toFixed(1) + '%';
    document.getElementById('lr').textContent = last.lr ? last.lr.toExponential(2) : '-';
    document.getElementById('loss_total').textContent = last.loss_total.toFixed(4);
    document.getElementById('loss_tok').textContent = last.loss_tok.toFixed(4);
    document.getElementById('loss_future').textContent = last.loss_future.toFixed(4);
    document.getElementById('loss_regime').textContent =
      last.loss_regime !== undefined ? last.loss_regime.toFixed(4) : '-';
    document.getElementById('loss_mem').textContent =
      last.loss_mem !== undefined ? last.loss_mem.toFixed(4) : '-';
    document.getElementById('loss_manifest').textContent =
      last.loss_manifest !== undefined ? last.loss_manifest.toFixed(4) : '-';

    const ppl = Math.exp(Math.min(last.loss_tok, 20));
    document.getElementById('ppl').textContent = ppl.toFixed(1);
    document.getElementById('temp').textContent =
      last.temp !== undefined ? last.temp.toFixed(3) : '-';

    // Chart data
    lossData = { steps: [], total: [], tok: [], future: [] };
    const entries = data.entries;
    const skip = Math.max(1, Math.floor(entries.length / MAX_POINTS));
    for (let i = 0; i < entries.length; i += skip) {
      const e = entries[i];
      lossData.steps.push(e.step);
      lossData.total.push(e.loss_total);
      lossData.tok.push(e.loss_tok);
      lossData.future.push(e.loss_future || 0);
    }
    drawChart();

    // Log
    if (data.entries.length > knownLines) {
      const logBox = document.getElementById('logBox');
      const newEntries = data.entries.slice(Math.max(0, data.entries.length - 20));
      logBox.innerHTML = newEntries.map(e =>
        `<span class="step">step ${e.step}</span> | ` +
        `<span class="loss">loss ${e.loss_total.toFixed(4)}</span> | ` +
        `tok ${e.loss_tok.toFixed(4)} | ppl ${Math.exp(Math.min(e.loss_tok, 20)).toFixed(1)}`
      ).join('<br>');
      logBox.scrollTop = logBox.scrollHeight;
      knownLines = data.entries.length;
    }

  } catch (e) {
    document.getElementById('status').textContent = 'Offline';
    document.getElementById('status').className = 'status offline';
  }
}

// Poll every 5 seconds
fetchData();
setInterval(fetchData, 5000);
window.addEventListener('resize', drawChart);
</script>
</body>
</html>"""


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    run_dir = None

    def log_message(self, format, *args):
        pass  # Suppress request logs

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            entries = self._read_log()
            self.wfile.write(json.dumps({"entries": entries}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def _read_log(self):
        log_path = Path(self.run_dir) / "log.jsonl"
        if not log_path.exists():
            return []
        entries = []
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries


def main():
    parser = argparse.ArgumentParser(description="LOLM Training Dashboard")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--run-dir", type=str, default="runs/base")
    args = parser.parse_args()

    DashboardHandler.run_dir = args.run_dir
    server = http.server.HTTPServer(('0.0.0.0', args.port), DashboardHandler)
    print(f"LOLM Dashboard: http://localhost:{args.port}")
    print(f"Watching: {args.run_dir}/log.jsonl")
    server.serve_forever()


if __name__ == "__main__":
    main()
