import { COMPANY_ID, MAGIC, parseScaleFrame, MeasurementTracker } from './protocol.js';
import { scaleFramesFromPklg } from './pklg.js';
import { STRINGS, pickLanguage } from './i18n.js';

// Web Bluetooth only exists over https, but a GitHub Pages custom domain also answers over http.
if (location.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(location.hostname)) {
  location.replace(`https://${location.host}${location.pathname}${location.search}${location.hash}`);
}

const HISTORY_KEY = 'ble-scale:history';
const DEVICE_KEY = 'ble-scale:device';
const LANGUAGE_KEY = 'ble-scale:language';
const THEME_KEY = 'ble-scale:theme'; // also read by the inline script in index.html
const HISTORY_MAX = 100;
const LOG_MAX = 60;
const EXPORT_MAX = 20000;
const MIN_WEIGH_COUNTS = 6; // about 3 s on the scale (the counter ticks every ~0.5 s): shorter is just a touch
const REPLAY_SPEED = 4;
const REPLAY_MAX_GAP_MS = 2000;
const RSSI_UNAVAILABLE = 127;

const SCALE_FILTER = { manufacturerData: [{ companyIdentifier: COMPANY_ID, dataPrefix: new Uint8Array(MAGIC) }] };

const $ = (id) => document.getElementById(id);
const ui = {
  reading: $('reading'), weight: $('weight'), state: $('state'), mac: $('mac'), rssi: $('rssi'),
  frames: $('frames'), listen: $('listen'), stop: $('stop'), replayFile: $('replay-file'),
  message: $('message'), history: $('history'), historyEmpty: $('history-empty'),
  clearHistory: $('clear-history'), log: $('log'), downloadLog: $('download-log'),
};

// localStorage may be missing (private window, blocked site data): the app still works.
function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* not persistent */ }
}

let language = pickLanguage(load(LANGUAGE_KEY, null), navigator.languages ?? [navigator.language ?? 'en']);
let kg;
let when;
let tracker = new MeasurementTracker();
let frameCount = 0;
let logLines = [];
let exportRows = []; // every frame of the session, for the CSV download
let source = 'watch'; // how frames arrive: watch, scan or replay
let weighStartCounter = null; // counter when a weight appeared, until a final frame or 0 kg
let stopCurrent = null; // stops the listening or replay in progress
let onMeasurement = saveMeasurement;
// What is on screen, kept as keys and raw values so a language change can redraw it.
let currentWeight = null;
let stateKey = 'notListening';
let lastMessage = null;

const formatKg = (value) => kg.format(value);

function t(key, params = {}) {
  const value = STRINGS[language][key];
  return typeof value === 'function' ? value(params, formatKg) : value;
}

function say(key, params, isError = false) {
  lastMessage = { key, params, isError };
  renderMessage();
}

function renderMessage() {
  ui.message.textContent = lastMessage ? t(lastMessage.key, lastMessage.params) : '';
  ui.message.classList.toggle('error', Boolean(lastMessage?.isError));
}

function setReadingState(state, key) {
  ui.reading.dataset.state = state;
  stateKey = key;
  ui.state.textContent = t(key);
}

function renderWeight() {
  ui.weight.textContent = currentWeight === null ? t('weightPlaceholder') : kg.format(currentWeight);
}

function applyLanguage(next) {
  language = next;
  kg = new Intl.NumberFormat(language, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  when = new Intl.DateTimeFormat(language, { dateStyle: 'short', timeStyle: 'short' });
  document.documentElement.lang = language;
  document.title = t('title');
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll('[data-i18n-html]')) el.innerHTML = t(el.dataset.i18nHtml);
  for (const el of document.querySelectorAll('[data-i18n-label]')) el.setAttribute('aria-label', t(el.dataset.i18nLabel));
  for (const button of document.querySelectorAll('[data-lang]')) button.setAttribute('aria-pressed', String(button.dataset.lang === language));
  ui.state.textContent = t(stateKey);
  renderWeight();
  renderHistory();
  renderMessage();
}

function applyTheme(choice) {
  if (choice === 'light' || choice === 'dark') document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const button of document.querySelectorAll('[data-theme-choice]')) {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === choice));
  }
}

function setActive(active) {
  ui.listen.hidden = active;
  ui.stop.hidden = !active;
  if (!active) setReadingState('off', 'notListening');
}

