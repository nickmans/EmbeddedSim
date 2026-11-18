import { headingErrorKey, parseTrace, poseAt, positionErrorKey, sampleAt } from './trace.mjs';
import { openLive } from './live.mjs';
import { createScene, drawPlot, moveCursor, plotFraction } from './drawing.mjs';

const byId = id => document.getElementById(id);
const scene = byId('scene');
const scrub = byId('scrub');
const play = byId('play');
const follow = byId('follow');
const odom = byId('odom');
const file = byId('file');
const job = new URLSearchParams(location.search).get('job');
const requestedLive = new URLSearchParams(location.search).get('live');
const liveId = /^[0-9a-f]{32}$/.test(requestedLive || '') ? requestedLive : null;
const left = '#66e4de';
const right = '#ffc478';

function pair(keys, scale = 1, prefix = '', dash = false, step = false) {
  return keys.map((key, i) => ({ key, scale, name: `${prefix}${i === 0 ? 'L' : 'R'}`, color: i === 0 ? left : right, dash, step }));
}

const actual = pair(['wl_rad_s', 'wr_rad_s'], 1, 'Model ');
const estimate = pair(['estimate_l_rad_s', 'estimate_r_rad_s'], 1, 'FW ', true);
const current = pair(['il_A', 'ir_A']);
const duty = pair(['duty_l', 'duty_r'], 100);
const direction = pair(['dir_l', 'dir_r'], 1, '', false, true);
direction[1].dash = true;
const positionError = [{ key: positionErrorKey, scale: 1000, name: 'Firmware − model (distance)', color: left }];
const headingError = [{ key: headingErrorKey, scale: 1000, name: 'Firmware − model (signed)', color: right }];
const plots = [
  ['Wheel speed · rad/s', [...actual, ...estimate]],
  ['PWM duty · %', duty],
  ['Direction GPIO · ±1', direction],
  ['Motor current · A', current],
  ['Position error · mm', positionError],
  ['Heading error · mrad', headingError],
];
const rows = [
  ['Pose · m, rad', 'Model ground truth', [['x_m', 'x'], ['y_m', 'y'], ['heading_rad', 'ψ']]],
  ['Odometry · m, rad', 'Firmware encoder estimate', [['odom_x_m', 'x'], ['odom_y_m', 'y'], ['odom_heading_rad', 'ψ']]],
  ['Wheel speed · rad/s', 'Model ground truth', actual],
  ['Wheel speed · rad/s', 'Firmware encoder estimate', estimate],
  ['Setpoint · rad/s', 'Firmware commanded', pair(['reference_l_rad_s', 'reference_r_rad_s'])],
  ['PWM duty · %', 'Measured pins · trailing 1 ms', duty],
  ['Direction GPIO', 'Measured pins', direction],
  ['Motor current · A', 'Model electrical state', current],
  ['Added drag · N·m/(rad/s)', 'External model input', [['left_drag_Nms', 'L'], ['right_drag_Nms', 'R']]],
  ['Resistance torque · N·m', 'Model load · signed', pair(['resistance_l_Nm', 'resistance_r_Nm'])],
  ...['left_a', 'left_b', 'right_a', 'right_b'].map(channel => [
    `Encoder ${channel.replace('_', ' ').toUpperCase()} · edges`, 'Physical encoder and MCU GPIO · cumulative',
    [[`enc_${channel}_physical_edges`, 'Physical'], [`enc_${channel}_delivered_edges`, 'GPIO'],
      [`enc_${channel}_forced_level`, 'Mask']],
  ]),
  ['Estimation error · mm, mrad', 'Derived from matched samples', [...positionError, ...headingError].map((item, i) => ({ ...item, name: i ? 'ψ' : 'pos' }))],
];

let trace;
let time = 0;
let frame;
let previous;
let generation = 0;
let drawScene;
let charts = [];
let readouts = [];
let lastSample = -1;

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content) node.textContent = content;
  if (className) node.className = className;
  return node;
}

