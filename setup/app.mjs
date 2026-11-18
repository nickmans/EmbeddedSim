const el = id => document.getElementById(id);
const bodyKeys = ['mass_kg', 'yaw_inertia_kg_m2', 'wheel_radius_m', 'track_width_m', 'wheel_inertia_kg_m2'];
const poseKeys = ['x_m', 'y_m', 'heading_rad'];
const labels = {
  pwm: 'Driver PWM input', direction: 'Driver direction input',
  encoder_a: 'Encoder A output', encoder_b: 'Encoder B output',
};
let preset, routes, endpoints;
let firmware;
let snapshots = [];
let busy = false;
let configuration;
const passiveProfile = "pwm-signal-pll168-v1";
const passive = () => el("target").value === passiveProfile;
const connections = new Map();

async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function report(error) {
  el('error').hidden = !error;
  el('error').textContent = error ? error.message : '';
}

function setBusy(value) {
  busy = value;
  for (const control of document.querySelectorAll('.setup-grid input, .setup-grid select, .setup-grid button, .setup-grid textarea, .wiring button, .wiring input, #wiring-rows select, #run, #live')) {
    control.disabled = value;
  }
  el('suggest').disabled = value || !snapshots.length;
}

function showCapabilities() {
  for (const item of document.querySelectorAll('[data-robot]')) item.hidden = passive();
  el('replay').hidden = passive() || !el('replay').getAttribute('href');
  el('passive-hint').hidden = !passive();
  el('existing-live').hidden = passive() || !el('existing-live').getAttribute('href');
  el('run-title').textContent = passive() ? 'Discovery status' : 'Execution';
}

function loadConfig(config) {
  if (config?.target?.profile === passiveProfile && config.target.part === 'stm32f407vgt6') {
    el('target').value = passiveProfile;
    showCapabilities();
    resetDiscovery();
    return;
  }
  if (config?.version !== 1 || config?.target?.part !== 'stm32f407vgt6' ||
      config.target.profile !== 'robot-hsi16-v1' ||
      config.robot?.preset !== preset.robot.preset || config.world?.type !== preset.world.type) {
    throw new Error('Choose a version 1 configuration for STM32F407VGT6 · HSI16 and the differential-drive preset.');
  }
  for (const [key, options] of connections) {
    const pin = config.wiring?.[key];
    if (pin !== null && ![...options.select.options].some(option => option.value && option.value === pin)) {
      throw new Error(`${key}: ${pin} is outside the qualified routes.`);
    }
  }
  configuration = structuredClone(config);
  el('target').value = config.target.part;
  el('observer').value = config.scenario.observer;
  el('duration').value = config.scenario.duration_s;
  el('loads').value = JSON.stringify(config.scenario.loads, null, 2);
  el('encoder-faults').value = JSON.stringify(config.scenario.encoder_faults ?? [], null, 2);
  el('encoder-fault-evidence').checked = config.scenario.encoder_fault_evidence ?? false;
  for (const key of bodyKeys) el(key).value = config.robot.body[key];
  for (const key of poseKeys) el(key).value = config.scenario.initial_pose[key];
  for (const [key, row] of connections) row.select.value = config.wiring[key] || '';
  showCapabilities();
  resetDiscovery();
}

function getConfig() {
  if (!el('target').value) throw new Error('Select the MCU and clock profile.');
  if (passive()) return {version: 1, target: {part: 'stm32f407vgt6', profile: passiveProfile}};
  for (const id of ['duration', ...bodyKeys, ...poseKeys]) {
    if (!el(id).value || !el(id).checkValidity()) throw new Error(`Check the value for ${el(id).parentElement.firstChild.textContent.trim()}.`);
  }
  const config = structuredClone(configuration);
  config.scenario.duration_s = el('duration').valueAsNumber;
  config.scenario.observer = el('observer').value;
  try {
    config.scenario.loads = JSON.parse(el('loads').value);
  } catch {
    throw new Error('Load events must contain a JSON array. Use [] for no external load.');
  }
  let faults;
  try {
    faults = JSON.parse(el('encoder-faults').value);
  } catch {
    throw new Error('Scheduled encoder faults must contain a JSON array. Use [] for no scheduled faults.');
  }
  if (!Array.isArray(faults)) throw new Error('Scheduled encoder faults must be an array.');
  if (faults.length || Object.hasOwn(config.scenario, 'encoder_faults')) config.scenario.encoder_faults = faults;
  const evidence = el('encoder-fault-evidence').checked;
  if (evidence || Object.hasOwn(config.scenario, 'encoder_fault_evidence')) config.scenario.encoder_fault_evidence = evidence;
  for (const key of bodyKeys) config.robot.body[key] = el(key).valueAsNumber;
  for (const key of poseKeys) config.scenario.initial_pose[key] = el(key).valueAsNumber;
  for (const [key, {select}] of connections) config.wiring[key] = select.value || null;
  return config;
}

