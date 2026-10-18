// Frames of the broadcast scale (see docs/protocol.md).
// The bytes are the manufacturer data AFTER the 0xFFFF company ID, i.e. what
// Web Bluetooth returns in event.manufacturerData.get(0xFFFF).

export const COMPANY_ID = 0xffff;
export const MAGIC = [0xaa, 0xbb];
const FRAME_LENGTH = 24;
const STATE_FINAL_BIT = 0x01; // state 0x02 measuring, 0x23 final

const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(' ');

export function parseScaleFrame(bytes) {
  if (bytes.length < FRAME_LENGTH || bytes[0] !== MAGIC[0] || bytes[1] !== MAGIC[1]) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const state = bytes[15];
  return {
    mac: hex(bytes.subarray(2, 8)).toUpperCase().replaceAll(' ', ':'),
    clock: view.getUint32(8, true),
    token: hex(bytes.subarray(12, 15)).replaceAll(' ', ''),
    state,
    final: (state & STATE_FINAL_BIT) !== 0,
    weightKg: view.getUint16(17, true) / 100,
    counter: view.getUint16(22, true),
    hex: hex(bytes.subarray(0, FRAME_LENGTH)),
  };
}

// The scale repeats the final frame for many seconds with the counter frozen:
// report a new measurement only the first time it shows up.
export class MeasurementTracker {
  #lastKey = null;

  update(frame) {
    if (!frame.final || frame.weightKg <= 0) return null;
    const key = `${frame.mac}/${frame.counter}/${frame.weightKg}`;
    if (key === this.#lastKey) return null;
    this.#lastKey = key;
    return { mac: frame.mac, weightKg: frame.weightKg, state: frame.state };
  }
}
