/* ── Tab navigation ──────────────────────────────────────────────────────── */

function showTab(tab) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + tab).classList.remove('hidden');
  document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
  if (tab === 'settings') loadSettings();
}


/* ── Connection indicator ────────────────────────────────────────────────── */

function updateDeviceIndicator(status, checkedAt) {
  const dot   = document.getElementById('conn-dot');
  const label = document.getElementById('conn-label');
  const time  = document.getElementById('conn-time');

  dot.className = 'conn-dot conn-' + status;

  const labels = { online: 'Online', offline: 'Offline', unknown: 'Unknown' };
  label.textContent = 'Ulanzi: ' + (labels[status] || status);
  time.textContent  = checkedAt ? `(${checkedAt})` : '';
}


/* ── Dashboard ───────────────────────────────────────────────────────────── */

let prevModulesJSON = null;
let prevOrderJSON = null;
let prevCountdownsJSON = null;
let prevTimerActiveJSON = null;
let prevTimerPresetsJSON = null;
let prevTwitchChJSON = null;
let prevPinnedJSON = null;
let statusFailCount = 0;
let isDragging = false;

async function refreshStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) { statusFailCount++; return; }
    statusFailCount = 0;
    const data = await res.json();

    const stateEl = document.getElementById('scheduler-state');
    stateEl.textContent = data.scheduler_state;
    stateEl.className   = 'badge badge-' + data.scheduler_state.toLowerCase();

    document.getElementById('last-poll').textContent =
      data.last_poll_at || '—';
    document.getElementById('next-poll').textContent =
      data.next_poll_in ? data.next_poll_in + 's' : '—';

    updateDeviceIndicator(data.device_status, data.device_last_checked);

    // Active apps table — sorted by module_order
    const tbody = document.getElementById('apps-list');
    const apps  = data.active_apps || {};
    const order = data.module_order || [];

    if (Object.keys(apps).length === 0) {
      tbody.innerHTML = '<tr><td colspan="4" class="muted">No active apps</td></tr>';
    } else {
      const sorted = Object.entries(apps).sort((a, b) => {
        const ia = order.indexOf(a[0]);
        const ib = order.indexOf(b[0]);
        return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
      });
      tbody.innerHTML = sorted.map(([name, app]) => {
        const hasMore = app.full_text && app.full_text !== app.text;
        const fullAttr = hasMore ? ` data-full="${escHtml(app.full_text).replace(/"/g, '&quot;')}"` : '';
        return `<tr>
          <td class="app-name">${name}</td>
          <td class="app-text${hasMore ? ' app-text-expandable' : ''}" style="color:${app.color || 'inherit'}"${fullAttr}>${escHtml(app.text)}</td>
          <td class="mono muted">${app.last_updated}</td>
          <td class="app-actions">
            <button class="btn-icon" onclick="refreshModule('${name}')" title="Force refresh">↻</button>
          </td>
        </tr>`;
      }).join('');
    }

    // Module toggles — rebuild only when data changes (and not mid-drag)
    const modulesJSON = JSON.stringify(data.modules || {});
    const orderJSON   = JSON.stringify(order);
    if (!isDragging && (modulesJSON !== prevModulesJSON || orderJSON !== prevOrderJSON)) {
      prevModulesJSON = modulesJSON;
      prevOrderJSON   = orderJSON;
      renderModules(data.modules, order, data.app_colors || {}, data.app_default_colors || {});
    } else if (!isDragging) {
      Object.entries(data.modules || {}).forEach(([name, enabled]) => {
        const el = document.querySelector(`.module-item[data-module="${name}"] input[type=checkbox]`);
        if (el) el.checked = enabled;
      });
    }

    // Countdown panel
    const countdownsJSON = JSON.stringify(data.countdowns || []);
    if (countdownsJSON !== prevCountdownsJSON) {
      prevCountdownsJSON = countdownsJSON;
      renderDashboardCountdowns(data.countdowns || []);
    }

    // Timer panel
    const timerActiveJSON = JSON.stringify(data.timer_active || []);
    const timerPresetsJSON = JSON.stringify(data.timer_presets || []);
    if (timerActiveJSON !== prevTimerActiveJSON || timerPresetsJSON !== prevTimerPresetsJSON) {
      prevTimerActiveJSON = timerActiveJSON;
      prevTimerPresetsJSON = timerPresetsJSON;
      renderDashboardTimer(data.timer_active || [], data.timer_presets || []);
    }

    // Twitch channels panel
    const twitchChJSON = JSON.stringify(data.twitch_channels || []);
    if (twitchChJSON !== prevTwitchChJSON) {
      prevTwitchChJSON = twitchChJSON;
      renderDashboardTwitchChannels(data.twitch_channels || []);
    }

    // Pinned message panel
    const pinnedJSON = JSON.stringify(data.pinned || {});
    if (pinnedJSON !== prevPinnedJSON) {
      prevPinnedJSON = pinnedJSON;
      renderPinnedStatus(data.pinned || {});
    }

  } catch (e) {
    statusFailCount++;
    if (statusFailCount >= 3) updateDeviceIndicator('unknown', '');
    console.error('Status fetch failed:', e);
  }
}