function node(tag, text) {
  const item = document.createElement(tag);
  if (text) item.textContent = text;
  return item;
}

function buildWiring() {
  for (const [key, role] of Object.entries(endpoints)) {
    const [side] = key.split('.');
    const title = `${side === 'left' ? 'Left' : 'Right'} · ${labels[role]}`;
    const select = node('select');
    select.setAttribute('aria-label', title);
    select.append(new Option('Disconnected', ''));
    for (const [pin, [type]] of Object.entries(routes)) {
      if (type === role) select.append(new Option(pin, pin));
    }
    const row = node('tr');
    const endpoint = node('td', title);
    const wiring = node('td');
    const configured = node('td');
    const observed = node('td');
    wiring.append(select);
    row.append(endpoint, wiring, configured, observed);
    el('wiring-rows').append(row);
    connections.set(key, {select, configured, observed});
    select.addEventListener('change', () => {
      report();
      if (snapshots.length) el('status').textContent = 'Wiring changed. Rerun discovery to measure with these connections.';
      renderSnapshot();
    });
  }
}

function renderSnapshot() {
  const snapshot = snapshots[Number(el('snapshot-select').value)];
  el('snapshot').hidden = !snapshot;
  el('signal-table').hidden = !passive() || !snapshot;
  if (passive()) {
    const body = el('signal-rows');
    body.replaceChildren();
    if (!snapshot) return;
    el('discovery-summary').textContent = snapshot.clock_profile_matches
      ? `HCLK ${snapshot.clocks.hclk_hz / 1e6} MHz · APB1 timers ${snapshot.clocks.apb1_timer_hz / 1e6} MHz`
      : 'Clock profile unconfirmed';
    for (const [name, pin] of Object.entries(snapshot.pins)) {
      const row = node('tr');
      const mode = [pin.mode, pin.af === null ? null : `AF${pin.af}`, pin.peripheral].filter(Boolean);
      const signal = pin.observed;
      const activity = signal?.period_s ? `${(signal.period_s * 1e6).toFixed(3)} µs · ${(signal.duty * 100).toFixed(2)}%`
        : signal ? `${signal.activity} · level ${signal.level}` : '—';
      row.append(node('td', name), node('td', pin.role), node('td', mode.join(' · ')), node('td', activity));
      body.append(row);
    }
    return;
  }
  if (snapshot) {
    const count = Object.values(snapshot.pins).filter(pin => pin.qualified).length;
    el('discovery-summary').textContent = `${count}/8 routes confirmed · ${snapshot.clock_profile_matches ? 'HSI16 profile matched' : 'Clock profile unconfirmed'}`;
  }
  for (const [key, {select, configured, observed}] of connections) {
    const name = select.value || preset.wiring[key];
    const pin = snapshot?.pins[name];
    configured.replaceChildren();
    observed.textContent = '—';
    if (!pin) {
      configured.textContent = select.value ? 'Awaiting discovery' : 'Disconnected';
      continue;
    }
    const state = node('span', `${name} · ${pin.configuration}`);
    state.className = pin.qualified ? 'confirmed' : 'unconfirmed';
    configured.append(state);
    const detail = [pin.mode, pin.af === null ? null : `AF${pin.af}`, pin.peripheral, pin.role].filter(Boolean);
    if (pin.timer) {
      const {psc, arr, ccr, sms, enabled, channel_enabled, clock_enabled} = pin.timer;
      detail.push(`PSC ${psc}`, `ARR ${arr}`, `SMS ${sms}`);
      if (ccr !== null) detail.push(`CCR ${ccr}`);
      detail.push(enabled ? 'running' : 'stopped');
      if (!channel_enabled) detail.push('channel disabled');
      if (!clock_enabled) detail.push('clock gated');
    }
    configured.append(node('small', detail.join(' · ')));
    const signal = pin.activity;
    if (!signal) continue;
    if (signal.kind === 'periodic') observed.textContent = `${(signal.period_s * 1000).toFixed(3)} ms · ${(signal.duty * 100).toFixed(1)}%`;
    else if (signal.kind === 'constant') observed.textContent = `Constant ${signal.level} · ${signal.duty * 100}%`;
    else if (signal.kind) observed.textContent = 'Insufficient edges';
    else observed.textContent = `${signal.level} · ${signal.edges} edge(s)`;
  }
}

function resetDiscovery() {
  snapshots = [];
  el('snapshot-select').replaceChildren();
  el('suggest').disabled = true;
  renderSnapshot();
}

function showDiscovery(result) {
  snapshots = result.snapshots;
  el('snapshot-select').replaceChildren(...snapshots.map((snapshot, index) =>
    new Option(`${snapshot.time_s.toFixed(3)} s`, index)));
  el('snapshot-select').value = snapshots.length - 1;
  el('suggest').disabled = busy;
  renderSnapshot();
}

