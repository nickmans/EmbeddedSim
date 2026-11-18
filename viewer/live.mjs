const el = id => document.getElementById(id);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export function openLive(id, render) {
  const endpoint = `/api/live/${id}`;
  let revision;
  let generation = 0;
  let rows = [];
  let header = "";
  let status;
  let sending = false;
  let controlVersion = 0;
  let disconnected = false;

  document.title = 'Live robot simulation · EmbeddedSim';
  document.body.classList.add('live-mode');
  el('viewer-title').textContent = 'Live robot simulation';
  el('viewer-subtitle').textContent = 'STM32 differential-drive robot · Virtual-time execution';
  el('replay-files').hidden = el('replay-transport').hidden = el('replay-conventions').hidden = true;
  el('conventions-title').textContent = 'Model limitations';
  el('live-controls').hidden = false;
  el('source').textContent = 'Connecting to live session…';
  el('source').setAttribute('role', 'status');

  function error(message) {
    el('error').textContent = message;
    el('error').hidden = !message;
  }

  function paint() {
    if (!status) return;
    const {state, control_pending: pending, samples, virtual_ns: time, speed, wall_seconds: wall} = status;
    if (disconnected) {
      el('source').textContent = 'Disconnected · showing last received state';
    } else {
      const label = state[0].toUpperCase() + state.slice(1);
      el('source').textContent = pending ? `${label} · ${pending} pending` : label;
    }
    el('metadata').textContent = `Run ${status.generation} · ${samples.toLocaleString()} recorded samples`;
    el('live-time').textContent = `${(time / 1e9).toFixed(3)} / ${(status.duration_ns / 1e9).toFixed(3)} s`;
    el('live-wall').textContent = `${wall.toFixed(1)} s`;
    el('live-speed').textContent = speed ? `${speed.toFixed(2)}× avg` : '—';
    const controlBlocked = Boolean(pending || sending || disconnected);
    el('live-toggle').disabled = controlBlocked || !['ready', 'running', 'paused'].includes(state);
    el('live-toggle').textContent = state === 'paused' ? 'Resume' : state === 'running' ? 'Pause' : 'Start';
    el('live-stop').disabled = controlBlocked || !['ready', 'running', 'paused'].includes(state);
    el('live-reset').disabled = controlBlocked || state === 'preparing';
    const queued = status.pending_right_Nms;
    el('live-load').disabled = el('live-apply').disabled = controlBlocked || queued !== null ||
      !['running', 'paused'].includes(state);
    const event = status.last_event;
    el('live-event').textContent = queued !== null ? `Pending ${queued} N·m/(rad/s) · ${state === "paused" ? "applies on resume" : "awaiting the next boundary"}`
      : event ? `Applied ${event.right_Nms} N·m/(rad/s) at ${(event.at_ns / 1e9).toFixed(3)} s virtual`
      : 'External viscous resistance · range 0–0.02';
    el('live-faults').hidden = !status.fault_enabled;
    const faultBlocked = controlBlocked || Boolean(status.pending_fault) || !['running', 'paused'].includes(state);
    for (const id of ['live-fault-channel', 'live-fault-level', 'live-fault-apply', 'live-fault-clear']) {
      el(id).disabled = faultBlocked;
    }
    const fault = status.pending_fault || status.last_fault_event;
    const overrides = Object.entries(status.live_faults).map(([channel, level]) => `${channel} = ${level}`).join(', ');
    const change = fault && (fault.level === null ? `clear ${fault.channel}` : `${fault.channel} stuck at ${fault.level}`);
    el('live-fault-event').textContent = status.pending_fault
      ? `Pending · ${change} · ${state === 'paused' ? 'applies on resume' : 'next boundary'}`
      : fault ? `Applied · ${change} at ${(fault.at_ns / 1e9).toFixed(3)} s virtual · ${overrides || 'no live overrides'}`
        : 'Live overrides take precedence over the scheduled faults.';
    const warnings = status.warnings || [];
    el('live-warnings').hidden = !warnings.length;
    el('live-warnings').textContent = warnings.length ? `Renode warnings · ${warnings.join(' · ')}` : '';
    el('live-failure-log').hidden = state !== 'failed';
    if (state === 'failed') el('live-failure-log').href = `/jobs/${status.recording_id}/renode.log`;
    const available = ['completed', 'stopped'].includes(state) && samples > 0;
    el('live-files').hidden = !available;
    if (available) {
      const recording = status.recording_id;
      el('live-save').href = `/jobs/${recording}/recording.csv`;
      el('live-events').href = `/jobs/${recording}/events.json`;
      el('live-log').href = `/jobs/${recording}/renode.log`;
      el('live-config').href = `/jobs/${recording}/config.json`;
      el('live-replay').href = `/viewer/?job=${recording}`;
    }
  }

  function receive(next) {
    // A slow poll that started before a control response must not rewind the view.
    if (status && next.revision < status.revision) return;
    status = next;
    if (next.display && next.revision !== revision) {
      const delta = next.display;
      if (Object.hasOwn(delta, 'header')) {
        header = delta.header;
        rows = [];
      }
      if (delta.offset !== rows.length) {
        // Request a fresh snapshot after a lost cursor.
        generation = 0;
        rows = [];
        return;
      }
      generation = next.generation;
      rows.push(...delta.rows);
      const csv = header ? [header, ...rows, ...(delta.latest ? [delta.latest] : []), ''].join('\n') : '';
      render(csv, next);
      revision = next.revision;
    }
    paint();
  }

  async function command(action, value) {
    sending = true;
    controlVersion++;
    paint();
    try {
      const response = await fetch(endpoint, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, signal: AbortSignal.timeout(7000),
        body: JSON.stringify(action === 'fault' ? {action, ...value} : {action, right_Nms: value}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error);
      error('');
      receive(result);
    } catch (failure) {
      error(failure.message);
    } finally {
      sending = false;
      paint();
    }
  }

  el('live-toggle').addEventListener('click', () =>
    command(status.state === 'ready' ? 'start' : status.state === 'running' ? 'pause' : 'resume'));
  el('live-stop').addEventListener('click', () => command('stop'));
  el('live-reset').addEventListener('click', () => command('reset'));
  el('live-load-form').addEventListener('submit', event => {
    event.preventDefault();
    command('load', el('live-load').valueAsNumber);
  });

  function faultCommand(level) {
    command('fault', {channel: el('live-fault-channel').value, level});
  }
  el('live-fault-form').addEventListener('submit', event => {
    event.preventDefault();
    faultCommand(Number(el('live-fault-level').value));
  });
  el('live-fault-clear').addEventListener('click', () => faultCommand(null));

  async function poll() {
    for (;;) {
      try {
        if (!sending) {
          const stamp = controlVersion;
          const response = await fetch(`${endpoint}?cursor=${generation}:${rows.length}`,
                                       {signal: AbortSignal.timeout(5000)});
          const next = await response.json();
          if (!response.ok) {
            if (response.status === 404) {
              error(next.error);
              disconnected = true;
              paint();
              return;
            }
            throw new Error(next.error);
          }
          if (!sending && stamp === controlVersion) {
            if (disconnected || next.error) error(next.error || '');
            disconnected = false;
            receive(next);
          }
        }
      } catch {
        disconnected = true;
        el('source').textContent = 'Disconnected · reconnecting…';
        paint();
      }
      await sleep(disconnected ? 750 : 240);
    }
  }
  poll();
}