/* ── Module rendering & drag-to-reorder ──────────────────────────────────── */

let draggedEl = null;

function renderModules(modules, order, appColors, defaultColors) {
  const container = document.getElementById('modules-list');
  const sorted = (order || []).filter(name => name in modules);
  Object.keys(modules).forEach(name => {
    if (!sorted.includes(name)) sorted.push(name);
  });

  container.innerHTML = sorted.map(name => {
    const enabled = modules[name];
    const color = appColors[name] || defaultColors[name] || '#FFFFFF';
    return `<div class="module-item module-toggle ${enabled ? 'is-on' : 'is-off'}"
                draggable="true" data-module="${name}">
      <span class="drag-handle">⠿</span>
      <input type="checkbox" ${enabled ? 'checked' : ''}
             onchange="toggleModule('${name}', this)">
      <span class="toggle-name">${name}</span>
      <span class="toggle-status">${enabled ? 'ON' : 'OFF'}</span>
      <input type="color" class="module-color" data-module="${name}" value="${color}"
             title="Color for ${name}" onclick="event.stopPropagation()"
             onchange="saveAppColor('${name}', this.value)">
    </div>`;
  }).join('');

  container.querySelectorAll('.module-item').forEach(el => {
    el.addEventListener('dragstart', onDragStart);
    el.addEventListener('dragend', onDragEnd);
    el.addEventListener('dragover', onDragOver);
    el.addEventListener('drop', onDrop);
  });
}

async function saveAppColor(moduleName, color) {
  try {
    const res = await fetch('/api/config', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_colors: { [moduleName]: color } }),
    });
    if (res.ok) {
      prevModulesJSON = null;
      refreshStatus();
      await fetch(`/api/modules/${moduleName}/refresh`, { method: 'POST' });
    }
  } catch (e) {
    console.error('Failed to save app color:', e);
  }
}

function onDragStart(e) {
  isDragging = true;
  draggedEl = e.currentTarget;
  e.currentTarget.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onDragEnd(e) {
  e.currentTarget.classList.remove('dragging');
  draggedEl = null;
  isDragging = false;
}

function onDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const target = e.currentTarget;
  if (!draggedEl || target === draggedEl) return;

  const container = target.parentNode;
  const children = [...container.children];
  const dragIdx   = children.indexOf(draggedEl);
  const targetIdx = children.indexOf(target);

  if (dragIdx < targetIdx) {
    container.insertBefore(draggedEl, target.nextSibling);
  } else {
    container.insertBefore(draggedEl, target);
  }
}

function onDrop(e) {
  e.preventDefault();
  saveModuleOrder();
}

async function saveModuleOrder() {
  const container = document.getElementById('modules-list');
  const order = [...container.children].map(el => el.dataset.module).filter(Boolean);
  prevOrderJSON = JSON.stringify(order);
  try {
    await fetch('/api/modules/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(order),
    });
  } catch (e) {
    console.error('Failed to save module order:', e);
  }
}


/* ── Module actions ──────────────────────────────────────────────────────── */

async function toggleModule(name, checkbox) {
  try {
    const res = await fetch(`/api/modules/${name}/toggle`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json();
      console.error('Toggle failed:', data.detail);
      checkbox.checked = !checkbox.checked;
    }
    prevModulesJSON = null;
    refreshStatus();
  } catch (e) {
    console.error('Toggle failed:', e);
    checkbox.checked = !checkbox.checked;
  }
}

async function refreshModule(name) {
  try {
    const res = await fetch(`/api/modules/${name}/refresh`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json();
      console.error('Refresh failed:', data.detail);
    }
    refreshStatus();
  } catch (e) {
    console.error('Refresh failed:', e);
  }
}


