(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  async function postJSON(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.detail || data.error || JSON.stringify(data));
    return data;
  }

  async function getJSON(path) {
    const res = await fetch(path);
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.detail || data.error || JSON.stringify(data));
    return data;
  }

  function list(items) {
    if (!items || !items.length) return '<span class="muted">None.</span>';
    return items.map((x) => `<div class="item"><b>${esc(typeof x === 'string' ? x : x.kind || x.title || 'item')}</b><span>${esc(typeof x === 'string' ? '' : x.text || x.status || JSON.stringify(x.meta || x))}</span></div>`).join('');
  }

  function verdictClass(v) {
    if (String(v).includes('visible') || String(v).includes('passed')) return 'proofPass';
    if (String(v).includes('failed') || String(v).includes('no_visible')) return 'proofBad';
    return 'proofWarn';
  }

  function render(data) {
    const proof = data.proof || {};
    const result = data.result || {};
    const base = data.base || {};
    $('resultBox').textContent = result.response || '(empty result)';
    $('planBox').innerHTML = list(data.plan || []);
    $('actionsBox').innerHTML = list(data.actions || []);
    $('memoryBox').innerHTML = list(data.memory_used || []);
    $('baseBox').textContent = base.response || '(empty base comparison)';
    $('proofBox').innerHTML = `
      <div class="item"><b class="${verdictClass(proof.verdict)}">${esc(proof.verdict || 'unknown')}</b><span>${esc(proof.plain || '')}</span></div>
      <div class="item"><b>Metrics</b><span>similarity=${esc(proof.word_similarity)} · memory hits=${esc(proof.memory_hits_available)} · latent=${proof.avg_latent_share == null ? '—' : Math.round(proof.avg_latent_share * 100) + '%'} · control=${esc(proof.last_control || '—')}</span></div>
      <div class="item"><b>Speed</b><span>base=${esc(proof.base_tok_per_sec)} tok/s · command=${esc(proof.command_tok_per_sec)} tok/s</span></div>
    `;
    $('learningBox').innerHTML = `<pre>${esc(JSON.stringify(data.saved_learning || {}, null, 2))}</pre>`;
  }

  function renderSelf(data) {
    const box = $('selfBox');
    if (!box) return;
    const result = data.inbox || data.last_result?.inbox || data.last_result?.inbox || null;
    const statusInbox = data.inbox || [];
    if (Array.isArray(statusInbox) && statusInbox.length) {
      box.innerHTML = statusInbox.slice().reverse().map((x) => `<div class="item"><b>${esc(x.directive || x.id || 'self tick')}</b><span>${esc(x.summary || '')}</span></div>`).join('');
      return;
    }
    if (result) {
      box.innerHTML = `<div class="item"><b>${esc(result.directive || result.id || 'self tick')}</b><span>${esc(result.summary || '')}</span></div>`;
      return;
    }
    box.textContent = 'No self-tick yet. Press Think Now.';
  }

  async function run() {
    const command = $('commandInput').value.trim();
    if (!command) {
      $('status').textContent = 'Type a command first.';
      return;
    }
    $('runBtn').disabled = true;
    $('status').textContent = 'Running Command Center. This does memory retrieval, LOLM generation, base comparison, proof, and saved learning...';
    $('resultBox').textContent = 'Working...';
    try {
      const data = await postJSON('/api/command/run', {
        command,
        max_new_tokens: Number($('maxTokens').value || 128),
        temperature: Number($('temperature').value || 0.35),
        top_p: Number($('topP').value || 0.9),
        use_graft: true,
        ablation_mode: 'full',
      });
      render(data);
      $('status').textContent = `Done. Verdict: ${data.proof?.verdict || 'unknown'}`;
    } catch (e) {
      $('status').textContent = `Command failed: ${e.message}\nMake sure the model is loaded. Start with: PORT=7861 PYTHONPATH=. python local_ui/server_command.py`;
      $('resultBox').textContent = 'Command failed.';
    } finally {
      $('runBtn').disabled = false;
    }
  }

  async function thinkNow() {
    $('thinkBtn').disabled = true;
    $('status').textContent = 'Self Tick running. It is reading memory/goals/journal and creating an inbox item...';
    $('selfBox').textContent = 'Thinking...';
    try {
      const directive = $('commandInput').value.trim();
      const data = await postJSON('/api/self/tick', {
        directive,
        max_new_tokens: Math.min(Number($('maxTokens').value || 96), 160),
        temperature: Number($('temperature').value || 0.35),
        top_p: Number($('topP').value || 0.9),
        use_graft: true,
      });
      renderSelf(data);
      $('status').textContent = 'Self Tick done. Inbox item saved to memory, journal, summary, and improvement log.';
    } catch (e) {
      $('status').textContent = `Self Tick failed: ${e.message}`;
      $('selfBox').textContent = 'Self Tick failed.';
    } finally {
      $('thinkBtn').disabled = false;
    }
  }

  async function refreshSelf() {
    try {
      const data = await getJSON('/api/self/status');
      renderSelf(data);
      $('status').textContent = 'Self status refreshed.';
    } catch (e) {
      $('status').textContent = `Refresh failed: ${e.message}`;
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    $('runBtn')?.addEventListener('click', run);
    $('thinkBtn')?.addEventListener('click', thinkNow);
    $('statusBtn')?.addEventListener('click', refreshSelf);
    refreshSelf().catch(() => {});
  });
})();
