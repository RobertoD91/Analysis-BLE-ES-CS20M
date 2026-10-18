import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseScaleFrame, MeasurementTracker } from '../webapp/protocol.js';
import { scaleFramesFromPklg } from '../webapp/pklg.js';

const SAMPLE_MAC = 'C0:FF:EE:12:34:56';
const fromHex = (s) => Uint8Array.from(s.split(' '), (b) => parseInt(b, 16));
const sample = (name) => scaleFramesFromPklg(readFileSync(new URL(`../samples/${name}`, import.meta.url)));

function decodeSample(name) {
  const frames = sample(name).map((f) => parseScaleFrame(f.data)).filter(Boolean);
  const tracker = new MeasurementTracker();
  const measurements = frames.map((f) => tracker.update(f)).filter(Boolean);
  return { frames, measurements };
}

test('decodes a measuring frame', () => {
  const frame = parseScaleFrame(fromHex('aa bb c0 ff ee 12 34 56 8e 40 d3 6a 12 34 56 02 00 6e 1c 4c 09 03 7d 06'));
  assert.equal(frame.mac, SAMPLE_MAC);
  assert.equal(frame.clock, 0x6ad3408e);
  assert.equal(frame.token, '123456');
  assert.equal(frame.state, 0x02);
  assert.equal(frame.final, false);
  assert.equal(frame.weightKg, 72.78);
  assert.equal(frame.counter, 0x067d);
});

test('ignores frames from other devices and truncated ones', () => {
  assert.equal(parseScaleFrame(fromHex('ab bb c0 ff ee 12 34 56 8e 40 d3 6a 12 34 56 02 00 6e 1c 4c 09 03 7d 06')), null);
  assert.equal(parseScaleFrame(fromHex('aa bb c0 ff ee 12')), null);
});

test('complete weighing: a single final measurement of 75.00 kg', () => {
  const { frames, measurements } = decodeSample('complete-weighing.pklg');
  assert.equal(frames.length, 78);
  assert.ok(frames.every((f) => f.mac === SAMPLE_MAC));
  assert.deepEqual(new Set(frames.filter((f) => f.final).map((f) => f.state)), new Set([0x23]));
  assert.deepEqual(measurements, [{ mac: SAMPLE_MAC, weightKg: 75, state: 0x23 }]);
});

test('interrupted weighing: settling readings only, no final measurement', () => {
  const { frames, measurements } = decodeSample('interrupted-weighing.pklg');
  assert.equal(frames.length, 93);
  assert.equal(Math.max(...frames.map((f) => f.weightKg)), 75.35);
  assert.deepEqual(measurements, []);
});
