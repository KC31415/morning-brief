// node --test ops/scheduler/test/worker.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { dispatch } from "../src/worker.js";

const env = { REPO: "KC31415/morning-brief", BRANCH: "main", GITHUB_TOKEN: "t" };
const noWait = async () => {};

function fakeFetch(statuses) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    const status = statuses[Math.min(calls.length - 1, statuses.length - 1)];
    return { status, text: async () => "" };
  };
  return { impl, calls };
}

test("dispatches refresh.yml on main with trigger=scheduler", async () => {
  const f = fakeFetch([204]);
  assert.equal(await dispatch(env, f.impl, noWait), true);
  assert.equal(f.calls[0].url, "https://api.github.com/repos/KC31415/morning-brief/actions/workflows/refresh.yml/dispatches");
  assert.deepEqual(JSON.parse(f.calls[0].init.body), { ref: "main", inputs: { trigger: "scheduler" } });
  assert.equal(f.calls[0].init.headers.Authorization, "Bearer t");
});

test("retries a server error, then succeeds", async () => {
  const f = fakeFetch([502, 204]);
  assert.equal(await dispatch(env, f.impl, noWait), true);
  assert.equal(f.calls.length, 2);
});

test("stops at once on a bad token and reports failure", async () => {
  const f = fakeFetch([401]);
  await assert.rejects(dispatch(env, f.impl, noWait));
  assert.equal(f.calls.length, 1);
});

test("gives up after three server errors", async () => {
  const f = fakeFetch([500]);
  await assert.rejects(dispatch(env, f.impl, noWait));
  assert.equal(f.calls.length, 3);
});
