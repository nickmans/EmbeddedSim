// Local Chromium, driven via CDP with the Node 24 standard library.
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {once} from 'node:events';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import readline from 'node:readline';

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const directory = await mkdtemp(join(tmpdir(), 'embedded-perf-'));
const chrome = spawn(process.env.CHROMIUM || 'chromium', [
  '--headless', ...(process.env.CHROMIUM_NO_SANDBOX === '1' ? ['--no-sandbox'] : []),
  '--disable-dev-shm-usage', '--disable-background-networking', '--no-first-run',
  '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
  '--window-size=1440,1050', `--user-data-dir=${directory}`, 'about:blank',
], {stdio: 'ignore'});
let ws;
try {
  let port;
  for (let i = 0; i < 100 && !port; i++) {
    try { port = (await readFile(join(directory, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; }
    catch { await sleep(50); }
  }
  if (!port) throw new Error('Could not start Chromium.');
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
  await once(ws, 'open');
  const pending = new Map();
  let sequence = 0;
  ws.addEventListener('message', event => {
    const reply = JSON.parse(event.data);
    const callbacks = pending.get(reply.id);
    if (!callbacks) return;
    pending.delete(reply.id);
    if (reply.error) callbacks.reject(new Error(reply.error.message));
    else callbacks.resolve(reply.result);
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, {resolve, reject});
    ws.send(JSON.stringify({id, method, params}));
  });
  const evalJS = async expression => {
    const reply = await send('Runtime.evaluate', {expression, returnByValue: true});
    if (reply.exceptionDetails) throw new Error(reply.exceptionDetails.text);
    return reply.result.value;
  };
  await send('Performance.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', {source: 'performance.setResourceTimingBufferSize(2000)'});
  const metrics = async () => Object.fromEntries((await send('Performance.getMetrics')).metrics.map(x => [x.name, x.value]));
  let initial;
  for await (const input of readline.createInterface({input: process.stdin})) {
    const command = JSON.parse(input);
    if (command.url) {
      await send('Page.navigate', {url: command.url});
      let ready = false;
      for (let i = 0; i < 300 && !ready; i++) {
        ready = await evalJS('document.querySelector("#source")?.textContent === "Ready"');
        if (!ready) await sleep(50);
      }
      if (!ready) throw new Error('Live viewer did not reach Ready.');
      await evalJS('performance.clearResourceTimings()');
      initial = await metrics();
      console.log(JSON.stringify({ready: true}));
    } else {
      for (let i = 0; i < 80; i++) {
        if (await evalJS('document.querySelector("#source")?.textContent === "Completed"')) break;
        if (i === 79) throw new Error('Browser did not display completion.');
        await sleep(50);
      }
      const result = await metrics();
      const timings = await evalJS(`performance.getEntriesByType('resource')
        .filter(entry => new URL(entry.name).pathname.startsWith('/api/live/'))
        .map(entry => [entry.encodedBodySize, entry.duration])`);
      for (const key of Object.keys(result)) result[key] -= initial[key] || 0;
      console.log(JSON.stringify({task_s: result.TaskDuration, script_s: result.ScriptDuration,
        layout_s: result.LayoutDuration, style_s: result.RecalcStyleDuration,
        telemetry_fetches: timings.length, telemetry_bytes: timings.reduce((n, row) => n + row[0], 0),
        telemetry_fetch_ms: timings.reduce((n, row) => n + row[1], 0)}));
    }
  }
} finally {
  ws?.close();
  chrome.kill('SIGTERM');
  if (chrome.exitCode === null) await once(chrome, 'exit');
  await rm(directory, {recursive: true, force: true, maxRetries: 3});
}