/* ── Dashboard: Countdown Timers ─────────────────────────────────────────── */

function renderDashboardCountdowns(events) {
  const el = document.getElementById('dashboard-countdowns');
  if (!events || events.length === 0) {
    el.innerHTML = '<span class="muted">No countdowns configured.</span>';
    return;
  }
  const now = new Date();
  el.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;">' +
    events.map((ev, i) => {
      const target = new Date(ev.date + 'T00:00:00');
      const diffMs = target - now;
      const days = Math.ceil(diffMs / 86400000);
      let eta;
      if (days <= 0) eta = 'NOW!';
      else if (days === 1) eta = '1d';
      else eta = days + 'd';
      return `<span class="module-toggle is-on">
        <span class="toggle-name">${escHtml(ev.name)}</span>
        <span class="muted">${ev.date}</span>
        <span class="countdown-eta">${eta}</span>
        <button type="button" class="tag-remove-btn" onclick="removeCountdown(${i})"
                style="padding:0 0.35rem;font-size:0.7rem;margin-left:0.2rem;">x</button>
      </span>`;
    }).join('') + '</div>';
}

async function addCountdown() {
  const nameEl = document.getElementById('countdown-name-input');
  const dateEl = document.getElementById('countdown-date-input');
  const name = nameEl.value.trim();
  const date = dateEl.value;
  if (!name || !date) return;

  try {
    await fetch('/api/countdowns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, date }),
    });
    nameEl.value = '';
    dateEl.value = '';
    prevCountdownsJSON = null;
    refreshStatus();
  } catch (e) {
    console.error('Failed to add countdown:', e);
  }
}

async function removeCountdown(idx) {
  try {
    await fetch(`/api/countdowns/${idx}`, { method: 'DELETE' });
    prevCountdownsJSON = null;
    refreshStatus();
  } catch (e) {
    console.error('Failed to remove countdown:', e);
  }
}


/* ── Dashboard: Timer ───────────────────────────────────────────────────── */

function renderDashboardTimer(active, presets) {
  const el = document.getElementById('dashboard-timer');
  const presetEl = document.getElementById('timer-preset');
  if (!el || !presetEl) return;

  // Populate preset dropdown
  presetEl.innerHTML = '<option value="">Custom…</option>' +
    (presets || []).map((p, i) =>
      `<option value="${i}">${escHtml(p.name)} (${Math.round(p.seconds / 60)}m)</option>`
    ).join('');

  if (!active || active.length === 0) {
    el.innerHTML = '<span class="muted">No active timers.</span>';
    return;
  }
  el.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;">' +
    active.map(t => {
      const m = Math.floor(t.remaining_seconds / 60);
      const s = t.remaining_seconds % 60;
      const display = `${m}:${String(s).padStart(2, '0')}`;
      return `<span class="module-toggle is-on">
        <span class="toggle-name">${escHtml(t.name)}</span>
        <span class="countdown-eta">${display}</span>
        <button type="button" class="tag-remove-btn" onclick="stopTimer('${escHtml(t.id).replace(/'/g, "\\'")}')"
                style="padding:0 0.35rem;font-size:0.7rem;margin-left:0.2rem;">Stop</button>
      </span>`;
    }).join('') + '</div>';
}

async function startTimer() {
  const presetEl = document.getElementById('timer-preset');
  const secondsEl = document.getElementById('timer-seconds');
  const nameEl = document.getElementById('timer-name');
  const chimeEl = document.getElementById('timer-chime');

  const presetId = presetEl?.value;
  const seconds = parseInt(secondsEl?.value);
  const name = (nameEl?.value || '').trim() || undefined;
  const chimeEnabled = chimeEl?.checked ?? true;

  let body = { chime_enabled: chimeEnabled };
  if (presetId !== '' && presetId !== undefined) {
    body.preset_id = parseInt(presetId);
    if (name) body.name = name;
  } else if (seconds && seconds >= 1) {
    body.seconds = seconds;
    body.name = name || 'Timer';
  } else {
    return;
  }

  try {
    const res = await fetch('/api/timer/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      secondsEl.value = '';
      nameEl.value = '';
      prevTimerActiveJSON = null;
      refreshStatus();
    } else {
      const data = await res.json();
      console.error('Timer start failed:', data.detail);
    }
  } catch (e) {
    console.error('Failed to start timer:', e);
  }
}

