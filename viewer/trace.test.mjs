import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { headingErrorKey, parseTrace, poseAt, positionErrorKey, sampleAt } from './trace.mjs';

const header = 'time_s,x_m,y_m,heading_rad';

test('preserves timestamps, interpolates irregular intervals, and holds telemetry at the previous sample', () => {
  const { data, start, end } = parseTrace(`${header},wl_rad_s\n1,0,0,0,4\n2,2,1,0,5\n5,5,4,0,8\n`);
  assert.deepEqual([start, end], [1, 5]);
  assert.equal(sampleAt(data.time_s, 0), 0);
  assert.equal(sampleAt(data.time_s, 4), 1);
  assert.equal(sampleAt(data.time_s, 5), 2);
  assert.equal(data.wl_rad_s[sampleAt(data.time_s, 4)], 5);
  assert.deepEqual(poseAt(data, 4), { x: 4, y: 3, yaw: 0 });
});

test('uses the shortest angular arc across the wrap boundary', () => {
  const { data } = parseTrace(`${header},odom_x_m,odom_y_m,odom_heading_rad\n0,1,3,3.13,1,4,-3.13\n1,1,3,-3.13,1,4,3.13`);
  assert.ok(Math.abs(poseAt(data, 0.5).yaw - Math.PI) < 1e-12);
  assert.equal(poseAt(data, 1).yaw, -3.13);
  assert.equal(data[positionErrorKey][0], 1);
  assert.ok(Math.abs(data[headingErrorKey][0] - (2 * Math.PI - 6.26)) < 1e-12);
});

test('accepts an optional-column subset, quoted numbers, BOM, and CRLF', () => {
  const { data } = parseTrace(`\uFEFF${header},odom_x_m\r\n"1","0",0,0,0\r\n`);
  assert.equal(data.odom_x_m[0], 0);
  assert.equal(data[positionErrorKey], undefined);
  assert.equal(data.wr_rad_s, undefined);
});

test('rejects malformed schema, nonfinite values, invalid pins, and unordered times with useful errors', () => {
  for (const [csv, error] of [
    ['time_s,x_m\n0,1', /Missing required columns: y_m, heading_rad/],
    [`${header},time_s\n0,0,0,0,0`, /duplicate/],
    [header, /no samples/],
    [`${header}\n0,0,0`, /Line 2: expected 4 cells/],
    [`${header}\n0,0,0,1e500`, /Line 2, heading_rad: expected a finite number/],
    [`${header}\n0,0,,0`, /Line 2, y_m/],
    [`${header}\n1,0,0,0\n0,0,0,0`, /Line 3: time_s must be strictly increasing/],
    [`${header}\n1,0,0,0\n1,0,0,0`, /strictly increasing/],
    [`${header},dir_l\n0,0,0,0,0`, /expected -1/],
    [`${header},duty_l\n0,0,0,0,2`, /duty fraction/],
  ]) assert.throws(() => parseTrace(csv), error);
});

test('reproduces the first, middle and last exported poses', () => {
  const csv = readFileSync(new URL('../tests/robot/out/main.csv', import.meta.url), 'utf8');
  const { data } = parseTrace(csv);
  const lines = csv.trimEnd().split('\n').slice(1);
  for (const index of [0, Math.floor(lines.length / 2), lines.length - 1]) {
    const [time, x, y, yaw] = lines[index].split(',').map(Number);
    assert.equal(sampleAt(data.time_s, time), index);
    assert.deepEqual(poseAt(data, time), { x, y, yaw });
  }
});

test('uses constant recorded geometry and preserves the old default', () => {
  const fallback = parseTrace(`${header}\n0,0,0,0`);
  const custom = `${header},wheel_radius_m,track_width_m\n0,0,0,0,0.06,0.4`;
  assert.deepEqual(fallback.geometry, { radius: 0.05, track: 0.30 });
  assert.deepEqual(parseTrace(custom).geometry, { radius: 0.06, track: 0.4 });
  assert.throws(() => parseTrace(`${custom}\n1,0,0,0,0.07,0.4`), /wheel_radius_m must be positive and constant/);
});
