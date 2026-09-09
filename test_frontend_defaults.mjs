import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { webcrypto } from "node:crypto";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const source = readFileSync(new URL("./app.js", import.meta.url), "utf8");
const rows = [{ issue: "2026001", date: "2026-01-01", red: [1, 6, 11, 16, 21, 26], blue: 1 }];
const plain = (value) => JSON.parse(JSON.stringify(value));

// Use the actual HTML defaults and application functions without adding test APIs to production.
class Element {
  constructor(tag, attributes) {
    this.tagName = tag.toUpperCase();
    this.attributes = new Map([...attributes.matchAll(/([\w-]+)="([^"]*)"/g)].map(([, key, value]) => [key, value]));
    this.value = this.attributes.get("value") || "";
    this.checked = /\schecked(?:\s|\/?>|$)/.test(attributes);
    this.textContent = "";
    this.innerHTML = "";
    this.disabled = false;
    this.listeners = new Map();
    const classes = new Set((this.attributes.get("class") || "").split(/\s+/).filter(Boolean));
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, force = !classes.has(name)) => force ? classes.add(name) : classes.delete(name)
    };
    this.options = [];
  }
  get selectedOptions() { return this.options.filter((option) => option.value === this.value); }
  addEventListener(name, callback) {
    this.listeners.set(name, [...(this.listeners.get(name) || []), callback]);
  }
  async dispatch(name) {
    for (const callback of this.listeners.get(name) || []) await callback({ target: this, key: "" });
  }
  removeAttribute(name) { this.attributes.delete(name); }
  setAttribute(name, value) { this.attributes.set(name, value); }
  querySelectorAll() { return []; }
}

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (name) => values.get(name) ?? null,
    setItem: (name, value) => values.set(name, String(value)),
    removeItem: (name) => values.delete(name)
  };
}

function setup({ access = "local", oldToken = "", historyItems = [], fetcher } = {}) {
  const elements = {};
  for (const [, tag, attributes, id] of html.matchAll(/<([a-z]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    assert.ok(!elements[id], `duplicate id ${id}`);
    elements[id] = new Element(tag, attributes);
  }
  for (const [, attributes, body] of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)) {
    const id = attributes.match(/id="([^"]+)"/)[1];
    elements[id].options = [...body.matchAll(/<option\b([^>]*)>(.*?)<\/option>/g)].map(([, attrs, textContent]) => ({
      value: attrs.match(/value="([^"]+)"/)[1], textContent, selected: /\bselected\b/.test(attrs)
    }));
    elements[id].value = (elements[id].options.find((option) => option.selected) || elements[id].options[0]).value;
  }
  const localStorage = storage(oldToken ? { ssqAdminToken: oldToken } : {});
  const sessionStorage = storage();
  const requests = [];
  const context = vm.createContext({
    document: { getElementById: (id) => elements[id] },
    window: { SSQ_HISTORY: rows, location: { protocol: "http:" }, setTimeout },
    localStorage, sessionStorage, crypto: webcrypto, console,
    fetch: async (path, options) => {
      requests.push({ path, ...options });
      let status = 200;
      let data = {};
      if (fetcher) ({ status = 200, data = {} } = await fetcher(path, options));
      else if (path === "/api/access") {
        if (access === "token" && options.headers.Authorization !== "Bearer test-admin") {
          status = 401;
        } else data = { mode: access, keys: { ai: true, purchase: true }, configured_key_count: 2, independent_keys: true };
      } else if (path.startsWith("/api/ai/recommendations")) data = { items: historyItems };
      else if (path === "/api/ai/tasks") data = {
        task_id: "test-default-task-id-0001", status: "failed", error: { message: "simulated provider failure" }
      };
      return { ok: status < 400, status, json: async () => data };
    }
  });
  const bootstrap = "  init();";
  assert.equal(source.split(bootstrap).length, 2, "one application bootstrap must exist");
  vm.runInContext(source.replace(bootstrap, `  globalThis.testApi = {
    bindEvents, generate, renderRecommendation, initializeAccess, fillCurrentPurchase,
    buildPurchasePayload, aiRequestConfig, analyzeWithAi, accessToken, apiFetch
  };`), context);
  context.testApi.bindEvents();
  return { api: context.testApi, elements, requests, localStorage, sessionStorage, context };
}

const complex = { type: "complex", red: [1, 6, 11, 16, 21, 26, 31], blue: [2, 12], betCount: 14 };

test("all controls have usable defaults, and optional forms start closed", () => {
  const { api, elements, requests } = setup();
  assert.deepEqual(plain(api.aiRequestConfig()), {
    scope: "100", strategy: "balanced", bet_mode: "complex", red_count: 7, blue_count: 2,
    dan_count: 0, tuo_count: 0, shape_filter: true, avoid_popular: true
  });
  const details = [...html.matchAll(/<details\b([^>]*)>/g)];
  assert.equal(details.length, 2);
  assert.ok(details.every(([, attributes]) => !/\bopen\b/.test(attributes)));
  assert.equal(elements.remoteAuth.classList.contains("hidden"), true);
  assert.equal(elements.adminToken.value, "");
  assert.equal(requests.length, 0, "opening must not create a purchase or start paid AI work");
});