async function stopTimer(timerId) {
  try {
    const res = await fetch('/api/timer/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timer_id: timerId }),
    });
    if (res.ok) {
      prevTimerActiveJSON = null;
      refreshStatus();
    }
  } catch (e) {
    console.error('Failed to stop timer:', e);
  }
}


/* ── Dashboard: Twitch Channels ──────────────────────────────────────────── */

let _currentTwitchChannels = [];

function renderDashboardTwitchChannels(channels) {
  _currentTwitchChannels = channels || [];
  const el = document.getElementById('dashboard-twitch-channels');
  if (_currentTwitchChannels.length === 0) {
    el.innerHTML = '<span class="muted">No channels configured.</span>';
    return;
  }
  el.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;">' +
    _currentTwitchChannels.map((ch, i) =>
      `<span class="module-toggle is-on">
        <span class="toggle-name">${escHtml(ch)}</span>
        <button type="button" class="tag-remove-btn" onclick="removeTwitchChannel(${i})"
                style="padding:0 0.35rem;font-size:0.7rem;margin-left:0.2rem;">x</button>
      </span>`
    ).join('') + '</div>';
}

async function addTwitchChannel() {
  const input = document.getElementById('twitch-channel-input');
  const name = input.value.trim().toLowerCase();
  if (!name) return;
  if (_currentTwitchChannels.includes(name)) { input.value = ''; return; }

  const updated = [..._currentTwitchChannels, name];
  try {
    await fetch('/api/twitch/channels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated),
    });
    input.value = '';
    prevTwitchChJSON = null;
    refreshStatus();
  } catch (e) {
    console.error('Failed to add twitch channel:', e);
  }
}

async function removeTwitchChannel(idx) {
  const updated = _currentTwitchChannels.filter((_, i) => i !== idx);
  try {
    await fetch('/api/twitch/channels', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updated),
    });
    prevTwitchChJSON = null;
    refreshStatus();
  } catch (e) {
    console.error('Failed to remove twitch channel:', e);
  }
}


/* ── Dashboard: Pinned Message ────────────────────────────────────────────── */

function renderPinnedStatus(cfg) {
  const el = document.getElementById('pinned-current');
  const text = (cfg.text || '').trim();
  const color = cfg.color || '#FFFFFF';
  if (!text) {
    el.innerHTML = '<span class="muted">No pinned message.</span>';
  } else {
    el.innerHTML = `<div class="pinned-preview">
      <span class="pinned-dot" style="background:${color}"></span>
      <span style="color:${color}">${escHtml(text)}</span>
    </div>`;
  }
  // Sync inputs to current state
  const textInput = document.getElementById('pinned-text');
  const colorInput = document.getElementById('pinned-color');
  if (textInput && !textInput.matches(':focus')) textInput.value = text;
  if (colorInput && !colorInput.matches(':focus')) colorInput.value = color;
}

async function savePinned() {
  const text = document.getElementById('pinned-text').value.trim();
  const color = document.getElementById('pinned-color').value;
  const resultEl = document.getElementById('pinned-result');

  if (!text) { setResult(resultEl, 'Enter text first', 'err'); return; }
  setResult(resultEl, 'Saving…', '');

  try {
    const res = await fetch('/api/pinned', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, color }),
    });
    if (res.ok) {
      setResult(resultEl, 'Pinned', 'ok');
      prevPinnedJSON = null;
      refreshStatus();
    } else {
      const data = await res.json();
      setResult(resultEl, 'Error: ' + (data.detail || res.status), 'err');
    }
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
}

async function clearPinned() {
  const resultEl = document.getElementById('pinned-result');
  try {
    await fetch('/api/pinned', { method: 'DELETE' });
    document.getElementById('pinned-text').value = '';
    setResult(resultEl, 'Cleared', 'ok');
    prevPinnedJSON = null;
    refreshStatus();
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
}


/* ── Quick notify ────────────────────────────────────────────────────────── */

document.getElementById('notify-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = document.getElementById('custom-text').value.trim();
  if (!text) return;

  const resultEl = document.getElementById('send-result');
  setResult(resultEl, 'Sending…', '');

  const duration = parseInt(document.getElementById('notify-duration').value) || 5;

  try {
    const res  = await fetch('/api/notify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, duration }),
    });
    const data = await res.json();
    if (res.ok) {
      setResult(resultEl, 'Sent', 'ok');
      document.getElementById('custom-text').value = '';
    } else {
      setResult(resultEl, 'Error: ' + (data.detail || res.status), 'err');
    }
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
});