function resetReading() {
  tracker = new MeasurementTracker();
  frameCount = 0;
  logLines = [];
  exportRows = [];
  weighStartCounter = null;
  currentWeight = null;
  renderWeight();
  ui.mac.textContent = ui.rssi.textContent = '—';
  ui.frames.textContent = '0';
  ui.log.textContent = '';
}

function handleFrame(frame, rssi) {
  frameCount += 1;
  ui.frames.textContent = String(frameCount);
  ui.mac.textContent = frame.mac;
  if (rssi != null && rssi !== RSSI_UNAVAILABLE) ui.rssi.textContent = `${rssi} dBm`;
  currentWeight = frame.weightKg;
  renderWeight();
  if (frame.final) setReadingState('final', 'final');
  else if (frame.weightKg > 0) setReadingState('measuring', 'measuring');
  else setReadingState('idle', 'stepOn');

  const status = `0x${frame.state.toString(16).padStart(2, '0')}`;
  logLines.unshift(`${new Date().toLocaleTimeString(language)}  ${frame.hex}  ${kg.format(frame.weightKg)} kg  ${status}`);
  logLines.length = Math.min(logLines.length, LOG_MAX);
  ui.log.textContent = logLines.join('\n');
  if (exportRows.length < EXPORT_MAX) {
    exportRows.push([new Date().toISOString(), source, rssi ?? '', status, frame.counter, frame.weightKg, frame.hex.replaceAll(' ', '')]);
  }

  // A weigh-in that ends without a final frame leaves no measurement: say so instead of staying silent.
  if (frame.final) {
    weighStartCounter = null;
  } else if (frame.weightKg > 0) {
    weighStartCounter ??= frame.counter;
  } else if (weighStartCounter !== null) {
    if (((frame.counter - weighStartCounter) & 0xffff) >= MIN_WEIGH_COUNTS) say('noFinalReading');
    weighStartCounter = null;
  }

  const measurement = tracker.update(frame);
  if (measurement) onMeasurement(measurement);
}

function saveMeasurement(measurement) {
  const history = load(HISTORY_KEY, []);
  history.unshift({ time: Date.now(), weightKg: measurement.weightKg, mac: measurement.mac, state: measurement.state });
  store(HISTORY_KEY, history.slice(0, HISTORY_MAX));
  renderHistory();
  say('measurementSaved', { weight: measurement.weightKg });
}

function renderHistory() {
  const history = load(HISTORY_KEY, []);
  ui.history.replaceChildren(...history.map((m) => {
    const li = document.createElement('li');
    const value = document.createElement('span');
    value.className = 'kg';
    value.textContent = `${kg.format(m.weightKg)} kg`;
    const stamp = document.createElement('time');
    stamp.dateTime = new Date(m.time).toISOString();
    stamp.textContent = when.format(m.time);
    li.append(value, stamp);
    return li;
  }));
  ui.historyEmpty.hidden = history.length > 0;
  ui.clearHistory.hidden = history.length === 0;
}

function onAdvertisement(event) {
  const view = event.manufacturerData?.get(COMPANY_ID);
  if (!view) return;
  const frame = parseScaleFrame(new Uint8Array(view.buffer, view.byteOffset, view.byteLength));
  if (frame) handleFrame(frame, event.rssi);
}

function bluetoothMode() {
  if (!navigator.bluetooth) return 'missing';
  if (window.BluetoothDevice && 'watchAdvertisements' in BluetoothDevice.prototype) return 'watch';
  if (typeof navigator.bluetooth.requestLEScan === 'function') return 'scan';
  return 'no-advertisements';
}

// Reuses the device already allowed, if the browser remembers it; otherwise opens the chooser.
async function pickScale() {
  const savedId = load(DEVICE_KEY, null);
  if (savedId && navigator.bluetooth.getDevices) {
    const known = (await navigator.bluetooth.getDevices()).find((d) => d.id === savedId);
    if (known) return known;
  }
  const device = await navigator.bluetooth.requestDevice({ filters: [SCALE_FILTER], optionalManufacturerData: [COMPANY_ID] });
  store(DEVICE_KEY, device.id);
  return device;
}

