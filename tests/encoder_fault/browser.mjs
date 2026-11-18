// Exercise the setup and live fault UI with a local Chromium CDP endpoint.
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { writeFile } from 'node:fs/promises';

const [base = 'http://127.0.0.1:8884', cdp = 'http://127.0.0.1:9439', screenshot] = process.argv.slice(2);
const tabs = await (await fetch(cdp + '/json/list')).json();
const ws = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
await once(ws, 'open');
const pending = new Map();
const errors = [];
let sequence = 0;
ws.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  pending.get(message.id)?.(message);
  pending.delete(message.id);
});
async function send(method, params = {}) {
  const id = ++sequence;
  const reply = await new Promise(resolve => {
    pending.set(id, resolve);
    ws.send(JSON.stringify({id, method, params}));
  });
  assert.ok(!reply.error, JSON.stringify(reply.error));
  return reply.result;
}
async function js(expression) {
  const response = await send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  assert.ok(!response.exceptionDetails, JSON.stringify(response.exceptionDetails));
  return response.result.value;
}
async function wait(expression) {
  for (let i = 0; i < 450; i++) {
    if (await js(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out: ${expression}. ${await js('document.querySelector("#error")?.textContent')}`);
}
const click = id => js(`document.getElementById('${id}').click()`);
const text = id => `document.getElementById('${id}')?.textContent`;
const target = profile => js(`(() => {
  const select = document.getElementById('target');
  select.value = '${profile}';
  select.dispatchEvent(new Event('change'));
})()`);
try {
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {mobile: false, width: 1440, height: 1180, deviceScaleFactor: 1});
  await send('Page.navigate', {url: base + '/setup/'});
  await wait('document.querySelectorAll("#wiring-rows tr").length === 8');
  await target('pwm-signal-pll168-v1');
  assert.equal(await js('getComputedStyle(document.querySelector("#encoder-faults").closest("section")).display'), 'none');
  assert.equal(await js('document.querySelector("#live").hidden'), true);
  await target('stm32f407vgt6');
  await click('example');
  await js('document.querySelector("#encoder-fault-evidence").checked=true; document.querySelector("#duration").value=12');
  await click('live');
  await wait(`${text('source')} === 'Ready'`);
  assert.equal(await js('getComputedStyle(document.querySelector("#live-faults")).display'), 'flex');
  await click('live-toggle');
  await wait(`parseFloat(${text('live-time')}) >= 0.7`);
  await click('live-toggle');
  await wait(`${text('source')} === 'Paused'`);
  const paused = await js(text('live-time'));
  await js("document.querySelector('#live-fault-channel').value='right.a'");
  await click('live-fault-apply');
  await wait(`${text('live-fault-event')}.startsWith('Pending · right.a stuck at 0')`);
  assert.equal(await js(text('live-time')), paused);
  await click('live-toggle');
  await wait(`${text('live-fault-event')}.startsWith('Applied · right.a stuck at 0 at')`);
  await wait(`parseFloat(${text('live-time')}) >= ${parseFloat(paused) + .3}`);
  assert.match(await js(text('readouts')), /Encoder RIGHT A.*Mask low/);
  if (screenshot) {
    const {data} = await send('Page.captureScreenshot', {format: 'png'});
    await writeFile(screenshot, Buffer.from(data, 'base64'));
  }
  await click('live-fault-clear');
  await wait(`${text('live-fault-event')}.startsWith('Applied · clear right.a at')`);
  await click('live-stop');
  await wait(`${text('source')} === 'Stopped'`);
  await click('live-replay');
  await wait(`${text('viewer-title')} === 'Recorded simulation replay' && !document.querySelector('#scrub').disabled`);
  assert.match(await js(text('readouts')), /Encoder RIGHT A/);
  assert.deepEqual(errors, []);
  console.log('PASS Chromium setup opt-in, passive exclusion, paused fault, resume, clear, and saved replay evidence.');
} finally {
  ws.close();
}