/* ── Settings ────────────────────────────────────────────────────────────── */

let _teamTags       = {};
let _favouriteTeams = [];

function renderFavouriteTeams() {
  const el = document.getElementById('fav-teams-list');
  if (!el) return;
  if (_favouriteTeams.length === 0) {
    el.innerHTML = '<span class="muted">All matches (no team filter)</span>';
    return;
  }
  el.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;">' +
    _favouriteTeams.map((tag, i) =>
      `<span class="module-toggle is-on">
        <span class="toggle-name">${escHtml(tag)}</span>
        <button type="button" class="tag-remove-btn" onclick="removeFavouriteTeam(${i})"
                style="padding:0 0.35rem;font-size:0.7rem;margin-left:0.2rem;">x</button>
      </span>`
    ).join('') + '</div>';
}

function addFavouriteTeam() {
  const input = document.getElementById('fav-team-input');
  const tag   = input.value.trim().toUpperCase();
  if (!tag || _favouriteTeams.includes(tag)) { input.value = ''; return; }
  _favouriteTeams.push(tag);
  renderFavouriteTeams();
  input.value = '';
}

function removeFavouriteTeam(idx) {
  _favouriteTeams.splice(idx, 1);
  renderFavouriteTeams();
}

function onPriorityToggle() {
  const enabled = document.getElementById('cfg-val-priority').checked;
  const section = document.getElementById('fav-teams-section');
  if (section) section.style.opacity = enabled ? '1' : '0.4';
}

function renderTeamTags() {
  const el = document.getElementById('team-tags-list');
  const entries = Object.entries(_teamTags);
  if (entries.length === 0) {
    el.innerHTML = '<span class="muted">No custom tags — using built-in abbreviations.</span>';
    return;
  }
  el.innerHTML = '<div style="display:flex;flex-wrap:wrap;gap:0.4rem;">' +
    entries.map(([name, tag]) =>
      `<span class="module-toggle is-on">
        <span class="toggle-name">${escHtml(name)}</span>
        <span class="toggle-status">${escHtml(tag)}</span>
        <button type="button" data-name="${escHtml(name).replace(/"/g, '&quot;')}" class="tag-remove-btn" style="padding:0 0.35rem;font-size:0.7rem;margin-left:0.2rem;">x</button>
      </span>`
    ).join('') + '</div>';
  el.querySelectorAll('.tag-remove-btn').forEach(btn => {
    btn.addEventListener('click', () => { delete _teamTags[btn.dataset.name]; renderTeamTags(); });
  });
}

function addTeamTag() {
  const name = document.getElementById('tag-name-input').value.trim();
  const tag  = document.getElementById('tag-abbr-input').value.trim().toUpperCase();
  if (!name || !tag) return;
  _teamTags[name] = tag;
  renderTeamTags();
  document.getElementById('tag-name-input').value = '';
  document.getElementById('tag-abbr-input').value = '';
}