function buildPanels() {
  byId('plots').replaceChildren();
  byId('readouts').replaceChildren();
  charts = [];
  readouts = [];

  for (const [title, origin, columns] of rows) {
    const series = columns.map(item => Array.isArray(item) ? { key: item[0], name: item[1], scale: 1 } : item)
      .filter(item => Object.hasOwn(trace.data, item.key));
    if (!series.length) continue;
    const row = element('section', '', 'readout');
    const label = element('div');
    label.append(element('h3', title), element('div', origin, 'origin'));
    const values = element('div', '', 'values');
    for (const signal of series) {
      const group = element('span');
      const value = element('span');
      const name = signal.name.replace(/^(Model|FW) /, '');
      group.append(element('b', `${name} `), value);
      values.append(group);
      readouts.push({ signal, value });
    }
    row.append(label, values);
    byId('readouts').append(row);
  }

  for (const [title, columns] of plots) {
    const series = columns.filter(item => Object.hasOwn(trace.data, item.key));
    if (!series.length) continue;
    const figure = element('figure', '', 'plot');
    const caption = element('figcaption');
    const legend = element('div', '', 'plot-key');
    for (const signal of series) {
      const entry = element('span', signal.name, signal.dash ? 'dashed' : '');
      entry.style.setProperty('--line', signal.color);
      legend.append(entry);
    }
    caption.append(element('h3', title), legend);
    const area = element('div', '', 'plot-area');
    const canvas = element('canvas');
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', `${title} versus simulation time. Use the time scrubber to inspect values.`);
    const cursor = element('div', '', 'cursor');
    cursor.setAttribute('aria-hidden', 'true');
    function seek(event) {
      const rect = canvas.getBoundingClientRect();
      setTime(trace.start + plotFraction(event.clientX - rect.left, rect.width) * (trace.end - trace.start));
    }
    canvas.addEventListener('pointerdown', event => {
      if (liveId || event.button !== 0) return;
      pause();
      canvas.setPointerCapture(event.pointerId);
      seek(event);
    });
    canvas.addEventListener('pointermove', event => {
      if (canvas.hasPointerCapture(event.pointerId)) seek(event);
    });
    area.append(canvas, cursor);
    figure.append(caption, area);
    byId('plots').append(figure);
    charts.push({ canvas, cursor, series });
  }
  byId('plots').hidden = charts.length === 0;
  document.querySelector('.signals').hidden = charts.length === 0;
}

function updatePlots() {
  if (!trace) return;
  for (const { canvas, series } of charts) drawPlot(canvas, trace, series);
  render();
}

function format(key, value) {
  if (typeof key !== 'string') return value.toFixed(3);
  if (key.endsWith('_forced_level')) return value === -1 ? 'pass' : value === 0 ? 'low' : 'high';
  if (key.endsWith('_edges')) return value.toFixed(0);
  if (key.startsWith('dir_')) return value === 1 ? '+1 high' : '−1 low';
  if (key.endsWith('_drag_Nms') || key.startsWith('resistance_')) return value.toFixed(4);
  return value.toFixed(3);
}

function render() {
  const { data, start, end } = trace;
  const index = sampleAt(data.time_s, time);
  const pose = poseAt(data, time, index);
  const fraction = end === start ? 0 : (time - start) / (end - start);
  scrub.value = time;
  const clock = `${time.toFixed(3)} s`;
  byId('timestamp').textContent = clock;
  scrub.setAttribute('aria-valuetext', clock);
  if (lastSample !== index) {
    byId('sample-time').textContent = `Sample ${data.time_s[index].toFixed(3)} s`;
    for (const { signal, value } of readouts) {
      value.textContent = format(signal.key, data[signal.key][index] * signal.scale);
    }
    lastSample = index;
  }
  for (const { canvas, cursor } of charts) moveCursor(canvas, cursor, fraction);
  drawScene(pose, odom.checked, follow.getAttribute('aria-pressed') === 'true');
}

function setTime(value) {
  time = Math.min(trace.end, Math.max(trace.start, value));
  render();
}

function pause() {
  cancelAnimationFrame(frame);
  frame = undefined;
  previous = undefined;
  play.textContent = 'Play';
}

function animate(now) {
  const elapsed = previous === undefined ? 0 : (now - previous) / 1000;
  previous = now;
  setTime(time + elapsed * Number(byId('speed').value));
  if (time >= trace.end) pause();
  else frame = requestAnimationFrame(animate);
}