async function listen() {
  const mode = bluetoothMode();
  if (mode === 'missing') {
    say('noBluetooth', {}, true);
    return;
  }
  if (mode === 'no-advertisements') {
    say('noAdvertisements', {}, true);
    return;
  }
  stop();
  resetReading();
  onMeasurement = saveMeasurement;
  source = mode;
  try {
    if (mode === 'watch') {
      const device = await pickScale();
      const abort = new AbortController();
      device.addEventListener('advertisementreceived', onAdvertisement);
      try {
        await device.watchAdvertisements({ signal: abort.signal });
      } catch (err) {
        device.removeEventListener('advertisementreceived', onAdvertisement);
        throw err;
      }
      stopCurrent = () => {
        abort.abort();
        device.removeEventListener('advertisementreceived', onAdvertisement);
      };
    } else {
      const scan = await navigator.bluetooth.requestLEScan({ filters: [SCALE_FILTER], keepRepeatedDevices: true });
      navigator.bluetooth.addEventListener('advertisementreceived', onAdvertisement);
      stopCurrent = () => {
        scan.stop();
        navigator.bluetooth.removeEventListener('advertisementreceived', onAdvertisement);
      };
    }
    setActive(true);
    setReadingState('idle', 'waiting');
    say('listening');
  } catch (err) {
    if (err.name === 'NotFoundError' && /cancel/i.test(err.message)) say('noScalePicked');
    else say('cannotListen', { error: err.message }, true);
  }
}

function stop() {
  if (stopCurrent) {
    stopCurrent();
    stopCurrent = null;
  }
  setActive(false);
}

async function replay(file) {
  stop();
  resetReading();
  let frames;
  try {
    frames = scaleFramesFromPklg(await file.arrayBuffer());
  } catch (err) {
    say('unreadableFile', { error: err.message }, true);
    return;
  }
  if (frames.length === 0) {
    say('noFramesInFile', { file: file.name }, true);
    return;
  }
  const finals = [];
  onMeasurement = (m) => finals.push(m.weightKg);
  source = 'replay';
  let timer;
  stopCurrent = () => clearTimeout(timer);
  setActive(true);
  say('replaying', { file: file.name, count: frames.length, speed: REPLAY_SPEED });

  const step = (i) => {
    const frame = parseScaleFrame(frames[i].data);
    if (frame) handleFrame(frame, frames[i].rssi);
    if (i + 1 < frames.length) {
      const gap = ((frames[i + 1].time - frames[i].time) * 1000) / REPLAY_SPEED;
      timer = setTimeout(() => step(i + 1), Math.min(gap, REPLAY_MAX_GAP_MS));
      return;
    }
    stopCurrent = null;
    ui.listen.hidden = false;
    ui.stop.hidden = true;
    if (finals.length) say('endWithFinal', { weights: finals });
    else say('endNoFinal');
  };
  step(0);
}

// The frames of the session as CSV: what the browser really received, to diagnose a weigh-in.
function downloadFrames() {
  if (exportRows.length === 0) {
    say('noFramesYet');
    return;
  }
  const header = 'time,source,rssi,status,counter,weight_kg,frame';
  const csv = `${[header, ...exportRows.map((row) => row.join(','))].join('\n')}\n`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `ble-scale-frames-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

ui.listen.addEventListener('click', listen);
ui.downloadLog.addEventListener('click', downloadFrames);
ui.stop.addEventListener('click', () => {
  stop();
  say('stopped');
});
ui.replayFile.addEventListener('change', () => {
  const [file] = ui.replayFile.files;
  ui.replayFile.value = '';
  if (file) replay(file);
});
ui.clearHistory.addEventListener('click', () => {
  if (!confirm(t('confirmClear'))) return;
  store(HISTORY_KEY, []);
  renderHistory();
});
for (const button of document.querySelectorAll('[data-lang]')) {
  button.addEventListener('click', () => {
    store(LANGUAGE_KEY, button.dataset.lang);
    applyLanguage(button.dataset.lang);
  });
}
for (const button of document.querySelectorAll('[data-theme-choice]')) {
  button.addEventListener('click', () => {
    store(THEME_KEY, button.dataset.themeChoice);
    applyTheme(button.dataset.themeChoice);
  });
}

applyTheme(load(THEME_KEY, 'auto'));
applyLanguage(language);
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => { /* the app works without it too */ });
}
