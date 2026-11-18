import { odometry } from './trace.mjs';

const cyan = '#66e4de';
const amber = '#ffc478';
const muted = '#a5b7ce';
const font = '11px ui-monospace, monospace';

function canvasContext(canvas) {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  const dpr = window.devicePixelRatio || 1;
  const width = Math.round(w * dpr);
  const height = Math.round(h * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.font = font;
  return { ctx, w, h };
}

function path(xs, ys) {
  const line = new Path2D();
  line.moveTo(xs[0], ys[0]);
  for (let i = 1; i < xs.length; i++) line.lineTo(xs[i], ys[i]);
  // A zero-length segment with round caps also represents a single sample.
  if (xs.length === 1) line.lineTo(xs[0], ys[0]);
  return line;
}

function gridStep(value) {
  const base = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 5, 10].find(factor => factor * base >= value) * base;
}

export function createScene(canvas, data, { radius, track }) {
  const halfTrack = track / 2;
  const padding = Math.max(track, radius * 2) + 0.05;
  const truthPath = path(data.x_m, data.y_m);
  const odomPath = odometry.every(key => Object.hasOwn(data, key))
    ? path(data.odom_x_m, data.odom_y_m) : null;

  function getBounds(includeOdom) {
    const bounds = [Infinity, Infinity, -Infinity, -Infinity];
    function extend(xs, ys) {
      for (let i = 0; i < xs.length; i++) {
        bounds[0] = Math.min(bounds[0], xs[i]);
        bounds[1] = Math.min(bounds[1], ys[i]);
        bounds[2] = Math.max(bounds[2], xs[i]);
        bounds[3] = Math.max(bounds[3], ys[i]);
      }
    }
    extend(data.x_m, data.y_m);
    if (includeOdom) extend(data.odom_x_m, data.odom_y_m);
    return bounds;
  }

  const truthBounds = getBounds(false);
  const combinedBounds = odomPath ? getBounds(true) : truthBounds;
  return (pose, showOdom, follow) => {
    const { ctx, w, h } = canvasContext(canvas);
    if (w < 100 || h < 100) return;
    const [xmin, ymin, xmax, ymax] = showOdom ? combinedBounds : truthBounds;
    const scale = follow ? Math.min(w, h) / Math.max(0.65, padding * 1.5) :
      Math.min((w - 60) / (xmax - xmin + padding), (h - 82) / (ymax - ymin + padding));
    const centerX = follow ? pose.x : xmin + (xmax - xmin) / 2;
    const centerY = follow ? pose.y : ymin + (ymax - ymin) / 2;
    const screenX = x => w / 2 + (x - centerX) * scale;
    const screenY = y => h / 2 + 13 - (y - centerY) * scale;
    const step = gridStep(58 / scale);
    if (!Number.isFinite(step) || step <= 0) return;
    const label = value => (Math.abs(value) < step / 10 ? 0 : value).toFixed(Math.max(0, -Math.floor(Math.log10(step))));
    const segment = (x, y, x2, y2) => {
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    };
    ctx.fillStyle = muted;
    ctx.lineWidth = 1;
    const leftLine = Math.ceil((centerX - w / (2 * scale)) / step);
    for (let i = 0; i <= w / (step * scale) + 1; i++) {
      const x = (leftLine + i) * step;
      const px = screenX(x);
      ctx.strokeStyle = Math.abs(x) < step / 10 ? '#47647e' : '#203249';
      segment(px, 0, px, h);
      if (px > 44 && px < w - 63) ctx.fillText(label(x), px + 4, h - 8);
    }
    const topLine = Math.floor((centerY + (h / 2 + 13) / scale) / step);
    for (let i = 0; i <= h / (step * scale) + 1; i++) {
      const y = (topLine - i) * step;
      const py = screenY(y);
      ctx.strokeStyle = Math.abs(y) < step / 10 ? '#47647e' : '#203249';
      segment(0, py, w, py);
      if (py > 36 && py < h - 24) ctx.fillText(label(y), 7, py - 4);
    }
    ctx.fillText('y (m) ↑', 8, h - 25);
    ctx.textAlign = 'right';
    ctx.fillText('x (m) →', w - 10, h - 8);
    ctx.textAlign = 'left';
    const bar = step * scale;
    ctx.fillStyle = '#c5daeb';
    ctx.fillRect(w - 16 - bar, 25, bar, 2);
    ctx.fillRect(w - 16 - bar, 22, 1, 8);
    ctx.fillRect(w - 16, 22, 1, 8);
    ctx.textAlign = 'right';
    ctx.fillText(`${label(step)} m`, w - 16, 17);

    ctx.save();
    // Positive world y points up on the screen, so positive yaw stays CCW.
    ctx.translate(screenX(0), screenY(0));
    ctx.scale(scale, -scale);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.strokeStyle = cyan;
    ctx.lineWidth = 3.8 / scale;
    ctx.stroke(truthPath);
    if (showOdom && odomPath) {
      ctx.strokeStyle = amber;
      ctx.lineWidth = 1.7 / scale;
      ctx.setLineDash([6 / scale, 5 / scale]);
      ctx.stroke(odomPath);
      ctx.setLineDash([]);
    }
    ctx.translate(pose.x, pose.y);
    ctx.rotate(pose.yaw);
    ctx.strokeStyle = '#e7fbff';
    ctx.lineWidth = 2 / scale;
    segment(0, -halfTrack, 0, halfTrack);
    ctx.strokeStyle = cyan;
    ctx.lineWidth = 7 / scale;
    for (const y of [-halfTrack, halfTrack]) segment(-radius, y, radius, y);
    ctx.strokeStyle = '#e7fbff';
    ctx.lineWidth = 2.5 / scale;
    segment(0, 0, radius * 2.1, 0);
    segment(radius * 2.1, 0, radius * 1.5, radius * 0.48);
    segment(radius * 2.1, 0, radius * 1.5, -radius * 0.48);
    ctx.fillStyle = '#e7fbff';
    ctx.beginPath();
    ctx.arc(0, 0, 3 / scale, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    ctx.textAlign = 'left';
  };
}

const margin = 54;
const right = 9;
export function plotFraction(x, width) {
  return Math.max(0, Math.min(1, (x - margin) / (width - margin - right)));
}

export function moveCursor(canvas, cursor, fraction) {
  cursor.style.left = `${margin + fraction * (canvas.clientWidth - margin - right)}px`;
}

export function drawPlot(canvas, trace, series) {
  const { ctx, w, h } = canvasContext(canvas);
  const { data, start, end } = trace;
  if (w <= margin + right) return;
  const top = 5;
  const bottom = h - 18;
  const width = w - margin - right;
  let min = 0;
  let max = 0;
  for (const signal of series) {
    for (const raw of data[signal.key]) {
      const value = raw * signal.scale;
      min = Math.min(min, value);
      max = Math.max(max, value);
    }
  }
  if (min === max) max = 1;
  const y = value => bottom - (value - min) / (max - min) * (bottom - top);
  ctx.fillStyle = muted;
  ctx.strokeStyle = '#283a50';
  ctx.textAlign = 'right';
  ctx.font = '10px ui-monospace, monospace';
  for (const value of [min, (min + max) / 2, max]) {
    const py = y(value);
    ctx.beginPath();
    ctx.moveTo(margin, py);
    ctx.lineTo(w - right, py);
    ctx.stroke();
    ctx.fillText(Number(value.toPrecision(3)).toString(), margin - 5, Math.max(9, py + 3));
  }
  for (const fraction of [0, 0.5, 1]) {
    const px = margin + width * fraction;
    ctx.textAlign = fraction === 0 ? 'left' : fraction === 1 ? 'right' : 'center';
    ctx.fillText((start + (end - start) * fraction).toFixed(3), px, h - 4);
    ctx.beginPath();
    ctx.moveTo(px, top);
    ctx.lineTo(px, bottom);
    ctx.stroke();
  }
  for (const signal of series) {
    ctx.strokeStyle = signal.color;
    ctx.fillStyle = signal.color;
    ctx.setLineDash(signal.dash ? [4, 3] : []);
    ctx.lineWidth = 1.25;
    ctx.beginPath();
    for (let i = 0; i < data.time_s.length; i++) {
      const px = margin + width * (end === start ? 0 : (data.time_s[i] - start) / (end - start));
      const py = y(data[signal.key][i] * signal.scale);
      if (i === 0) ctx.moveTo(px, py);
      else {
        if (signal.step) ctx.lineTo(px, y(data[signal.key][i - 1] * signal.scale));
        ctx.lineTo(px, py);
      }
      if (data.time_s.length === 1) ctx.fillRect(px - 2, py - 2, 4, 4);
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);
}