async function loadSettings() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    const cfg = await res.json();

    set('cfg-awtrix-ip',          cfg.awtrix_ip ?? '');

    const builtin = cfg.built_in_apps ?? {};
    ['TIM','DAT','TEMP','HUM','BAT'].forEach(k => {
      const el = document.getElementById('cfg-builtin-' + k);
      if (el) el.checked = builtin[k] !== false;
    });

    const w = cfg.weather ?? {};
    set('cfg-weather-location',   w.location_name ?? '');
    set('cfg-weather-lat',        w.latitude ?? 1.3404);
    set('cfg-weather-lon',        w.longitude ?? 103.7054);
    set('cfg-weather-poll',       w.poll_interval_seconds ?? 1800);

    const r = cfg.reddit ?? {};
    set('cfg-reddit-subs',        (r.subreddits ?? ['ValorantCompetitive']).join(', '));
    set('cfg-reddit-score',       r.min_score ?? 300);
    set('cfg-reddit-age',         r.max_age_hours ?? 24);
    set('cfg-reddit-poll',        r.poll_interval_seconds ?? 1200);
    set('cfg-reddit-posts',       r.max_posts ?? 3);

    _teamTags = cfg.team_tags ?? {};
    renderTeamTags();

    const v = cfg.valorant ?? {};
    set('cfg-val-idle',           v.poll_interval_idle_seconds ?? 300);
    set('cfg-val-prematch',       v.poll_interval_pre_match_seconds ?? 60);
    set('cfg-val-live',           v.poll_interval_live_seconds ?? 20);
    set('cfg-val-cooldown',       v.cooldown_seconds ?? 180);
    set('cfg-val-window',         v.pre_match_window_minutes ?? 15);

    const priorityEl = document.getElementById('cfg-val-priority');
    if (priorityEl) priorityEl.checked = v.live_priority ?? true;
    _favouriteTeams = [...(v.favourite_teams ?? [])];
    renderFavouriteTeams();
    onPriorityToggle();

    // Populate favourite-team tag autocomplete
    try {
      const tagsRes = await fetch('/api/team-tags');
      if (tagsRes.ok) {
        const { tags } = await tagsRes.json();
        const dl = document.getElementById('fav-team-tags-list');
        if (dl && Array.isArray(tags)) {
          dl.innerHTML = tags.map(t => `<option value="${escHtml(t)}">`).join('');
        }
      }
    } catch (_) { /* ignore */ }

    const tw = cfg.twitch ?? {};
    set('cfg-twitch-id',          tw.client_id ?? '');
    set('cfg-twitch-secret',      tw.client_secret ?? '');

    const d = cfg.display ?? {};
    set('cfg-display-speed',      d.scroll_speed ?? 55);
    set('cfg-display-offset',     d.sensor_temp_offset ?? 0);
    set('cfg-display-base-speed', d.base_scroll_speed_px_per_sec ?? 40);
    set('cfg-display-matrix-width', d.matrix_width ?? 32);
    set('cfg-display-avg-char',  d.avg_char_width ?? 5);
    set('cfg-display-dur-floor', d.app_duration_floor ?? 10);
    set('cfg-display-dur-cap',   d.app_duration_cap ?? 120);
    set('cfg-display-lux',        d.lux_threshold ?? 50);
    const dimBri = d.dim_brightness ?? 20;
    const normBri = d.normal_brightness ?? 180;
    const dimEl = document.getElementById('cfg-display-dimbri');
    const normEl = document.getElementById('cfg-display-normalbri');
    const fixedEl = document.getElementById('cfg-display-fixedbri');
    if (dimEl) { dimEl.value = dimBri; dimEl.nextElementSibling.textContent = dimBri; }
    if (normEl) { normEl.value = normBri; normEl.nextElementSibling.textContent = normBri; }
    if (fixedEl) { fixedEl.value = normBri; fixedEl.nextElementSibling.textContent = normBri; }
    const autoDimEl = document.getElementById('cfg-display-autodim');
    if (autoDimEl) autoDimEl.checked = d.auto_dim_enabled ?? false;
    onAutoDimToggle();

    refreshErrorLog();
  } catch (e) {
    console.error('loadSettings failed:', e);
  }
}

async function refreshErrorLog() {
  const el = document.getElementById('error-log');
  if (!el) return;
  try {
    const res = await fetch('/api/errors');
    if (!res.ok) { el.textContent = 'Failed to load errors'; return; }
    const { entries } = await res.json();
    if (!entries || entries.length === 0) {
      el.textContent = 'No errors or warnings yet.';
      return;
    }
    el.textContent = entries.map(e =>
      `[${e.ts}] ${e.level}: ${e.msg}`
    ).join('\n');
    el.scrollTop = el.scrollHeight;
  } catch (e) {
    el.textContent = 'Error loading log: ' + (e.message || e);
  }
}

function onAutoDimToggle() {
  const enabled = document.getElementById('cfg-display-autodim')?.checked;
  const autodimSection = document.getElementById('autodim-settings');
  const fixedSection = document.getElementById('fixed-brightness-settings');
  if (autodimSection) autodimSection.style.display = enabled ? '' : 'none';
  if (fixedSection) fixedSection.classList.toggle('hidden', enabled);
  if (!enabled && fixedSection) {
    const normalVal = document.getElementById('cfg-display-normalbri')?.value;
    if (normalVal != null) {
      const fixed = document.getElementById('cfg-display-fixedbri');
      const fixedVal = document.getElementById('cfg-display-fixedbri-val');
      if (fixed) { fixed.value = normalVal; fixedVal.textContent = normalVal; }
    }
  } else if (enabled && autodimSection) {
    const fixedVal = document.getElementById('cfg-display-fixedbri')?.value;
    if (fixedVal != null) {
      const normal = document.getElementById('cfg-display-normalbri');
      const normalVal = document.getElementById('cfg-display-normalbri-val');
      if (normal) { normal.value = fixedVal; normalVal.textContent = fixedVal; }
    }
  }
}

