import assert from "node:assert/strict";
import { createAuthClient } from "./auth-client.js";

const store = new Map();
const storage = {
  getItem: (key) => store.get(key) ?? null,
  setItem: (key, value) => store.set(key, value),
  removeItem: (key) => store.delete(key),
};
const calls = [];
let apiCalls = 0;
const fetchImpl = async (url, options) => {
  calls.push({ url, options });
  if (url.endsWith("/auth/login")) {
    return Response.json({ access_token: "access-1" });
  }
  if (url.endsWith("/auth/refresh")) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    return Response.json({ access_token: "access-2" });
  }
  if (url.endsWith("/auth/logout")) return new Response(null, { status: 204 });
  apiCalls += 1;
  return new Response(null, { status: apiCalls === 1 ? 401 : 200 });
};

const client = createAuthClient({ baseUrl: "https://api.example.test/api/v1", storage, fetchImpl });
await client.login("user@example.test", "secret");
assert.equal(storage.getItem("taskhub_access_token"), "access-1");
const [first, second] = await Promise.all([
  client.request("/tasks"),
  client.request("/tasks"),
]);
assert.equal(first.status, 200);
assert.equal(second.status, 200);
assert.equal(calls.filter(({ url }) => url.endsWith("/auth/refresh")).length, 1);
assert(calls.every(({ options }) => options.credentials === "include"));
assert(calls.some(({ url, options }) => url.endsWith("/tasks") && options.headers.get("Authorization") === "Bearer access-2"));
assert(calls.every(({ options }) => !JSON.stringify(options).includes("refresh_token")));
await client.logout();
assert.equal(storage.getItem("taskhub_access_token"), null);
await client.login("user@example.test", "secret");
await client.request("/tasks", { headers: new Headers({ "X-Client": "present" }) });
assert(calls.some(({ url, options }) => url.endsWith("/tasks") && options.headers.get("X-Client") === "present"));

const failedLogoutStore = new Map([["taskhub_access_token", "access-token"]]);
const failedLogout = createAuthClient({
  baseUrl: "https://api.example.test/api/v1",
  storage: {
    getItem: (key) => failedLogoutStore.get(key) ?? null,
    setItem: (key, value) => failedLogoutStore.set(key, value),
    removeItem: (key) => failedLogoutStore.delete(key),
  },
  fetchImpl: async () => new Response(null, { status: 401 }),
});
await assert.rejects(failedLogout.logout(), /Logout failed/);
assert.equal(failedLogoutStore.has("taskhub_access_token"), false);

const raceStore = new Map([["taskhub_access_token", "old"]]);
let finishRefresh;
let logoutSent = false;
const racing = createAuthClient({
  baseUrl: "https://api.example.test/api/v1",
  storage: {
    getItem: (key) => raceStore.get(key) ?? null,
    setItem: (key, value) => raceStore.set(key, value),
    removeItem: (key) => raceStore.delete(key),
  },
  fetchImpl: async (url) => {
    if (url.endsWith("/tasks")) return new Response(null, { status: 401 });
    if (url.endsWith("/auth/refresh")) {
      return new Promise((resolve) => { finishRefresh = () => resolve(Response.json({ access_token: "late" })); });
    }
    if (url.endsWith("/auth/logout")) {
      logoutSent = true;
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected URL ${url}`);
  },
});
const pendingRequest = racing.request("/tasks").catch(() => {});
while (!finishRefresh) await new Promise((resolve) => setTimeout(resolve, 0));
const pendingLogout = racing.logout();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(logoutSent, false);
finishRefresh();
await Promise.all([pendingRequest, pendingLogout]);
assert.equal(logoutSent, true);
assert.equal(raceStore.get("taskhub_access_token"), undefined);
await assert.rejects(racing.request("//evil.example/path"), /Expected an API path/);

const loginStore = new Map();
let finishLogin;
let queuedLogoutSent = false;
const queuedAuth = createAuthClient({
  baseUrl: "https://api.example.test/api/v1",
  storage: {
    getItem: (key) => loginStore.get(key) ?? null,
    setItem: (key, value) => loginStore.set(key, value),
    removeItem: (key) => loginStore.delete(key),
  },
  fetchImpl: async (url) => {
    if (url.endsWith("/auth/login")) {
      return new Promise((resolve) => { finishLogin = () => resolve(Response.json({ access_token: "late-login" })); });
    }
    if (url.endsWith("/auth/logout")) {
      queuedLogoutSent = true;
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected URL ${url}`);
  },
});
const loginTask = queuedAuth.login("user@example.test", "secret");
while (!finishLogin) await new Promise((resolve) => setTimeout(resolve, 0));
const logoutTask = queuedAuth.logout();
await new Promise((resolve) => setTimeout(resolve, 0));
assert.equal(queuedLogoutSent, false);
finishLogin();
await Promise.all([loginTask, logoutTask]);
assert.equal(queuedLogoutSent, true);
assert.equal(loginStore.get("taskhub_access_token"), undefined);

const switchStore = new Map([["taskhub_access_token", "old"]]);
let finishSwitchRefresh;
let switchApiCalls = 0;
const switching = createAuthClient({
  baseUrl: "https://api.example.test/api/v1",
  storage: {
    getItem: (key) => switchStore.get(key) ?? null,
    setItem: (key, value) => switchStore.set(key, value),
    removeItem: (key) => switchStore.delete(key),
  },
  fetchImpl: async (url) => {
    if (url.endsWith("/tasks")) return new Response(null, { status: ++switchApiCalls === 1 ? 401 : 200 });
    if (url.endsWith("/auth/refresh")) {
      return new Promise((resolve) => { finishSwitchRefresh = () => resolve(Response.json({ access_token: "old-session" })); });
    }
    if (url.endsWith("/auth/login")) return Response.json({ access_token: "new-session" });
    throw new Error(`Unexpected URL ${url}`);
  },
});
const switchRequest = switching.request("/tasks");
while (!finishSwitchRefresh) await new Promise((resolve) => setTimeout(resolve, 0));
const switchLogin = switching.login("other@example.test", "secret");
finishSwitchRefresh();
await Promise.all([switchRequest, switchLogin]);
assert.equal(switchStore.get("taskhub_access_token"), "new-session");
console.log("browser auth client flow passed");
