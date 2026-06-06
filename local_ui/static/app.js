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
  return row;
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
  $('status').textContent = s.loaded ? `Loaded: ${s.profile}\nDevice: ${s.device || 'device_map'}\nLOLM engine: ${s.latent_backend || 'none'}\nImprovement log: ${s.improvement_log || ''}` : 'Not loaded. Click Load model before chatting.';
}

async function loadModel() {
  $('loadBtn').disabled = true;
  $('status').textContent = 'Loading model... first load can take a while.';
  const backend = $('latentBackend') ? $('latentBackend').value : 'gru_debug';
  try {
    const data = await api('/api/load', {
      method: 'POST',
      body: JSON.stringify({ profile: $('profile').value, device: $('device').value, use_graft: $('useGraft').checked, latent_backend: backend }),
    });
    modelLoaded = true;
    $('status').textContent = `Loaded: ${data.profile}\nHidden: ${data.hidden_size}\nSize: ${data.size_b}B\nDevice: ${data.device}\nLOLM engine: ${data.latent_backend || backend}`;
  } catch (e) {
    modelLoaded = false;
    $('status').textContent = `Load failed: ${e.message}`;
  } finally {
    $('loadBtn').disabled = false;
  }
}

function addTraceRow(t) {
  const box = $('trace');
  if (!box) return;
  box.classList.remove('empty');
  if (box.textContent === 'No trace yet.') box.textContent = '';
  const row = document.createElement('div');
  row.className = 'traceRow';
  const token = t.sampled?.text || '';
  const control = t.control || 'base';
  const gate = t.gate_mean == null ? '—' : t.gate_mean.toFixed(2);
  const latent = t.latent_share == null ? '—' : t.latent_share.toFixed(2);
  const reg = t.regime_entropy == null ? '—' : t.regime_entropy.toFixed(2);
  const drift = t.hidden_drift == null ? '—' : t.hidden_drift.toFixed(3);
  const delta = t.base_graft_delta_l2 == null ? '—' : t.base_graft_delta_l2.toFixed(3);
  row.innerHTML = `<b>${token.replace(/</g, '&lt;')}</b><span>ctrl=${control} gate=${gate} latent=${latent} reg=${reg} drift=${drift} Δ=${delta}</span>`;
  box.prepend(row);
  while (box.children.length > 80) box.removeChild(box.lastChild);
}

function renderLiveToken(data) {
  const nfet = data.nfet || {};
  const trace = data.trace || {};
  if (nfet.gate_mean != null) setText('gate', nfet.gate_mean.toFixed(4));
  if (nfet.latent_share != null) setText('latentShare', nfet.latent_share.toFixed(4));
  if (nfet.regime_entropy != null) setText('regime', nfet.regime_entropy.toFixed(4));
  if (nfet.control != null) setText('control', nfet.control);
  if (nfet.gate_mean != null) {
    setText('surfacePct', `${Math.round(nfet.gate_mean * 100)}%`);
    setBar('surfaceBar', nfet.gate_mean * 100);
  }
  if (nfet.latent_share != null) {
    setText('latentPct', `${Math.round(nfet.latent_share * 100)}%`);
    setBar('latentBar', nfet.latent_share * 100);
  }
  if (nfet.base_graft_delta_l2 != null) {
    setText('deltaAvg', nfet.base_graft_delta_l2.toFixed(4));
    setBar('deltaBar', Math.min(100, nfet.base_graft_delta_l2 * 100));
  }
  traceCount += 1;
  setText('improveCount', String(traceCount));
  addTraceRow(trace);
}

function renderTrace(data) {
  const nfet = data.nfet || {};
  const gate = nfet.gate_mean;
  const latent = gate == null ? null : 1 - gate;
  setText('gate', gate == null ? '—' : gate.toFixed(4));
  setText('regime', nfet.regime_entropy == null ? '—' : nfet.regime_entropy.toFixed(4));
  setText('control', nfet.last_control_label || (nfet.last_control == null ? '—' : String(nfet.last_control)));
  setText('latentShare', latent == null ? '—' : latent.toFixed(4));
  const trace = data.trace || [];
  traceCount += trace.length;
  setText('improveCount', String(traceCount));
}

async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || '';
    for (const part of parts) {
      const lines = part.split('\n');
      const event = (lines.find((l) => l.startsWith('event:')) || 'event: message').slice(6).trim();
      const dataLine = lines.find((l) => l.startsWith('data:'));
      if (!dataLine) continue;
      const data = JSON.parse(dataLine.slice(5).trim());
      onEvent(event, data);
    }
  }
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
  const row = addMessage('assistant', '');
  const bubble = row.querySelector('.bubble');
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = 'Live LOLM/NFET stream starting...';
  bubble.appendChild(meta);
  let accumulated = '';
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, max_new_tokens: Number($('maxTokens').value), temperature: Number($('temperature').value), top_p: Number($('topP').value), use_graft: $('useGraft').checked, ablation_mode: $('ablation').value }),
    });
    if (!response.ok) throw new Error(await response.text());
    await readSSE(response, (event, data) => {
      if (event === 'start') {
        meta.textContent = `${data.profile} · live stream · graft=${data.use_graft} · engine=${data.latent_backend}`;
      } else if (event === 'token') {
        accumulated += data.token || '';
        bubble.firstChild.textContent = accumulated;
        renderLiveToken(data);
      } else if (event === 'done') {
        lastEntryId = data.id;
        bubble.firstChild.textContent = data.response || accumulated || '(empty response)';
        meta.textContent = `${data.profile} · ${data.tokens} tokens · graft=${data.use_graft} · engine=${data.latent_backend}`;
        renderTrace(data);
        messages.push({ role: 'assistant', content: data.response || accumulated });
      } else if (event === 'error') {
        throw new Error(data.error || 'Stream failed');
      }
    });
  } catch (e) {
    bubble.firstChild.textContent = `Error: ${e.message}`;
    meta.textContent = 'stream failed';
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
  await api('/api/feedback', { method: 'POST', body: JSON.stringify({ entry_id: lastEntryId, rating, note }) });
  setText('feedbackStatus', `Saved ${rating} feedback to local improvement log.`);
}

$('loadBtn').addEventListener('click', loadModel);
$('profile').addEventListener('change', updateProfileWarning);
$('composer').addEventListener('submit', sendMessage);
$('clearBtn').addEventListener('click', () => { messages.length = 0; $('messages').innerHTML = ''; });
if ($('goodBtn')) $('goodBtn').addEventListener('click', () => sendFeedback('good'));
if ($('badBtn')) $('badBtn').addEventListener('click', () => sendFeedback('bad'));

loadProfiles().then(refreshStatus).catch((e) => { $('status').textContent = `Init failed: ${e.message}`; });
