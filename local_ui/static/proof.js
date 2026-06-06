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
    if (!res.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
    return data;
  }

  function renderProof(data) {
    const box = $('proofBox');
    if (!box) return;
    const diff = data.diff || {};
    const base = data.base || {};
    const lolm = data.lolm || {};
    const latent = diff.avg_latent_share == null ? '—' : `${Math.round(diff.avg_latent_share * 100)}%`;
    const similarity = diff.word_similarity == null ? '—' : diff.word_similarity;
    const verdict = diff.verdict || (diff.changed_text ? 'changed_text' : 'no_visible_difference');
    box.innerHTML = `
      <div class="proofVerdict"><b>${esc(verdict)}</b><span>${esc(diff.plain_english || diff.plain || '')}</span></div>
      <div class="proofGrid">
        <div><b>Base</b><pre>${esc(base.response || '')}</pre></div>
        <div><b>LOLM-NFET</b><pre>${esc(lolm.response || '')}</pre></div>
      </div>
      <div class="proofStats">
        <span>Similarity: <b>${esc(similarity)}</b></span>
        <span>Latent: <b>${esc(latent)}</b></span>
        <span>Control: <b>${esc(diff.last_control || '—')}</b></span>
        <span>Base tok/s: <b>${esc(diff.base_tok_per_sec || '—')}</b></span>
        <span>LOLM tok/s: <b>${esc(diff.lolm_tok_per_sec || '—')}</b></span>
      </div>
    `;
  }

  async function runProof() {
    const box = $('proofBox');
    const btn = $('proofBtn');
    const promptEl = $('prompt');
    const prompt = promptEl?.value.trim() || 'Explain why LOLM-NFET should feel different from a normal local chatbot.';
    if (btn) btn.disabled = true;
    if (box) box.textContent = 'Running base vs LOLM proof comparison. This runs two generations, so it can take a bit on CPU...';
    try {
      const body = {
        messages: [{ role: 'user', content: prompt }],
        max_new_tokens: Math.min(Number($('maxTokens')?.value || 24), 48),
        temperature: Number($('temperature')?.value || 0.7),
        top_p: Number($('topP')?.value || 0.9),
        use_graft: true,
        ablation_mode: $('ablation')?.value || 'full',
      };
      const data = await postJSON('/api/proof/compare', body);
      renderProof(data);
    } catch (e) {
      if (box) box.innerHTML = `<b>Proof Mode failed.</b><br><span>${esc(e.message)}</span><br><br><span>Start with: <code>PORT=7861 PYTHONPATH=. python local_ui/server_proof.py</code></span>`;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  window.addEventListener('DOMContentLoaded', () => {
    const btn = $('proofBtn');
    if (btn) btn.addEventListener('click', runProof);
  });
})();
