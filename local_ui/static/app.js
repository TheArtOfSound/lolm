const $ = (id) => document.getElementById(id);
const messages = [];

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
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
  return data;
}

async function loadProfiles() {
  const data = await api('/api/profiles');
  const select = $('profile');
  select.innerHTML = '';
  data.profiles.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = `${p.name} — ${p.model_id}`;
    if (p.name === 'qwen3_0_6b_smoke') opt.selected = true;
    select.appendChild(opt);
  });
}

async function refreshStatus() {
  const s = await api('/api/status');
  $('status').textContent = s.loaded ? `Loaded: ${s.profile}\nDevice: ${s.device || 'device_map'}` : 'Not loaded';
}

async function loadModel() {
  $('loadBtn').disabled = true;
  $('status').textContent = 'Loading model... first load can take a while.';
  try {
    const data = await api('/api/load', {
      method: 'POST',
      body: JSON.stringify({
        profile: $('profile').value,
        device: $('device').value,
        use_graft: $('useGraft').checked,
        latent_backend: 'selective_ssm',
      }),
    });
    $('status').textContent = `Loaded: ${data.profile}\nHidden: ${data.hidden_size}\nDevice: ${data.device}`;
  } catch (e) {
    $('status').textContent = `Load failed: ${e.message}`;
  } finally {
    $('loadBtn').disabled = false;
  }
}

async function sendMessage(ev) {
  ev.preventDefault();
  const prompt = $('prompt').value.trim();
  if (!prompt) return;
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
      body: JSON.stringify({
        messages,
        max_new_tokens: Number($('maxTokens').value),
        temperature: Number($('temperature').value),
        top_p: Number($('topP').value),
        use_graft: $('useGraft').checked,
        ablation_mode: $('ablation').value,
      }),
    });
    placeholder.remove();
    addMessage('assistant', data.response || '(empty response)', `${data.profile} · ${data.tokens} tokens · graft=${data.use_graft}`);
    $('gate').textContent = data.nfet.gate_mean == null ? '—' : data.nfet.gate_mean.toFixed(4);
    $('regime').textContent = data.nfet.regime_entropy == null ? '—' : data.nfet.regime_entropy.toFixed(4);
    $('control').textContent = data.nfet.last_control == null ? '—' : String(data.nfet.last_control);
  } catch (e) {
    placeholder.remove();
    addMessage('assistant', `Error: ${e.message}`);
  } finally {
    $('sendBtn').disabled = false;
  }
}

$('loadBtn').addEventListener('click', loadModel);
$('composer').addEventListener('submit', sendMessage);
$('clearBtn').addEventListener('click', () => {
  messages.length = 0;
  $('messages').innerHTML = '';
});

loadProfiles().then(refreshStatus).catch((e) => {
  $('status').textContent = `Init failed: ${e.message}`;
});
