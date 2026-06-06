const $ = (id) => document.getElementById(id);
const messages = [];
let modelLoaded = false;
let lastEntryId = null;
let traceCount = 0;
let reflectionCount = 0;

function addMessage(role, content, meta = '', record = true) {
  if (record) messages.push({ role, content });
  const row = document.createElement('div');
  row.className = `msg ${role}`;
  row.innerHTML = `<div class="role">${role}</div><div class="bubble"><span class="content"></span></div>`;
  row.querySelector('.content').textContent = content;
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

function setText(id, value) { const el = $(id); if (el) el.textContent = value; }
function setHTML(id, value) { const el = $(id); if (el) el.innerHTML = value; }
function setBar(id, pct) { const el = $(id); if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`; }

function escapeHTML(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
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
    const data = await api('/api/load', { method: 'POST', body: JSON.stringify({ profile: $('profile').value, device: $('device').value, use_graft: $('useGraft').checked, latent_backend: backend }) });
    modelLoaded = true;
    $('status').textContent = `Loaded: ${data.profile}\nHidden: ${data.hidden_size}\nSize: ${data.size_b}B\nDevice: ${data.device}\nLOLM engine: ${data.latent_backend || backend}`;
  } catch (e) {
    modelLoaded = false;
    $('status').textContent = `Load failed: ${e.message}`;
  } finally {
    $('loadBtn').disabled = false;
  }
}

function controlMeaning(control) {
  return { continue: 'kept generating normally', retrieve: 'wanted more context or memory', verify: 'wanted to check the answer', branch: 'considered alternatives', finalize: 'was ready to close the response', base: 'used the base model path' }[control] || 'made an internal control move';
}

function updatePlainExplanation(nfet, trace) {
  if (!nfet || nfet.gate_mean == null) return;
  const surface = Math.round(nfet.gate_mean * 100);
  const latent = Math.round((nfet.latent_share ?? (1 - nfet.gate_mean)) * 100);
  const control = nfet.control || 'base';
  const delta = nfet.base_graft_delta_l2 == null ? 'small' : nfet.base_graft_delta_l2.toFixed(3);
  setHTML('plainExplain', `<div><b>What happened:</b> The answer was ${surface}% base-language path and ${latent}% LOLM latent correction.</div><div><b>NFET move:</b> ${control} — ${controlMeaning(control)}.</div><div><b>How much LOLM changed it:</b> base→graft movement was ${delta} on this token.</div><div><b>Simple meaning:</b> the model did not only autocomplete text; the graft nudged the hidden state and NFET chose a control posture.</div>`);
}

function updateReflection(data) {
  const summary = data.summary || {};
  const control = data.nfet?.last_control_label || summary.last_control || 'unknown';
  const gate = summary.avg_gate == null ? null : Math.round(summary.avg_gate * 100);
  const latent = summary.avg_latent_share == null ? null : Math.round(summary.avg_latent_share * 100);
  reflectionCount += 1;
  setText('reflectionCount', String(reflectionCount));
  setHTML('selfReflection', `<div><b>Memory event written.</b></div><div>This response is now stored with prompt, output, token trace, gate behavior, regime entropy, NFET control, and feedback slot.</div><div><b>Average behavior:</b> ${gate ?? '—'}% surface / ${latent ?? '—'}% latent, final control: ${control}.</div><div><b>Next improvement use:</b> bad ratings become correction examples; good ratings become preferred local behavior.</div>`);
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
  row.innerHTML = `<b>${escapeHTML(token)}</b><span>${controlMeaning(control)} · gate=${gate} latent=${latent} regime=${reg} drift=${drift} Δ=${delta}</span>`;
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
  if (nfet.gate_mean != null) { setText('surfacePct', `${Math.round(nfet.gate_mean * 100)}%`); setBar('surfaceBar', nfet.gate_mean * 100); }
  if (nfet.latent_share != null) { setText('latentPct', `${Math.round(nfet.latent_share * 100)}%`); setBar('latentBar', nfet.latent_share * 100); }
  if (nfet.base_graft_delta_l2 != null) { setText('deltaAvg', nfet.base_graft_delta_l2.toFixed(4)); setBar('deltaBar', Math.min(100, nfet.base_graft_delta_l2 * 100)); }
  traceCount += 1;
  setText('improveCount', String(traceCount));
  updatePlainExplanation(nfet, trace);
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
  updateReflection(data);
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
      onEvent(event, JSON.parse(dataLine.slice(5).trim()));
    }
  }
}

async function sendMessage(ev) {
  ev.preventDefault();
  const prompt = $('prompt').value.trim();
  if (!prompt) return;
  if (!modelLoaded) { addMessage('assistant', 'No model loaded. Pick qwen3_0_6b_smoke, click Load model, wait for Loaded status, then chat.'); return; }
  $('prompt').value = '';
  addMessage('user', prompt, '', true);
  $('sendBtn').disabled = true;
  const row = addMessage('assistant', '', '', false);
  const content = row.querySelector('.content');
  const bubble = row.querySelector('.bubble');
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = 'Live LOLM/NFET stream starting...';
  bubble.appendChild(meta);
  let accumulated = '';
  try {
    const response = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages, max_new_tokens: Number($('maxTokens').value), temperature: Number($('temperature').value), top_p: Number($('topP').value), use_graft: $('useGraft').checked, ablation_mode: $('ablation').value }) });
    if (!response.ok) throw new Error(await response.text());
    await readSSE(response, (event, data) => {
      if (event === 'start') meta.textContent = `${data.profile} · live stream · graft=${data.use_graft} · engine=${data.latent_backend}`;
      else if (event === 'token') { accumulated += data.token || ''; content.textContent = accumulated || '...'; renderLiveToken(data); }
      else if (event === 'done') { lastEntryId = data.id; const finalText = data.response || accumulated || '(empty response)'; content.textContent = finalText; meta.textContent = `${data.profile} · ${data.tokens} tokens · graft=${data.use_graft} · engine=${data.latent_backend}`; messages.push({ role: 'assistant', content: finalText }); renderTrace(data); }
      else if (event === 'error') throw new Error(data.error || 'Stream failed');
    });
  } catch (e) {
    content.textContent = `Error: ${e.message}`;
    meta.textContent = 'stream failed';
    if (String(e.message).includes('No model loaded')) modelLoaded = false;
  } finally {
    $('sendBtn').disabled = false;
  }
}

async function sendFeedback(rating) {
  if (!lastEntryId) { setText('feedbackStatus', 'No response to rate yet.'); return; }
  const note = $('feedbackNote') ? $('feedbackNote').value : '';
  await api('/api/feedback', { method: 'POST', body: JSON.stringify({ entry_id: lastEntryId, rating, note }) });
  setText('feedbackStatus', `Saved ${rating} feedback to local improvement log.`);
}

async function loadMemoryPanels() {
  try {
    const mem = await api('/api/memory/recent?limit=8');
    setHTML('memoryList', mem.items.length ? mem.items.map((m) => `<div class="listItem"><b>${escapeHTML(m.tag || 'note')} · ${escapeHTML(m.importance)}</b><span>${escapeHTML(m.text)}</span></div>`).join('') : 'No memories yet.');
    const goals = await api('/api/goals');
    setHTML('goalList', goals.items.length ? goals.items.map((g) => `<div class="listItem"><b>${escapeHTML(g.title)}</b><span>${escapeHTML(g.why || '')}</span></div>`).join('') : 'No goals yet.');
    const journal = await api('/api/journal?max_chars=1200');
    setHTML('journalBox', journal.journal ? `<pre>${escapeHTML(journal.journal)}</pre>` : 'No journal yet.');
  } catch (e) {
    setHTML('memoryList', `Memory load failed: ${escapeHTML(e.message)}`);
  }
}

async function saveMemory() {
  const text = $('memoryText')?.value.trim();
  if (!text) return;
  await api('/api/memory/note', { method: 'POST', body: JSON.stringify({ text, tag: $('memoryTag').value || 'note', importance: Number($('memoryImportance').value || 5) }) });
  $('memoryText').value = '';
  await loadMemoryPanels();
}

async function saveGoal() {
  const title = $('goalTitle')?.value.trim();
  if (!title) return;
  await api('/api/goals', { method: 'POST', body: JSON.stringify({ title, why: $('goalWhy').value || '', priority: 5 }) });
  $('goalTitle').value = '';
  $('goalWhy').value = '';
  await loadMemoryPanels();
}

async function saveJournal() {
  const markdown = $('journalText')?.value.trim();
  if (!markdown) return;
  await api('/api/journal', { method: 'POST', body: JSON.stringify({ markdown }) });
  $('journalText').value = '';
  await loadMemoryPanels();
}

$('loadBtn').addEventListener('click', loadModel);
$('profile').addEventListener('change', updateProfileWarning);
$('composer').addEventListener('submit', sendMessage);
$('clearBtn').addEventListener('click', () => { messages.length = 0; $('messages').innerHTML = ''; });
if ($('goodBtn')) $('goodBtn').addEventListener('click', () => sendFeedback('good'));
if ($('badBtn')) $('badBtn').addEventListener('click', () => sendFeedback('bad'));
if ($('saveMemoryBtn')) $('saveMemoryBtn').addEventListener('click', saveMemory);
if ($('saveGoalBtn')) $('saveGoalBtn').addEventListener('click', saveGoal);
if ($('saveJournalBtn')) $('saveJournalBtn').addEventListener('click', saveJournal);

loadProfiles().then(refreshStatus).then(loadMemoryPanels).catch((e) => { $('status').textContent = `Init failed: ${e.message}`; });