async function encoded(file) {
  if (file.size > 16 * 1024 * 1024) throw new Error('Select an ELF of 16 MiB or smaller.');
  const bytes = new Uint8Array(await file.arrayBuffer());
  let content = '';
  for (let offset = 0; offset < bytes.length; offset += 16384) {
    content += String.fromCharCode(...bytes.subarray(offset, offset + 16384));
  }
  return btoa(content);
}

async function execute(operation) {
  if (busy) return;
  report();
  el('log').hidden = true;
  el('warnings').hidden = true;
  try {
    const config = getConfig();
    if (!firmware) throw new Error('Choose an ELF or use the example ELF.');
    setBusy(true);
    el('status').textContent = operation === 'discover' ? 'Discovering pins in a fresh Renode machine…'
      : operation === 'live' ? 'Opening the live viewer…' : 'Running scenario in a fresh Renode machine…';
    const job = await request('/api/jobs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        operation, config, seconds: el('discovery-time').valueAsNumber,
        firmware: firmware === 'example' ? firmware : await encoded(firmware),
      }),
    });
    if (operation === 'live') {
      location.href = `/viewer/?live=${job.id}`;
      return;
    }
    let result = job;
    while (result.state === 'running') {
      await new Promise(resolve => setTimeout(resolve, 600));
      result = await request(`/jobs/${job.id}`);
    }
    el('log').href = `/jobs/${job.id}/renode.log`;
    el('log').hidden = false;
    if (result.state === 'failed') throw new Error(result.error);
    const warnings = result.result.warnings || [];
    el('warnings').hidden = !warnings.length;
    el('warnings').textContent = warnings.length ? `Renode warnings · ${warnings.join(' · ')}` : '';
    if (operation === 'discover') {
      showDiscovery(result.result);
      el('status').textContent = result.result.diagnostics?.join(' ') ||
        (passive() ? 'Discovery complete. Review the pin snapshots.' : 'Discovery complete. Review the snapshots and confirm physical wiring.');
    } else {
      el('replay').href = `/viewer/?job=${job.id}`;
      el('replay').hidden = false;
      el('status').textContent = `Run complete · ${result.result.samples.toLocaleString()} recorded samples.`;
    }
  } catch (error) {
    el('status').textContent = 'Check the setup and try again.';
    report(error);
  } finally {
    setBusy(false);
  }
}

async function init() {
  try {
    const data = await request('/api/preset');
    ({config: preset, endpoints, pins: routes} = data);
    buildWiring();
    for (const [key, [min, max]] of Object.entries(data.limits)) {
      el(key).min = min;
      el(key).max = max;
    }
    loadConfig(preset);
    el('target').value = '';
    const active = await request('/api/live');
    if (active.id) {
      el('existing-live').href = `/viewer/?live=${active.id}`;
      el('existing-live').hidden = false;
    }
  } catch (error) {
    report(error);
    return;
  }

  el('example').addEventListener('click', () => {
    firmware = 'example';
    el('elf').value = '';
    if (!passive()) el('observer').value = 'example-v1';
    el('firmware-name').textContent = 'EmbeddedSim example ELF';
    resetDiscovery();
    report();
  });
  el('elf').addEventListener('change', event => {
    if (!event.target.files[0]) return;
    firmware = event.target.files[0];
    el('observer').value = 'none';
    el('firmware-name').textContent = firmware.name;
    resetDiscovery();
    report();
  });
  el('import').addEventListener('change', async event => {
    try {
      const file = event.target.files[0];
      if (!file) return;
      if (file.size > 65536) throw new Error('Select a configuration up to 64 KiB.');
      const config = await request('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: await file.text(),
      });
      loadConfig(config);
      report();
    } catch (error) { report(error); }
    event.target.value = '';
  });
  el('export').addEventListener('click', async () => {
    try {
      const config = await request('/api/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(getConfig()),
      });
      const data = JSON.stringify(config, null, 2);
      const url = URL.createObjectURL(new Blob([data + '\n'], {type: 'application/json'}));
      const link = node('a');
      link.href = url;
      link.download = 'robot-config.json';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      report();
    } catch (error) { report(error); }
  });
  el('suggest').addEventListener('click', () => {
    const snapshot = snapshots[Number(el('snapshot-select').value)];
    for (const [key, {select}] of connections) {
      const pin = preset.wiring[key];
      const occupied = [...connections.values()].some(row => row.select.value === pin);
      if (!select.value && snapshot.pins[pin]?.qualified && !occupied) select.value = pin;
    }
    renderSnapshot();
  });
  el('snapshot-select').addEventListener('change', renderSnapshot);
  el('discover').addEventListener('click', () => execute('discover'));
  el('run').addEventListener('click', () => execute('run'));
  el('live').addEventListener('click', () => execute('live'));
  el('target').addEventListener('change', () => {
    showCapabilities();
    resetDiscovery();
  });
}

init();
