// Reads Apple PacketLogger (.pklg) captures: extracts the scale frames from the
// LE Advertising Reports, to replay them without the scale.
import { COMPANY_ID } from './protocol.js';

const PKLG_EVENT = 0x01;
const HCI_LE_META = 0x3e;
const LE_ADV_REPORT = 0x02;
const LE_EXT_ADV_REPORT = 0x0d;
const AD_MANUFACTURER = 0xff;

// Record: length (u32 LE) | seconds (u32) | microseconds (u32) | type (u8) | payload
function* pklgRecords(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let off = 0;
  while (off + 4 <= bytes.length) {
    const len = view.getUint32(off, true);
    if (len < 9 || off + 4 + len > bytes.length) return;
    yield {
      time: view.getUint32(off + 4, true) + view.getUint32(off + 8, true) / 1e6,
      type: bytes[off + 12],
      payload: bytes.subarray(off + 13, off + 4 + len),
    };
    off += 4 + len;
  }
}

function* advReports(evt) {
  if (evt.length < 4 || evt[0] !== HCI_LE_META) return;
  const sub = evt[2];
  let off = 4;
  for (let i = 0; i < evt[3] && off < evt.length; i++) {
    if (sub === LE_EXT_ADV_REPORT) {
      const len = evt[off + 23];
      yield { rssi: (evt[off + 13] << 24) >> 24, data: evt.subarray(off + 24, off + 24 + len) };
      off += 24 + len;
    } else if (sub === LE_ADV_REPORT) {
      const len = evt[off + 8];
      yield { rssi: (evt[off + 9 + len] << 24) >> 24, data: evt.subarray(off + 9, off + 9 + len) };
      off += 10 + len;
    } else {
      return;
    }
  }
}

function* adStructures(data) {
  let i = 0;
  while (i < data.length && data[i] && i + 1 + data[i] <= data.length) {
    yield { type: data[i + 1], value: data.subarray(i + 2, i + 1 + data[i]) };
    i += 1 + data[i];
  }
}

// Returns [{time, rssi, data}] with data = manufacturer data without the company ID.
export function scaleFramesFromPklg(buffer) {
  const bytes = buffer instanceof Uint8Array ? buffer : new Uint8Array(buffer);
  const frames = [];
  for (const { time, type, payload } of pklgRecords(bytes)) {
    if (type !== PKLG_EVENT) continue;
    for (const { rssi, data } of advReports(payload)) {
      for (const { type: adType, value } of adStructures(data)) {
        if (adType === AD_MANUFACTURER && value.length > 2 && (value[0] | (value[1] << 8)) === COMPANY_ID) {
          frames.push({ time, rssi, data: value.subarray(2) });
        }
      }
    }
  }
  return frames;
}