async function saveSettings() {
  // Fetch current config to preserve fields managed by dashboard panels
  let currentCfg = {};
  try {
    const r = await fetch('/api/config');
    if (r.ok) currentCfg = await r.json();
  } catch (e) { /* use empty */ }

  const cfg = {
    ...currentCfg,
    awtrix_ip: get('cfg-awtrix-ip').trim(),
    built_in_apps: {
      TIM:  document.getElementById('cfg-builtin-TIM')?.checked ?? true,
      DAT:  document.getElementById('cfg-builtin-DAT')?.checked ?? true,
      TEMP: document.getElementById('cfg-builtin-TEMP')?.checked ?? true,
      HUM:  document.getElementById('cfg-builtin-HUM')?.checked ?? true,
      BAT:  document.getElementById('cfg-builtin-BAT')?.checked ?? true,
    },
    weather: {
      location_name:        get('cfg-weather-location').trim(),
      latitude:             parseFloat(get('cfg-weather-lat')),
      longitude:            parseFloat(get('cfg-weather-lon')),
      poll_interval_seconds: parseInt(get('cfg-weather-poll')),
    },
    reddit: {
      subreddits:           get('cfg-reddit-subs').split(',').map(s => s.trim()).filter(Boolean),
      min_score:            parseInt(get('cfg-reddit-score')),
      max_age_hours:        parseInt(get('cfg-reddit-age')),
      poll_interval_seconds: parseInt(get('cfg-reddit-poll')),
      max_posts:            parseInt(get('cfg-reddit-posts')),
    },
    team_tags: _teamTags,
    valorant: {
      poll_interval_idle_seconds:      parseInt(get('cfg-val-idle')),
      poll_interval_pre_match_seconds: parseInt(get('cfg-val-prematch')),
      poll_interval_live_seconds:      parseInt(get('cfg-val-live')),
      cooldown_seconds:                parseInt(get('cfg-val-cooldown')),
      pre_match_window_minutes:        parseInt(get('cfg-val-window')),
      live_priority:                   document.getElementById('cfg-val-priority')?.checked ?? true,
      favourite_teams:                 [..._favouriteTeams],
    },
    twitch: {
      ...(currentCfg.twitch || {}),
      client_id:     get('cfg-twitch-id').trim(),
      client_secret: get('cfg-twitch-secret').trim(),
    },
    display: {
      ...(currentCfg.display || {}),
      scroll_speed:        parseInt(get('cfg-display-speed')) || 55,
      sensor_temp_offset:  parseFloat(get('cfg-display-offset')) || 0,
      base_scroll_speed_px_per_sec: parseInt(get('cfg-display-base-speed')) || 40,
      matrix_width:        parseInt(get('cfg-display-matrix-width')) || 32,
      avg_char_width:      parseFloat(get('cfg-display-avg-char')) || 5,
      app_duration_floor:  parseInt(get('cfg-display-dur-floor')) || 10,
      app_duration_cap:    parseInt(get('cfg-display-dur-cap')) || 120,
      auto_dim_enabled:    document.getElementById('cfg-display-autodim')?.checked ?? false,
      lux_threshold:       parseInt(get('cfg-display-lux')) || 50,
      dim_brightness:      parseInt(get('cfg-display-dimbri')) || 20,
      normal_brightness:   parseInt(document.getElementById('cfg-display-autodim')?.checked ? get('cfg-display-normalbri') : get('cfg-display-fixedbri')) || 180,
    },
    module_order: getCurrentModuleOrder(),
  };

  delete cfg.wordnik;

  const resultEl = document.getElementById('save-result');
  setResult(resultEl, 'Saving…', '');

  try {
    const res  = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cfg),
    });
    const data = await res.json();
    if (res.ok) {
      setResult(resultEl, 'Saved', 'ok');
    } else {
      setResult(resultEl, 'Error: ' + (data.detail || res.status), 'err');
    }
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
}

function getCurrentModuleOrder() {
  const container = document.getElementById('modules-list');
  const items = container.querySelectorAll('.module-item[data-module]');
  if (items.length === 0) return [];
  return [...items].map(el => el.dataset.module);
}

