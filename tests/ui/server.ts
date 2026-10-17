// Starts the real server from the repository on a fresh data folder, with a folder of generated images to open.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { crc32, deflateSync } from 'node:zlib';
import { PORT } from './playwright.config';

const ROOT = resolve(import.meta.dirname, '../..');
const PYTHON = join(ROOT, '.venv', ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']));
const START_SECONDS = 30;
// Every image is from today, except those in trips/, which are from 2020, so the date filter splits them.
const TODAY = { 'red.png': [220, 30, 30], 'green.png': [30, 160, 60], 'blue.png': [30, 60, 220], 'yellow.bmp': [240, 210, 30] };
const OLD = { 'trips/beach.png': [230, 200, 140], 'trips/harbour.png': [40, 90, 120] };
const OLD_DATE = new Date('2020-06-15T12:00:00Z');
export const FIXTURE = { images: Object.keys(TODAY).length + Object.keys(OLD).length, today: Object.keys(TODAY).length, trips: Object.keys(OLD).length };

/** A plain square PNG of one colour. */
function png(rgb: number[], size = 48) {
  const chunk = (kind: string, data: Buffer) => {
    const body = Buffer.concat([Buffer.from(kind, 'latin1'), data]);
    const framed = Buffer.alloc(body.length + 8);
    framed.writeUInt32BE(data.length, 0); body.copy(framed, 4); framed.writeUInt32BE(crc32(body), body.length + 4);
    return framed;
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0); header.writeUInt32BE(size, 4); header.set([8, 2, 0, 0, 0], 8);
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({ length: size }, () => rgb).flat())]);
  const pixels = deflateSync(Buffer.concat(Array.from({ length: size }, () => row)));
  return Buffer.concat([Buffer.from('\x89PNG\r\n\x1a\n', 'latin1'), chunk('IHDR', header), chunk('IDAT', pixels), chunk('IEND', Buffer.alloc(0))]);
}

/** A plain square 24-bit BMP of one colour, so the folder has a second file type. */
function bmp([r, g, b]: number[], size = 48) {
  const stride = Math.ceil(size * 3 / 4) * 4;
  const file = Buffer.alloc(54 + stride * size);
  file.write('BM', 0, 'latin1'); file.writeUInt32LE(file.length, 2); file.writeUInt32LE(54, 10);
  file.writeUInt32LE(40, 14); file.writeInt32LE(size, 18); file.writeInt32LE(size, 22); file.writeUInt16LE(1, 26); file.writeUInt16LE(24, 28);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) file.set([b, g, r], 54 + y * stride + x * 3);
  return file;
}

function writeImages(folder: string, images: Record<string, number[]>, date?: Date) {
  for (const [name, rgb] of Object.entries(images)) {
    const path = join(folder, name);
    mkdirSync(join(path, '..'), { recursive: true });
    writeFileSync(path, name.endsWith('.bmp') ? bmp(rgb) : png(rgb));
    if (date) utimesSync(path, date, date);
  }
}

async function started(server: ReturnType<typeof spawn>, log: () => string) {
  const deadline = Date.now() + START_SECONDS * 1000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) throw new Error(`The server exited with status ${server.exitCode}:\n${log()}`);
    try { if ((await fetch(`http://127.0.0.1:${PORT}/api/status`)).ok) return; } catch { /* Not listening yet. */ }
    await new Promise(done => setTimeout(done, 200));
  }
  throw new Error(`The server did not answer within ${START_SECONDS} seconds:\n${log()}`);
}

export default async function setup() {
  const scratch = mkdtempSync(join(tmpdir(), 'orchard-ui-'));
  const photos = join(scratch, 'photos');
  writeImages(photos, TODAY);
  writeImages(photos, OLD, OLD_DATE);
  process.env.ORCHARD_UI_PHOTOS = photos;
  // HF_HUB_OFFLINE keeps the search model from ever downloading.
  const server = spawn(PYTHON, ['-m', 'server.api', '--port', String(PORT), '--data-dir', join(scratch, 'data'), '--no-watch'],
    { cwd: ROOT, env: { ...process.env, HF_HUB_OFFLINE: '1' }, stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  server.stdout!.on('data', data => { output += data; });
  server.stderr!.on('data', data => { output += data; });
  server.on('error', error => { output += `${error.message}. Is .venv set up? Run ./orchard once, or see docs/development.md.`; });
  try {
    await started(server, () => output);
  } catch (error) {
    server.kill();
    rmSync(scratch, { recursive: true, force: true });
    throw error;
  }
  return async () => {
    server.kill();
    await new Promise(done => server.exitCode !== null ? done(null) : server.once('exit', done));
    rmSync(scratch, { recursive: true, force: true });
  };
}