function setTrace(next, name) {
  pause();
  trace = next;
  lastSample = -1;
  const { data, start, end } = trace;
  const duration = end - start;
  drawScene = createScene(scene, data, next.geometry);
  const { radius, track } = next.geometry;
  byId('scene-note').textContent = `Schematic axle · Track ${track.toFixed(3)} m · Wheel radius ${radius.toFixed(3)} m`;
  if (!liveId) byId('source').textContent = name;
  byId('metadata').textContent = `${data.time_s.length.toLocaleString()} samples · Robot CSV v1`;
  byId('duration').textContent = `${duration.toFixed(3)} s duration`;
  byId('start-time').textContent = `${start.toFixed(3)} s`;
  byId('end-time').textContent = `${end.toFixed(3)} s`;
  scrub.min = start;
  scrub.max = end;
  scrub.disabled = play.disabled = byId('speed').disabled = duration === 0;
  follow.disabled = byId('fit').disabled = byId('restart').disabled = false;
  follow.setAttribute('aria-pressed', 'false');
  odom.disabled = !Object.hasOwn(data, positionErrorKey);
  odom.checked = !odom.disabled;
  odom.closest('label').hidden = odom.disabled;
  time = start;
  buildPanels();
  updatePlots();
}

async function load(read, name) {
  const token = ++generation;
  const error = byId('error');
  error.hidden = true;
  try {
    const csv = await read();
    if (token === generation) setTrace(parseTrace(csv), name);
  } catch (failure) {
    if (token !== generation) return;
    error.textContent = `${name}: ${failure.message}`;
    error.hidden = false;
    if (!trace) byId('source').textContent = 'No recording loaded';
  }
}

function loadDemo() {
  load(async () => {
    let response;
    try {
      response = await fetch('../tests/robot/out/main.csv');
    } catch {
      throw new Error('Serve the repository over HTTP or open a recorded CSV.');
    }
    if (!response.ok) throw new Error('Demo CSV unavailable. Run bash viewer/demo.sh from the repository or open a recorded CSV.');
    return response.text();
  }, 'main.csv');
}

byId('demo').addEventListener('click', loadDemo);
file.addEventListener('change', () => {
  const selected = file.files[0];
  if (selected) load(() => selected.text(), selected.name);
  file.value = '';
});
play.addEventListener('click', () => {
  if (frame !== undefined) return pause();
  if (time >= trace.end) setTime(trace.start);
  play.textContent = 'Pause';
  frame = requestAnimationFrame(animate);
});
byId('restart').addEventListener('click', () => {
  pause();
  setTime(trace.start);
});
scrub.addEventListener('input', () => {
  pause();
  setTime(Number(scrub.value));
});
odom.addEventListener('change', render);
follow.addEventListener('click', () => {
  follow.setAttribute('aria-pressed', String(follow.getAttribute('aria-pressed') !== 'true'));
  render();
});
byId('fit').addEventListener('click', () => {
  follow.setAttribute('aria-pressed', 'false');
  render();
});
new ResizeObserver(updatePlots).observe(document.querySelector('.dashboard'));
if (liveId) {
  openLive(liveId, (csv, {generation, initial_pose: initial, geometry: dimensions}) => {
    if (!csv) {
      trace = undefined;
      charts = [];
      byId('readouts').replaceChildren();
      byId('plots').replaceChildren();
      const geometry = {radius: dimensions.wheel_radius_m, track: dimensions.track_width_m};
      const initialScene = createScene(scene, {x_m: [initial.x_m], y_m: [initial.y_m]}, geometry);
      initialScene({x: initial.x_m, y: initial.y_m, yaw: initial.heading_rad}, false, false);
      follow.disabled = byId('fit').disabled = odom.disabled = true;
      byId('scene-note').textContent = `Schematic axle · Track ${geometry.track.toFixed(3)} m · Wheel radius ${geometry.radius.toFixed(3)} m`;
      byId('sample-time').textContent = 'Awaiting first sample';
      return;
    }
    const next = parseTrace(csv);
    if (!trace || trace.generation !== generation) {
      setTrace(next, 'Live session');
    } else {
      trace = next;
      drawScene = createScene(scene, next.data, next.geometry);
      lastSample = -1;
    }
    trace.generation = generation;
    time = next.end;
    updatePlots();
  });
} else if (job && /^[0-9a-f]{32}$/.test(job)) {
  load(async () => {
    const response = await fetch(`/jobs/${job}/recording.csv`);
    if (!response.ok) throw new Error('Recording unavailable. Run a scenario or open a local CSV.');
    return response.text();
  }, 'Scenario recording');
} else {
  loadDemo();
}
