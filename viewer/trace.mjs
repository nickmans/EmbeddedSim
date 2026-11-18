export const required = ['time_s', 'x_m', 'y_m', 'heading_rad'];
export const odometry = ['odom_x_m', 'odom_y_m', 'odom_heading_rad'];
export const positionErrorKey = Symbol('position error');
export const headingErrorKey = Symbol('heading error');
const number = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i;

// The exporter writes one line per sample. Accept quoted scalar cells as well.
function cells(line, row) {
  return line.split(',').map(cell => {
    const value = cell.trim();
    if (!value.includes('"')) return value;
    if (/^"[^"]*"$/.test(value)) return value.slice(1, -1).trim();
    throw new Error(`Line ${row}: expected a plain or quoted scalar CSV cell.`);
  });
}

export function parseTrace(csv) {
  const lines = csv.replace(/^\uFEFF/, '').trimEnd().split(/\r?\n/);
  const headers = cells(lines[0], 1);
  if (headers.includes('') || new Set(headers).size !== headers.length) {
    throw new Error('The header contains an empty or duplicate column name.');
  }
  const missing = required.filter(key => !headers.includes(key));
  if (missing.length) throw new Error(`Missing required columns: ${missing.join(', ')}. Select a robot replay CSV such as main.csv.`);
  if (lines.length < 2) throw new Error('The recording contains no samples.');
  const data = Object.fromEntries(headers.map(key => [key, new Float64Array(lines.length - 1)]));
  for (let i = 1; i < lines.length; i++) {
    const values = cells(lines[i], i + 1);
    if (values.length !== headers.length) {
      throw new Error(`Line ${i + 1}: expected ${headers.length} cells, found ${values.length}.`);
    }
    for (const [j, key] of headers.entries()) {
      const value = Number(values[j]);
      if (!number.test(values[j]) || !Number.isFinite(value)) {
        throw new Error(`Line ${i + 1}, ${key}: expected a finite number.`);
      }
      if ((key === 'dir_l' || key === 'dir_r') && value !== -1 && value !== 1) {
        throw new Error(`Line ${i + 1}, ${key}: expected -1 (GPIO low) or +1 (GPIO high).`);
      }
      if ((key === 'duty_l' || key === 'duty_r') && (value < 0 || value > 1)) {
        throw new Error(`Line ${i + 1}, ${key}: expected a duty fraction between 0 and 1.`);
      }
      data[key][i - 1] = value;
    }
    if (i > 1 && data.time_s[i - 1] <= data.time_s[i - 2]) {
      throw new Error(`Line ${i + 1}: time_s must be strictly increasing.`);
    }
  }
  const start = data.time_s[0];
  const end = data.time_s.at(-1);
  if (!Number.isFinite(end - start)) throw new Error('The timestamp range is too large.');
  if (odometry.every(key => Object.hasOwn(data, key))) {
    data[positionErrorKey] = Float64Array.from(data.x_m, (x, i) =>
      Math.hypot(x - data.odom_x_m[i], data.y_m[i] - data.odom_y_m[i]));
    data[headingErrorKey] = Float64Array.from(data.heading_rad, (yaw, i) =>
      wrap(data.odom_heading_rad[i] - yaw));
  }
  return { data, start, end };
}

export function wrap(angle) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

export function sampleAt(time, t) {
  let lo = 0;
  let hi = time.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (time[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export function poseAt(data, t, i = sampleAt(data.time_s, t)) {
  const j = Math.min(i + 1, data.time_s.length - 1);
  const fraction = j === i ? 0 : Math.max(0, Math.min(1, (t - data.time_s[i]) / (data.time_s[j] - data.time_s[i])));
  const x = data.x_m[i];
  const y = data.y_m[i];
  const yaw = data.heading_rad[i];
  return {
    x: x + (data.x_m[j] - x) * fraction,
    y: y + (data.y_m[j] - y) * fraction,
    yaw: yaw + wrap(data.heading_rad[j] - yaw) * fraction,
  };
}