async function pingDevice() {
  const resultEl = document.getElementById('ping-result');
  setResult(resultEl, 'Pinging…', '');
  try {
    const res  = await fetch('/api/device/ping', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'online') {
      setResult(resultEl, 'Online', 'ok');
      updateDeviceIndicator('online', data.checked_at);
    } else {
      setResult(resultEl, 'No response', 'err');
      updateDeviceIndicator('offline', data.checked_at);
    }
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
}

async function rebootClock() {
  const resultEl = document.getElementById('reboot-result') || document.getElementById('ping-result');
  setResult(resultEl, 'Rebooting…', '');
  try {
    const res = await fetch('/api/device/reboot', { method: 'POST' });
    const data = await res.json();
    if (res.ok && data.ok) {
      setResult(resultEl, 'Rebooting…', 'ok');
      updateDeviceIndicator('unknown', '');
      setTimeout(() => setResult(resultEl, 'Device may take ~30s to come back', ''), 2000);
    } else {
      setResult(resultEl, 'Failed', 'err');
    }
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
}

async function softRestart() {
  const resultEl = document.getElementById('soft-restart-result');
  setResult(resultEl, 'Restarting…', '');
  try {
    const res = await fetch('/api/soft-restart', { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      setResult(resultEl, 'Done', 'ok');
      setTimeout(() => refreshStatus(), 500);
    } else {
      setResult(resultEl, 'Error: ' + (data.detail || res.status), 'err');
    }
  } catch (e) {
    setResult(resultEl, 'Request failed', 'err');
  }
}


/* ── Utilities ───────────────────────────────────────────────────────────── */

function get(id) { return document.getElementById(id).value; }
function set(id, val) { document.getElementById(id).value = val; }

function setResult(el, text, type) {
  el.textContent = text;
  el.className = 'inline-result' + (type ? ' result-' + type : '');
  if (type === 'ok' || type === 'err') {
    setTimeout(() => { el.textContent = ''; el.className = 'inline-result'; }, 4000);
  }
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/* ── Hover card ──────────────────────────────────────────────────────────── */

(function initHoverCard() {
  const card = document.createElement('div');
  card.id = 'text-hover-card';
  card.className = 'text-hover-card';
  document.body.appendChild(card);

  function formatCardText(fullText) {
    // Reddit: blocks separated by ·····, within-block segments by |
    if (fullText.includes('   ·····   ') || fullText.includes('   |   ')) {
      const blocks = fullText.split('   ·····   ');
      return blocks.map(block =>
        block.split('   |   ').map(seg => {
          seg = seg.trim();
          return seg.startsWith('↳ ') ? '  ' + seg : seg;
        }).join('\n')
      ).join('\n\n');
    }
    return fullText;
  }

  function show(cell) {
    const fullText = cell.dataset.full;
    if (!fullText) return;
    card.textContent = formatCardText(fullText);
    card.style.display = 'block';
    const rect = cell.getBoundingClientRect();
    const cardW = 420;
    let left = rect.left;
    let top  = rect.bottom + 8;
    if (left + cardW > window.innerWidth - 12) left = window.innerWidth - cardW - 12;
    if (left < 8) left = 8;
    card.style.left = Math.round(left) + 'px';
    card.style.top  = Math.round(top)  + 'px';
  }

  let hideTimer = null;

  function hide()         { card.style.display = 'none'; hideTimer = null; }
  function scheduleHide() { hideTimer = setTimeout(hide, 150); }
  function cancelHide()   { if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; } }

  document.addEventListener('mouseover', e => {
    const cell = e.target.closest('.app-text-expandable');
    if (cell && cell.dataset.full) { cancelHide(); show(cell); }
  });
  document.addEventListener('mouseout', e => {
    const cell = e.target.closest('.app-text-expandable');
    if (cell && !cell.contains(e.relatedTarget) && !card.contains(e.relatedTarget)) scheduleHide();
  });
  card.addEventListener('mouseenter', cancelHide);
  card.addEventListener('mouseleave', scheduleHide);
})();


/* ── Init ────────────────────────────────────────────────────────────────── */

function updateClock() {
  const el = document.getElementById('current-time');
  if (el) el.textContent = new Date().toLocaleTimeString('en-GB');
}
updateClock();
setInterval(updateClock, 1000);

refreshStatus();
setInterval(refreshStatus, 5000);
