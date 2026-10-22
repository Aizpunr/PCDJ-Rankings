// Worker tests for the duplicate path. Run: node --test tests/js/test_worker.mjs
//
// Every log stays on record. A byte-identical resend used to return the first
// submission's id and store nothing at all, so a second sender left no trace.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

const worker = (await import('../../submit-worker/src/index.js')).default;

// A minimal stand-in for the KV namespace: get/put/list over a Map.
class FakeKV {
  constructor() { this.store = new Map(); }
  async get(key) { const v = this.store.get(key); return v === undefined ? null : v; }
  async put(key, value) { this.store.set(key, value); }
  async delete(key) { this.store.delete(key); }
  subs() {
    return [...this.store.entries()]
      .filter(([k]) => k.startsWith('sub:'))
      .map(([, v]) => JSON.parse(v));
  }
}

const ORIGIN = 'https://aizpunr.github.io';
const HEADER = '[Info   :COTDTracker] Doing eliminations with leaderboard:';
const LOG = [
  HEADER, '[Info   :COTDTracker] Player A: Time: 40.0', '[Info   :COTDTracker] Player B: Time: 41.0',
  HEADER, '[Info   :COTDTracker] Player A: Time: 39.0', '[Info   :COTDTracker] Player B: Time: 41.0',
  '[Info   :COTDTracker] Eliminating on time: B',
].join('\r\n');

let env;
beforeEach(() => {
  env = { SUBMISSIONS: new FakeKV(), TURNSTILE_SECRET: 'test-secret', ALLOWED_ORIGINS: ORIGIN };
  // Turnstile is the only outbound call in this path.
  globalThis.fetch = async () => new Response(JSON.stringify({ success: true }), {
    headers: { 'Content-Type': 'application/json' },
  });
});

function submit(fields, body = LOG) {
  const form = new FormData();
  const all = {
    community: '52', map1: 'PCDJ #52 - One', map2: 'PCDJ #52 - Two',
    mapper1: '', mapper2: '', date: new Date().toISOString().slice(0, 10),
    submitter: 'tester', 'cf-turnstile-response': 'token', ...fields,
  };
  for (const [k, v] of Object.entries(all)) form.set(k, v);
  form.set('file', new Blob([body], { type: 'text/plain' }), 'LogOutput.log');
  return worker.fetch(new Request('https://w.example/submit',
    { method: 'POST', body: form, headers: { Origin: ORIGIN } }), env);
}

test('a first submission is received and stores its bytes', async () => {
  const r = await submit({});
  const j = await r.json();
  assert.equal(j.ok, true);
  assert.equal(j.status, 'received');
  assert.ok(await env.SUBMISSIONS.get('log:' + j.id), 'the log bytes are stored');
  assert.equal(env.SUBMISSIONS.subs().length, 1);
});

test('an identical file is kept as its own duplicate record, not dropped', async () => {
  const first = await (await submit({ submitter: 'alice' })).json();
  const second = await (await submit({ submitter: 'bob' })).json();

  assert.equal(second.status, 'duplicate');
  assert.notEqual(second.id, first.id, 'the resend gets its own id');
  assert.equal(second.same_file_as, first.id);

  const subs = env.SUBMISSIONS.subs();
  assert.equal(subs.length, 2, 'both submitters are on record');
  const dup = subs.find((s) => s.id === second.id);
  assert.equal(dup.submitter, 'bob');
  assert.equal(dup.note, 'same file as ' + first.id);
  // The bytes are stored once, not per resend.
  assert.equal(await env.SUBMISSIONS.get('log:' + second.id), null);
});

test('the same file sent under another cup number is flagged for review', async () => {
  const first = await (await submit({ community: '52' })).json();
  const second = await (await submit({ community: '53' })).json();

  const dup = env.SUBMISSIONS.subs().find((s) => s.id === second.id);
  assert.equal(dup.status, 'duplicate');
  assert.ok(dup.note.startsWith('REVIEW: '), `expected a REVIEW note, got ${dup.note}`);
  assert.ok(dup.note.includes('sent as PCDJ 52'), dup.note);
  assert.equal(dup.same_file_as, first.id);
});

test('the daily cap is applied before the dedupe, so resends still count', async () => {
  env.DAILY_SUBMIT_CAP = '1';
  await submit({});
  const r = await submit({ submitter: 'bob' });
  assert.equal(r.status, 429);
  assert.equal(env.SUBMISSIONS.subs().length, 1, 'the capped resend is not recorded');
});