test("default generation fills a valid purchase without user input or saving it", () => {
  const { api, elements, requests } = setup();
  api.generate();
  const payload = api.buildPurchasePayload();
  assert.equal(payload.issue, "2026002");
  assert.equal(payload.red.length, 7);
  assert.equal(payload.blue.length, 2);
  assert.equal(new Set(payload.red).size, 7);
  assert.match(elements.purchasePreview.textContent, /14 注 \/ 28 元/);
  assert.match(elements.defaultsSummary.textContent, /近 100 期.*复式 7 红 \+ 2 蓝/);
  assert.equal(requests.length, 0);
});

test("normal and dantuo records follow the current scheme and mode automatically", () => {
  const { api, elements } = setup();
  api.renderRecommendation(complex);
  assert.deepEqual(plain(api.buildPurchasePayload().red), complex.red);
  api.renderRecommendation({
    type: "dantuo", red: [1, 6, 11, 16, 21, 26, 31], blue: [2],
    dantuo: { dan: [1, 6], tuo: [11, 16, 21, 26, 31] }, betCount: 5
  });
  const payload = plain(api.buildPurchasePayload());
  assert.equal(payload.type, "dantuo");
  assert.deepEqual(payload.dan, [1, 6]);
  assert.deepEqual(payload.tuo, [11, 16, 21, 26, 31]);
  assert.equal(elements.purchaseNormalFields.classList.contains("hidden"), true);
  assert.equal(elements.purchaseDantuoFields.classList.contains("hidden"), false);
  assert.match(elements.purchasePreview.textContent, /5 注 \/ 10 元/);
});

test("generating another scheme preserves manual edits until fill-current is clicked", async () => {
  const { api, elements } = setup();
  api.renderRecommendation(complex);
  elements.purchaseIssue.value = "2026020";
  await elements.purchaseIssue.dispatch("input");
  elements.purchaseNote.value = "keep my own record";
  await elements.purchaseNote.dispatch("change");
  api.renderRecommendation({ ...complex, blue: [3, 13] });
  assert.equal(elements.purchaseIssue.value, "2026020");
  assert.equal(elements.purchaseNote.value, "keep my own record");
  assert.equal(elements.purchaseBlue.value, "02 12");
  await elements.fillCurrentBtn.dispatch("click");
  assert.equal(elements.purchaseIssue.value, "2026002");
  assert.equal(elements.purchaseBlue.value, "03 13");
});

test("local auto-connection sends no secret, clears old browser keys, and reads history without overriding defaults", async () => {
  const { api, elements, requests, localStorage } = setup({
    oldToken: "old-provider-key-must-not-be-sent", historyItems: [{ id: "old-report", bet_mode: "single" }]
  });
  await api.initializeAccess();
  assert.equal(api.accessToken(), "");
  assert.equal(localStorage.getItem("ssqAdminToken"), null);
  assert.equal(elements.remoteAuth.classList.contains("hidden"), true);
  assert.match(elements.connectionStatus.textContent, /本地已自动连接/);
  assert.match(elements.aiKeyStatus.textContent, /已配置/);
  assert.match(elements.purchaseKeyStatus.textContent, /已配置/);
  assert.deepEqual(requests.map(({ path }) => path), ["/api/access", "/api/state", "/api/ai/recommendations?limit=12"]);
  assert.ok(requests.every(({ headers }) => !headers.Authorization && headers["X-SSQ-Local"] === "1"));
  assert.equal(elements.modeSelect.value, "complex");
});

test("AI button submits the default configuration without any entered credential", async () => {
  const { api, elements, requests, sessionStorage } = setup();
  await api.initializeAccess();
  await elements.aiAnalyzeBtn.dispatch("click");
  const request = requests.find(({ path }) => path === "/api/ai/tasks");
  assert.ok(request);
  assert.equal(request.method, "POST");
  assert.equal(request.headers.Authorization, undefined);
  const payload = JSON.parse(request.body);
  assert.deepEqual({ ...payload, client_request_id: undefined }, { ...plain(api.aiRequestConfig()), client_request_id: undefined });
  assert.match(payload.client_request_id, /^[\w-]+$/);
  assert.equal(elements.aiAnalyzeBtn.disabled, false);
  assert.match(elements.aiRecommendation.innerHTML, /simulated provider failure/);
  assert.equal(sessionStorage.getItem("ssqAiTaskId"), null);
});

test("remote service stays protected and may reuse a saved management credential", async () => {
  const unsigned = setup({ access: "token" });
  await unsigned.api.initializeAccess();
  assert.equal(unsigned.elements.remoteAuth.classList.contains("hidden"), false);
  assert.equal(unsigned.requests.length, 1);
  const saved = setup({ access: "token", oldToken: "test-admin" });
  await saved.api.initializeAccess();
  assert.equal(saved.api.accessToken(), "test-admin");
  assert.equal(saved.requests[0].headers.Authorization, undefined);
  assert.equal(saved.requests[1].headers.Authorization, "Bearer test-admin");
  assert.match(saved.elements.connectionStatus.textContent, /已连接远程服务/);
});

test("file previews and unavailable servers give actionable messages instead of requesting extra keys", async () => {
  const file = setup();
  file.context.window.location.protocol = "file:";
  await file.api.initializeAccess();
  assert.match(file.elements.connectionStatus.textContent, /不要直接打开 HTML/);
  assert.equal(file.requests.length, 0);
  const offline = setup({ fetcher: async () => { throw new TypeError("offline"); } });
  await offline.api.initializeAccess();
  assert.match(offline.elements.connectionStatus.textContent, /服务连接失败/);
  assert.equal(offline.elements.remoteAuth.classList.contains("hidden"), true);
});
