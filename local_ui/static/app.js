const $ = (id) => document.getElementById(id);
const messages = [];
let modelLoaded = false;
let lastEntryId = null;
let traceCount = 0;

function addMessage(role, content, meta = '') {
  messages.push({ role, content });
  const row = document.createElement('div');
  row.className = `msg ${role}`;
  row.innerHTML = `<div class="role">${role}</div><div class="bubble"></div>`;
  row.querySelector('.bubble').textContent = content;
  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    row.querySelector('.bubble').appendChild(m);
  }
  $('messages').appendChild(row);
  $('messages').scrollTop = $('messages').scrollHeight;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
  return data;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setBar(id, pct) {
  const el = $(id);
  if (!el) return;
  el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
}

function profileLabel(p) {
  const safe = p.local_safe ? 'LOCAL' : 'HOSTED/TEACHER';
  const size = p.size_b == null ? '' : `${p.size_b}B`;
  return `${safe} · ${p.name} · ${size} · ${p.model_id}`;
}

async function loadProfiles() {
  const data = await api('/api/profiles');
  const select = $('profile');
  select.innerHTML = '';
  const localFirst = data.profiles.slice().sort((a, b) => Number(b.local_safe) - Number(a.local_safe));
  localFirst.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = profileLabel(p);
    opt.dataset.localSafe = String(p.local_safe);
    opt.dataset.role = p.role;
    opt.dataset.sizeB = String(p.size_b || '');
    if (p.name === 'qwen3_0_6b_smoke') opt.selected = true;
    select.appendChild(opt);
  });
  updateProfileWarning();
}

function updateProfileWarning() {
  const opt = $('profile').selectedOptions[0];
  if (!opt) return;
  if (opt.dataset.localSafe !== 'true') {
    $('status').textContent = `Selected profile is not safe for local Mac loading. Pick qwen3_0_6b_smoke first.\nRole: ${opt.dataset.role}\nSize: ${opt.dataset.sizeB}B`;
  } else if (!modelLoaded) {
    $('status').textContent = 'Ready to load local profile. Click Load model before chatting.';
  }
}

async function refreshStatus() {
  const s = await api('/api/status');
  modelLoaded = Boolean(s.loaded);
  $('status').textContent = s.loaded ? `Loaded: ${s.profile}\nDevice: ${s.device || 'device_map'}\nImprovement log: ${s.improvement_log || ''}` : 'Not loaded. Click Load model before chatting.';
}

async function loadModel() {
  $('loadBtn').disabled = true;
  $('status').textContent = 'Loading model... first load can take a while.';
  try {
    const data = await api('/api/load', {
      method: 'POST',
      body: JSON.stringify({ profile: $('profile').value, device: $('device').value, use_graft: $('useGraft').checked, latent_backend: 'selective_ssm' }),
    });
    modelLoaded = true;
    $('status').textContent = `Loaded: ${data.profile}\nHidden: ${data.hidden_size}\nSize: ${data.size_b}B\nDevice: ${data.device}`;
  } catch (e) {
    modelLoaded = false;
    $('status').textContent = `Load failed: ${e.message}`;
  } finally {
    $('loadBtn').disabled = false;
  }
}

function renderTrace(data) {
  const summary = data.summary || {};
  const nfet = data.nfet || {};
  const gate = nfet.gate_mean;
  const latent = gate == null ? null : 1 - gate;
  setText('gate', gate == null ? '—' : gate.toFixed(4));
  setText('latentShare', latent == null ? '—' : latent.toFixed(4));
  setText('regime', nfet.regime_entropy == null ? '—' : nfet.regime_entropy.toFixed(4));
  setText('control', nfet.last_control_label || (nfet.last_control == null ? '—' : String(nfet.last_control)));
  setText('surfacePct', gate == null ? '—' : `${Math.round(gate * 100)}%`);
  setText('latentPct', latent == null ? '—' : `${Math.round(latent * 100)}%`);
  setBar('surfaceBar', gate == null ? 0 : gate * 100);
  setBar('latentBar', latent == null ? 0 : latent * 100);
  const trace = data.trace || [];
  traceCount += trace.length;
  setText('improveCount', String(traceCount));
  const avgDelta = trace.length ? trace.reduce((s, t) => s + (t.base_graft_delta_l2 || 0), 0) / trace.length : 0;
  setText('deltaAvg', avgDelta ? avgDelta.toFixed(4) : '—');
  setBar('deltaBar', Math.min(100, avgDelta * 100));
  const box = $('trace');
  if (!box) return;
  box.classList.remove('empty');
  box.innerHTML = '';
  trace.slice(0, 80).forEach((t) => {
    const row = document.createElement('div');
    row.className = 'traceRow';
    row.innerHTML = `<b>${t.sampled?.text || ''}</b><span>ctrl=${t.control || 'base'} gate=${t.gate_mean == null ? '—' : t.gate_mean.toFixed(2)} reg=${t.regime_entropy == null ? '—' : t.regime_entropy.toFixed(2)} Δ=${t.base_graft_delta_l2 == null ? '—' : t.base_graft_delta_l2.toFixed(3)}</span>`;
    box.appendChild(row);
  });
}

async function sendMessage(ev) {
  ev.preventDefault();
  const prompt = $('prompt').value.trim();
  if (!prompt) return;
  if (!modelLoaded) {
    addMessage('assistant', 'No model loaded. Pick qwen3_0_6b_smoke, click Load model, wait for Loaded status, then chat.');
    return;
  }
  $('prompt').value = '';
  addMessage('user', prompt);
  $('sendBtn').disabled = true;
  const placeholder = document.createElement('div');
  placeholder.className = 'msg assistant';
  placeholder.innerHTML = '<div class="role">assistant</div><div class="bubble">Thinking locally...</div>';
  $('messages').appendChild(placeholder);
  $('messages').scrollTop = $('messages').scrollHeight;
  try {
    const data = await api('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ messages, max_new_tokens: Number($('maxTokens').value), temperature: Number($('temperature').value), top_p: Number($('topP').value), use_graft: $('useGraft').checked, ablation_mode: $('ablation').value }),
    });
    placeholder.remove();
    lastEntryId = data.id;
    addMessage('assistant', data.response || '(empty response)', `${data.profile} · ${data.tokens} tokens · graft=${data.use_graft}`);
    renderTrace(data);
  } catch (e) {
    placeholder.remove();
    addMessage('assistant', `Error: ${e.message}`);
    if (String(e.message).includes('No model loaded')) modelLoaded = false;
  } finally {
    $('sendBtn').disabled = false;
  }
}

async function sendFeedback(rating) {
  if (!lastEntryId) {
    setText('feedbackStatus', 'No response to rate yet.');
    return;
  }
  const note = $('feedbackNote') ? $('feedbackNote').value : '';
  const data = await api('/api/feedback', { method: 'POST', body: JSON.stringify({ entry_id: lastEntryId, rating, note }) });
  setText('feedbackStatus', `Saved ${rating} feedback to local improvement log.`);
}

$('loadBtn').addEventListener('click', loadModel);
$('profile').addEventListener('change', updateProfileWarning);
$('composer').addEventListener('submit', sendMessage);
$('clearBtn').addEventListener('click', () => { messages.length = 0; $('messages').innerHTML = ''; });
if ($('goodBtn')) $('goodBtn').addEventListener('click', () => sendFeedback('good'));
if ($('badBtn')) $('badBtn').addEventListener('click', () => sendFeedback('bad'));

loadProfiles().then(refreshStatus).catch((e) => { $('status').textContent = `Init failed: ${e.message}`; });
