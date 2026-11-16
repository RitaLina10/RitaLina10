// GasControl SPA — offline-first para operações de campo.
// Segurança: nenhum dado do servidor é inserido via innerHTML; todo texto passa por textContent (h()).
"use strict";
import { kv, outbox, failed, moveToFailed, retryFailed } from "/static/db.js";

const QR_PREFIX = "GC1:";
const OFFLINE_SESSION_HOURS = 72;   // por quanto tempo o app opera offline após o último login online
const SYNC_INTERVAL_MS = 30000;
const MAX_RETRIES = 5;
const state = { token: null, me: null, sessionAt: 0, gases: [], customers: [], snapshot: null, syncing: false };

// ---------------- utilidades ----------------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);
const badge = (s) => h("span", { class: `badge s-${s}` }, String(s).replace("_", " "));
const fmtDate = (d) => (d ? new Date(d.length === 10 ? d + "T00:00:00" : d).toLocaleDateString("pt-BR") : "—");
const fmtDT = (d) => (d ? new Date(/Z$|[+-]\d\d:\d\d$/.test(d) ? d : d + "Z").toLocaleString("pt-BR") : "—");
const roleIs = (...r) => state.me && (state.me.role === "ADMIN" || r.includes(state.me.role));
const cleanSerial = (s) => String(s || "").trim().toUpperCase().replace(QR_PREFIX, "");
const online = () => navigator.onLine;
const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
  : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
      (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)));

class OfflineError extends Error {}
class AuthError extends Error {}

function toast(msg, kind = "ok") {
  const t = h("div", { class: "toast" + (kind === "err" ? " err" : "") + (kind === "warn" ? " warn" : "") }, msg);
  $("#toast").append(t);
  setTimeout(() => t.remove(), kind === "err" ? 8000 : 4000);
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.dataset.skip !== undefined) continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.value === "") continue;
    else if (el.type === "number" || el.dataset.int !== undefined) out[el.name] = Number(el.value);
    else out[el.name] = el.value.trim();
  }
  return out;
}

function jwtExp(token) {
  try {
    const p = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return (p.exp || 0) * 1000;
  } catch (_) { return 0; }
}
const tokenValid = () => state.token && jwtExp(state.token) > Date.now() + 30000;

async function api(path, { method = "GET", body, raw = false } = {}) {
  if (!online()) throw new OfflineError("Sem conexão");
  if (!tokenValid() && path !== "/api/auth/login") throw new AuthError("Sessão expirada; faça login para sincronizar");
  const headers = { Accept: "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 20000);
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                              signal: ctrl.signal, credentials: "omit" });
  } catch (e) {
    throw new OfflineError(e.name === "AbortError" ? "Tempo de resposta esgotado" : "Falha de rede");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401 && path !== "/api/auth/login") {
    state.token = null;
    await saveSession();
    renderNet();
    throw new AuthError("Sessão expirada; faça login para sincronizar");
  }
  if (raw) {
    if (!res.ok) throw new Error(`Erro ${res.status}`);
    return res;
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const m = data && data.message;
    throw new Error(Array.isArray(m) ? m.map((x) => `${x.loc.slice(1).join(".")}: ${x.msg}`).join("; ") : m || `Erro ${res.status}`);
  }
  return data;
}

function guard(fn) {
  return async (ev) => {
    if (ev && ev.preventDefault) ev.preventDefault();
    const btn = ev && ev.submitter;
    if (btn) btn.disabled = true;
    try { await fn(ev); } catch (e) {
      if (e instanceof AuthError) promptRelogin();
      toast(e.message, "err");
    } finally { if (btn) btn.disabled = false; }
  };
}

async function download(path, filename) {
  const res = await api(path, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  const a = h("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

function table(headers, rows) {
  return h("table", {}, h("thead", {}, h("tr", {}, headers.map((x) => h("th", {}, x)))),
    h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c))))
                                : h("tr", {}, h("td", { colspan: headers.length, class: "muted" }, "Nenhum registro"))));
}

function gasSelect(name = "gas_type_id") {
  return h("select", { name, required: true, "data-int": "" },
    state.gases.map((g) => h("option", { value: g.id }, `${g.code} — ${g.name}`)));
}

function customerSelect(name = "customer_id", required = true) {
  return h("select", { name, required, "data-int": "" }, h("option", { value: "" }, "— selecione o cliente —"),
    state.customers.map((c) => h("option", { value: c.id }, `${c.name} (${c.document})`)));
}

// ---------------- sessão (persistente para uso offline) ----------------
async function saveSession() {
  await kv.set("session", { token: state.token, me: state.me, sessionAt: state.sessionAt });
}

async function loadSession() {
  const s = await kv.get("session");
  if (!s || !s.me) return false;
  Object.assign(state, { token: s.token, me: s.me, sessionAt: s.sessionAt || 0 });
  return Date.now() - state.sessionAt < OFFLINE_SESSION_HOURS * 3600 * 1000;
}

// ---------------- snapshot de referência (offline) ----------------
async function refreshSnapshot() {
  try {
    const snap = await api("/api/sync/snapshot");
    state.snapshot = snap;
    await kv.set("snapshot", snap);
  } catch (e) {
    if (!(e instanceof OfflineError || e instanceof AuthError)) throw e;
    state.snapshot = state.snapshot || (await kv.get("snapshot")) || null;
  }
  if (state.snapshot) {
    state.gases = state.snapshot.gas_types;
    state.customers = state.snapshot.customers;
  }
}

function localCylinder(serial) {
  return state.snapshot && state.snapshot.cylinders.find((c) => c.serial === serial);
}

const TRANSITIONS = {
  ENVASE: [["VAZIO"], "CHEIO"], ENTREGA: [["CHEIO"], "EM_CLIENTE"], COLETA: [["EM_CLIENTE"], "VAZIO"],
  ENVIO_MANUTENCAO: [["VAZIO", "CHEIO"], "MANUTENCAO"], RETORNO_MANUTENCAO: [["MANUTENCAO"], "VAZIO"],
  CONDENACAO: [["VAZIO", "MANUTENCAO"], "CONDENADO"],
};

// Pré-validação local (mesmas regras do servidor). O servidor revalida tudo na sincronização.
function precheck(serial, type, payload) {
  const c = localCylinder(serial);
  if (!c) return { warn: `Cilindro ${serial} não está no cache do aparelho; será validado ao sincronizar.` };
  const [from] = TRANSITIONS[type];
  if (!from.includes(c.status)) return { error: `${serial} está ${c.status}; não aceita ${type}.` };
  if (type === "ENVASE" && c.hydro_expired) return { error: `${serial}: teste hidrostático vencido.` };
  if (type === "COLETA" && payload.customer_id && c.customer_id && c.customer_id !== payload.customer_id)
    return { error: `${serial} não está registrado neste cliente.` };
  if (type === "ENTREGA" && c.category === "MEDICINAL") {
    const lot = state.snapshot.lots.find((l) => l.id === c.lot_id);
    if (!lot || lot.status !== "APROVADO") return { error: `${serial}: lote medicinal não aprovado; entrega bloqueada.` };
  }
  return {};
}

function applyLocally(serial, type, payload) {
  const c = localCylinder(serial);
  if (!c) return;
  c.status = TRANSITIONS[type][1];
  if (type === "ENTREGA") c.customer_id = payload.customer_id;
  if (type === "COLETA") { c.customer_id = null; c.lot_id = null; }
  if (type === "ENVASE") c.lot_id = payload.lot_id || null;
  kv.set("snapshot", state.snapshot);
}

// ---------------- fila de sincronização ----------------
async function enqueue(kind, payload) {
  const item = { client_uuid: uuid(), kind, payload, occurred_at: new Date().toISOString(),
                 user_id: state.me.id, attempts: 0 };
  await outbox.put(item);  // grava ANTES de tentar enviar: nada se perde se a rede cair no meio
  await renderNet();
  return item;
}

async function flush({ quiet = false } = {}) {
  if (state.syncing || !online() || !tokenValid()) { await renderNet(); return { sent: 0 }; }
  state.syncing = true;
  let sent = 0, rejected = 0;
  try {
    const run = async () => {
      const mine = (await outbox.all()).filter((i) => i.user_id === state.me.id)
        .sort((a, b) => a.occurred_at.localeCompare(b.occurred_at));
      for (let i = 0; i < mine.length; i += 50) {
        const chunk = mine.slice(i, i + 50);
        const results = await api("/api/sync/batch", { method: "POST", body: {
          items: chunk.map(({ client_uuid, kind, occurred_at, payload }) => ({ client_uuid, kind, occurred_at, payload })) } });
        const byId = Object.fromEntries(chunk.map((c) => [c.client_uuid, c]));
        for (const r of results) {
          const item = byId[r.client_uuid];
          if (!item) continue;
          if (r.status === "ok" || r.status === "duplicate") { await outbox.del(item.client_uuid); sent++; }
          else if (r.retryable && item.attempts + 1 < MAX_RETRIES) await outbox.put({ ...item, attempts: item.attempts + 1 });
          else { await moveToFailed(item, r.message || r.error); rejected++; }
        }
      }
    };
    // Web Locks: evita duas abas enviando a mesma fila em paralelo.
    if (navigator.locks) await navigator.locks.request("gc-sync", run); else await run();
    if (sent || rejected) await refreshSnapshot();
  } catch (e) {
    if (e instanceof AuthError) promptRelogin();
    else if (!(e instanceof OfflineError) && !quiet) toast("Sincronização: " + e.message, "err");
  } finally {
    state.syncing = false;
    await renderNet();
  }
  if (!quiet && sent) toast(`${sent} operação(ões) sincronizada(s)`);
  if (rejected) toast(`${rejected} operação(ões) recusada(s) pelo servidor — veja "Pendências" na tela Operação`, "err");
  return { sent, rejected };
}

async function renderNet() {
  if (!state.me) return;
  const pending = (await outbox.all()).filter((i) => i.user_id === state.me.id).length;
  const bad = (await failed.all()).filter((i) => i.user_id === state.me.id).length;
  const net = $("#net");
  const status = !online() ? "Offline" : !tokenValid() ? "Login necessário" : state.syncing ? "Sincronizando…" : "Online";
  $("#net-label").textContent = `${status} · ${pending} pendente(s)` + (bad ? ` · ${bad} recusada(s)` : "");
  net.classList.toggle("off", !online() || !tokenValid());
  net.classList.toggle("warn", bad > 0);
}

function promptRelogin() {
  if (online() && !tokenValid()) {
    $("#login-view").classList.remove("hidden");
    $("#app-view").classList.add("hidden");
    $("#login-error").textContent = "Sessão expirada. Entre novamente para enviar as operações pendentes (elas continuam salvas).";
  }
}

// ---------------- leitor de QR (câmera) ----------------
async function scanInto(input) {
  if (!("BarcodeDetector" in window)) {
    toast("Navegador sem leitor nativo; use leitor USB/Bluetooth ou digite o número de série.", "err");
    input.focus();
    return;
  }
  const video = h("video", { autoplay: true, playsinline: true, muted: true });
  const wrap = h("div", { class: "card" }, video, h("button", { type: "button", class: "ghost", onclick: () => stop() }, "Cancelar"));
  input.closest("form").prepend(wrap);
  let stream, active = true;
  const stop = () => { active = false; stream && stream.getTracks().forEach((t) => t.stop()); wrap.remove(); };
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    video.srcObject = stream;
    const det = new BarcodeDetector({ formats: ["qr_code", "code_128", "code_39", "ean_13"] });
    const loop = async () => {
      if (!active) return;
      try {
        const codes = await det.detect(video);
        if (codes.length) {
          input.value = cleanSerial(codes[0].rawValue);
          input.dispatchEvent(new Event("change"));
          stop();
          toast(`Lido: ${input.value}`);
          return;
        }
      } catch (_) { /* frame ainda não pronto */ }
      requestAnimationFrame(loop);
    };
    loop();
  } catch (e) {
    stop();
    toast("Câmera indisponível: " + e.message, "err");
  }
}

function serialField(name, label) {
  const input = h("input", { name, required: true, maxlength: 44, autocomplete: "off", placeholder: "Bipe ou digite o nº de série" });
  return h("label", {}, label, h("div", { class: "row" }, input,
    h("button", { type: "button", class: "ghost", onclick: () => scanInto(input) }, "📷 Ler QR")));
}

function geo() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve({});
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latitude: +p.coords.latitude.toFixed(6), longitude: +p.coords.longitude.toFixed(6) }),
      () => resolve({}), { timeout: 4000, maximumAge: 60000 });
  });
}

// ---------------- telas ----------------
const VIEWS = {
  painel: { label: "Painel", roles: ["GESTOR", "OPERADOR"], render: viewDashboard },
  operacao: { label: "Operação", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewOperation, offline: true },
  cilindros: { label: "Cilindros", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewCylinders },
  clientes: { label: "Clientes", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewCustomers },
  lotes: { label: "Lotes", roles: ["GESTOR", "OPERADOR"], render: viewLots },
  historico: { label: "Movimentações", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewMovements },
  auditoria: { label: "Auditoria", roles: ["GESTOR"], render: viewAudit },
  usuarios: { label: "Usuários", roles: [], render: viewUsers },
};

async function viewDashboard(main) {
  const d = await api("/api/dashboard");
  const s = d.by_status;
  main.append(
    h("div", { class: "grid" },
      ["CHEIO", "VAZIO", "EM_CLIENTE", "MANUTENCAO", "CONDENADO"].map((k) =>
        h("div", { class: "kpi" }, badge(k), h("b", {}, s[k] ?? 0))),
      h("div", { class: "kpi" }, h("span", { class: "badge s-VENCIDO" }, "TESTE HIDROSTÁTICO"),
        h("b", {}, d.hydro_alerts.length), h("span", { class: "muted" }, "vencidos ou a vencer"))),
    h("div", { class: "cols" },
      h("div", { class: "card" }, h("h2", {}, "Saldo de cilindros por cliente"),
        table(["Cliente", "Cilindros", "Comodato"], d.customer_balance.map((r) => [r.customer, r.cylinders, r.loans]))),
      h("div", { class: "card" }, h("h2", {}, "Alertas de teste hidrostático"),
        table(["Série", "Gás", "Situação", "Vence", "Local"], d.hydro_alerts.map((a) => [
          a.serial, a.gas, a.expired ? badge("VENCIDO") : badge("MANUTENCAO"), fmtDate(a.due_date), a.customer || a.status]))),
      h("div", { class: "card" }, h("h2", {}, "Estoque por gás"),
        table(["Gás", "Status", "Qtd"], d.by_gas.map((r) => [r.gas, badge(r.status), r.count]))),
      h("div", { class: "card" }, h("h2", {}, "Lotes aguardando liberação"),
        table(["Lote", "Gás"], d.lots_in_quarantine.map((l) => [l.code, l.gas])))),
    h("p", { class: "muted" }, `Atualizado em ${fmtDT(d.generated_at)}`));
}

async function viewOperation(main) {
  if (!state.snapshot) await refreshSnapshot();
  const snap = state.snapshot;
  if (!snap) {
    main.append(h("p", { class: "error" }, "Sem dados de referência no aparelho. Conecte-se uma vez para baixar."));
    return;
  }
  if (!online()) main.append(h("div", { class: "banner" },
    "Modo offline: as operações ficam salvas neste aparelho e são enviadas automaticamente quando a internet voltar."));

  const usableLots = snap.lots.filter((l) => l.status !== "REPROVADO");
  const types = [
    ["ENTREGA", "Entrega"], ["COLETA", "Coleta"], ["ENVASE", "Envase"],
    ["ENVIO_MANUTENCAO", "Envio p/ manutenção"], ["RETORNO_MANUTENCAO", "Retorno de manutenção"], ["CONDENACAO", "Condenação"],
  ].filter(([t]) => ({ ENTREGA: 1, COLETA: 1 }[t] || roleIs("GESTOR", "OPERADOR")) && (t !== "CONDENACAO" || roleIs("GESTOR")));

  const extra = h("div");
  const typeSel = h("select", { name: "type", required: true }, types.map(([v, l]) => h("option", { value: v }, l)));
  const renderExtra = () => {
    extra.replaceChildren();
    const t = typeSel.value;
    if (t === "ENTREGA" || t === "COLETA") extra.append(h("label", {}, "Cliente", customerSelect()));
    if (t === "ENTREGA") extra.append(h("label", {}, h("input", { type: "checkbox", name: "is_loan" }), "Comodato"));
    if (t === "ENVASE") {
      const gasCode = (id) => (state.gases.find((g) => g.id === id) || {}).code || "?";
      extra.append(h("label", {}, "Lote (obrigatório para medicinal)",
        h("select", { name: "lot_id", "data-int": "" }, h("option", { value: "" }, "— sem lote (industrial) —"),
          usableLots.map((l) => h("option", { value: l.id }, `${l.code} · ${gasCode(l.gas_type_id)} · ${l.status}`)))),
        h("fieldset", { class: "checklist card" }, h("legend", {}, "Inspeção pré-envase (obrigatória para medicinal)"),
          Object.entries(snap.checklist).map(([k, label]) =>
            h("label", {}, h("input", { type: "checkbox", "data-check": k, "data-skip": "" }), label))));
    }
    if (t === "RETORNO_MANUTENCAO") extra.append(h("label", {}, "Novo teste hidrostático (se realizado)", h("input", { type: "date", name: "new_hydro_test" })));
    if (["ENTREGA", "COLETA"].includes(t)) extra.append(h("label", {}, "NF-e / romaneio", h("input", { name: "document_ref", maxlength: 60 })));
  };
  typeSel.addEventListener("change", renderExtra);
  renderExtra();

  const submitOp = async (kind, payload, serials) => {
    if (!online()) {
      for (const [serial, type] of serials) {
        const r = precheck(serial, type, payload);
        if (r.error) throw new Error(r.error);
        if (r.warn) toast(r.warn, "warn");
      }
    }
    await enqueue(kind, payload);
    for (const [serial, type] of serials) applyLocally(serial, type, payload);
    if (online() && tokenValid()) {
      const { sent, rejected } = await flush({ quiet: true });
      if (sent) toast("Registrado e sincronizado");
      else if (!rejected) toast("Salvo no aparelho; será enviado quando possível", "warn");
    } else {
      toast("Salvo offline. Será sincronizado automaticamente.", "warn");
    }
    await renderPending();
  };

  const single = h("form", { class: "card", onsubmit: guard(async (ev) => {
    const form = ev.target;
    const body = formData(form);
    body.serial = cleanSerial(body.serial);
    const checks = form.querySelectorAll("[data-check]");
    if (body.type === "ENVASE" && checks.length) {
      body.checklist = Object.fromEntries([...checks].map((c) => [c.dataset.check, c.checked]));
    }
    Object.assign(body, await geo());
    await submitOp("movement", body, [[body.serial, body.type]]);
    form.serial.value = "";
    checks.forEach((c) => { c.checked = false; });
    form.serial.focus();
  }) },
    h("h2", {}, "Movimentação de cilindro"),
    h("label", {}, "Operação", typeSel), serialField("serial", "Cilindro"), extra,
    h("label", {}, "Observações", h("textarea", { name: "notes", maxlength: 1000, rows: 2 })),
    h("button", { type: "submit" }, "Registrar"));

  const exchange = h("form", { class: "card", onsubmit: guard(async (ev) => {
    const body = formData(ev.target);
    body.full_serial = cleanSerial(body.full_serial);
    body.empty_serial = cleanSerial(body.empty_serial);
    if (body.full_serial === body.empty_serial) throw new Error("Cilindro cheio e vazio devem ser diferentes");
    Object.assign(body, await geo());
    await submitOp("exchange", body, [[body.empty_serial, "COLETA"], [body.full_serial, "ENTREGA"]]);
    ev.target.reset();
  }) },
    h("h2", {}, "Troca (entrega cheio + recolhe vazio)"),
    h("label", {}, "Cliente", customerSelect()),
    serialField("full_serial", "Cilindro CHEIO entregue"), serialField("empty_serial", "Cilindro VAZIO recolhido"),
    h("label", {}, h("input", { type: "checkbox", name: "is_loan" }), "Comodato"),
    h("label", {}, "NF-e / romaneio", h("input", { name: "document_ref", maxlength: 60 })),
    h("button", { type: "submit" }, "Registrar troca"));

  const pendingBox = h("div", { class: "card" });
  const describe = (i) => i.kind === "exchange"
    ? `TROCA ${i.payload.full_serial} ⇄ ${i.payload.empty_serial}` : `${i.payload.type} ${i.payload.serial}`;
  const renderPending = async () => {
    const pend = (await outbox.all()).filter((i) => i.user_id === state.me.id);
    const bad = (await failed.all()).filter((i) => i.user_id === state.me.id);
    pendingBox.replaceChildren(
      h("h2", {}, "Pendências deste aparelho"),
      h("p", { class: "muted" }, `${pend.length} aguardando envio`),
      table(["Feito em", "Operação", "Tentativas"], pend.map((i) => [fmtDT(i.occurred_at), describe(i), i.attempts])),
      h("h2", {}, "Recusadas pelo servidor (revisar)"),
      table(["Feito em", "Operação", "Motivo", ""], bad.map((i) => [fmtDT(i.occurred_at), describe(i), i.error,
        h("span", {},
          h("button", { class: "sm ghost", onclick: guard(async () => { await retryFailed(i); await flush(); await renderPending(); }) }, "Reenviar"), " ",
          h("button", { class: "sm danger", onclick: guard(async () => {
            if (!confirm("Descartar esta operação? Ela não será registrada no sistema.")) return;
            await failed.del(i.client_uuid); await renderNet(); await renderPending();
          }) }, "Descartar"))]))
    );
  };
  await renderPending();
  main.append(h("div", { class: "cols" }, single, exchange), pendingBox);
}

async function viewCylinders(main) {
  const list = h("div");
  const detail = h("div");
  const load = async (params = "") => {
    const rows = await api(`/api/cylinders?limit=500${params}`);
    const today = new Date().toISOString().slice(0, 10);
    list.replaceChildren(table(["Série", "Gás", "Cap. (L)", "Status", "Cliente", "Lote", "Teste vence", ""],
      rows.map((c) => [c.serial, c.gas_type.code, c.capacity_liters, badge(c.status),
        c.current_customer ? c.current_customer.name + (c.is_loan ? " (comodato)" : "") : "—",
        c.current_lot ? c.current_lot.code : "—",
        c.hydro_due_date < today ? h("span", { class: "badge s-VENCIDO" }, fmtDate(c.hydro_due_date)) : fmtDate(c.hydro_due_date),
        h("button", { class: "sm ghost", onclick: guard(() => showHistory(c.serial)) }, "Rastrear")])));
  };
  const showHistory = async (serial) => {
    const [hist, png] = await Promise.all([
      api(`/api/cylinders/${encodeURIComponent(serial)}/history`),
      api(`/api/cylinders/${encodeURIComponent(serial)}/qr.png`, { raw: true }).then((r) => r.blob()),
    ]);
    const url = URL.createObjectURL(png);
    detail.replaceChildren(h("div", { class: "card" },
      h("div", { class: "row" },
        h("div", {}, h("h2", {}, `Rastreabilidade — ${hist.cylinder.serial}`),
          h("p", {}, `${hist.cylinder.gas_type.name} · ${hist.cylinder.capacity_liters} L · último teste ${fmtDate(hist.cylinder.last_hydro_test)}`),
          roleIs("GESTOR", "OPERADOR") ? h("button", { class: "sm ghost", onclick: guard(() =>
            download(`/api/cylinders/${encodeURIComponent(serial)}/history.csv`, `cilindro-${serial}.csv`)) }, "Exportar CSV") : null),
        h("div", {}, h("img", { class: "qr", src: url, alt: `QR ${serial}` }),
          h("button", { class: "sm ghost", onclick: () => window.print() }, "Imprimir etiqueta"))),
      table(["Data", "Operação", "De → Para", "Cliente", "Lote", "Usuário", "Doc.", "Origem", "Hash"],
        hist.movements.map((m) => [fmtDT(m.client_occurred_at || m.occurred_at), m.type, `${m.from_status || "—"} → ${m.to_status}`,
          m.customer ? m.customer.name : "—", m.lot ? m.lot.code : "—", m.user.name, m.document_ref || "—",
          m.offline ? `offline (sinc. ${fmtDT(m.occurred_at)})` : "online",
          h("span", { class: "mono" }, m.hash.slice(0, 12) + "…")]))));
    detail.scrollIntoView({ behavior: "smooth" });
  };

  const filter = h("form", { class: "card row", onsubmit: guard(async (ev) => {
    const f = formData(ev.target);
    const p = new URLSearchParams();
    if (f.q) p.set("q", cleanSerial(f.q));
    if (f.status) p.set("status", f.status);
    if (f.gas_type_id) p.set("gas_type_id", f.gas_type_id);
    await load("&" + p.toString());
  }) },
    h("label", {}, "Série", h("input", { name: "q", maxlength: 40 })),
    h("label", {}, "Status", h("select", { name: "status" }, h("option", { value: "" }, "Todos"),
      ["CHEIO", "VAZIO", "EM_CLIENTE", "MANUTENCAO", "CONDENADO"].map((s) => h("option", { value: s }, s)))),
    h("label", {}, "Gás", h("select", { name: "gas_type_id", "data-int": "" }, h("option", { value: "" }, "Todos"),
      state.gases.map((g) => h("option", { value: g.id }, g.code)))),
    h("button", { type: "submit" }, "Filtrar"));

  if (roleIs("GESTOR", "OPERADOR")) {
    main.append(h("form", { class: "card", onsubmit: guard(async (ev) => {
      const body = formData(ev.target);
      body.serial = cleanSerial(body.serial);
      const c = await api("/api/cylinders", { method: "POST", body });
      toast(`Cilindro ${c.serial} cadastrado`);
      ev.target.reset();
      await Promise.all([load(), refreshSnapshot()]);
      await showHistory(c.serial);
    }) },
      h("h2", {}, "Cadastrar cilindro"),
      h("div", { class: "row" },
        h("label", {}, "Nº de série", h("input", { name: "serial", required: true, maxlength: 40 })),
        h("label", {}, "Gás", gasSelect()),
        h("label", {}, "Capacidade (L)", h("input", { name: "capacity_liters", type: "number", step: "0.01", min: "0.01", required: true })),
        h("label", {}, "Último teste hidrostático", h("input", { name: "last_hydro_test", type: "date", required: true }))),
      h("div", { class: "row" },
        h("label", {}, "Fabricante", h("input", { name: "manufacturer", maxlength: 120 })),
        h("label", {}, "Data de fabricação", h("input", { name: "manufacture_date", type: "date" })),
        h("label", {}, h("input", { type: "checkbox", name: "owned_by_company", checked: true }), "Patrimônio próprio")),
      h("button", { type: "submit" }, "Cadastrar e gerar QR Code")));
  }
  main.append(filter, h("div", { class: "card" }, list), detail);
  await load();
}

async function viewCustomers(main) {
  const list = h("div");
  const render = async () => {
    const rows = await api("/api/customers?limit=200");
    list.replaceChildren(table(["Nome", "CPF/CNPJ", "Telefone", "Estab. saúde", "Ativo", ""],
      rows.map((c) => [c.name, c.document, c.phone || "—", c.is_health_facility ? "Sim" : "Não", c.active ? "Sim" : "Não",
        h("button", { class: "sm ghost", onclick: guard(async () => {
          const cyl = await api(`/api/cylinders?customer_id=${c.id}&limit=500`);
          toast(`${c.name}: ${cyl.length} cilindro(s) em posse — ${cyl.map((r) => r.serial).join(", ") || "nenhum"}`);
        }) }, "Saldo")])));
  };
  if (roleIs("GESTOR", "OPERADOR")) {
    main.append(h("form", { class: "card", onsubmit: guard(async (ev) => {
      await api("/api/customers", { method: "POST", body: formData(ev.target) });
      toast("Cliente cadastrado");
      ev.target.reset();
      await Promise.all([render(), refreshSnapshot()]);
    }) },
      h("h2", {}, "Novo cliente"),
      h("div", { class: "row" },
        h("label", {}, "Nome / Razão social", h("input", { name: "name", required: true, maxlength: 160 })),
        h("label", {}, "CPF / CNPJ", h("input", { name: "document", required: true, maxlength: 20 })),
        h("label", {}, "Telefone", h("input", { name: "phone", maxlength: 30 }))),
      h("label", {}, "Endereço", h("input", { name: "address", maxlength: 300 })),
      h("label", {}, h("input", { type: "checkbox", name: "is_health_facility" }), "Estabelecimento de saúde / home care"),
      h("button", { type: "submit" }, "Salvar")));
  }
  main.append(h("div", { class: "card" }, list));
  await render();
}

async function viewLots(main) {
  const list = h("div");
  const trace = h("div");
  const load = async () => {
    const lots = await api("/api/lots?limit=200");
    list.replaceChildren(table(["Lote", "Gás", "Produção", "Validade", "Laudo", "Status", "Assinatura", ""],
      lots.map((l) => [l.code, l.gas_type.code, fmtDate(l.production_date), fmtDate(l.expiry_date), l.analysis_report || "—", badge(l.status),
        l.signature_hash ? h("span", { title: l.signature_meaning }, `${fmtDT(l.released_at)} · ${l.signature_hash.slice(0, 10)}…`) : "—",
        h("span", {},
          l.status === "QUARENTENA" && roleIs("GESTOR") ? [
            h("button", { class: "sm", onclick: () => signForm(l, true) }, "Aprovar"), " ",
            h("button", { class: "sm danger", onclick: () => signForm(l, false) }, "Reprovar"), " "] : null,
          h("button", { class: "sm ghost", onclick: guard(() => showTrace(l.id)) }, "Recall"), " ",
          roleIs("GESTOR") ? h("button", { class: "sm ghost", onclick: guard(() =>
            download(`/api/lots/${l.id}/dossier.csv`, `dossie-lote-${l.code}.csv`)) }, "Dossiê CSV") : null)])));
  };
  // Assinatura eletrônica: o responsável técnico reconfirma a senha e o significado do ato.
  const signForm = (lot, approve) => {
    const form = h("form", { class: "sig", onsubmit: guard(async (ev) => {
      const f = formData(ev.target);
      await api(`/api/lots/${lot.id}/decision`, { method: "POST",
        body: { approve, notes: f.notes || null, signature_password: f.signature_password } });
      toast(approve ? "Lote aprovado e assinado" : "Lote reprovado e assinado");
      form.remove();
      await Promise.all([load(), refreshSnapshot()]);
    }) },
      h("h2", {}, `${approve ? "Aprovar" : "Reprovar"} lote ${lot.code} — assinatura eletrônica`),
      h("p", {}, `Ao assinar, ${state.me.name} declara: "${approve ? "Aprovo a liberação deste lote para uso" : "Reprovo este lote; uso proibido"}".`),
      h("label", {}, approve ? "Observação da liberação" : "Motivo da reprovação",
        h("textarea", { name: "notes", maxlength: 1000, rows: 2, required: !approve })),
      h("label", {}, "Confirme sua senha", h("input", { name: "signature_password", type: "password", required: true, autocomplete: "current-password" })),
      h("button", { type: "submit", class: approve ? "" : "danger" }, "Assinar"), " ",
      h("button", { type: "button", class: "ghost", onclick: () => form.remove() }, "Cancelar"));
    list.prepend(form);
    form.querySelector("textarea").focus();
  };
  const showTrace = async (id) => {
    const t = await api(`/api/lots/${id}/trace`);
    trace.replaceChildren(h("div", { class: "card" }, h("h2", {}, `Recall do lote ${t.lot.code}`),
      table(["Data", "Operação", "Cilindro", "Cliente", "Usuário"],
        t.movements.map((m) => [fmtDT(m.client_occurred_at || m.occurred_at), m.type, m.cylinder.serial, m.customer ? m.customer.name : "—", m.user.name]))));
  };
  main.append(h("form", { class: "card", onsubmit: guard(async (ev) => {
    await api("/api/lots", { method: "POST", body: formData(ev.target) });
    toast("Lote criado em QUARENTENA");
    ev.target.reset();
    await load();
  }) },
    h("h2", {}, "Novo lote de envase"),
    h("div", { class: "row" },
      h("label", {}, "Código", h("input", { name: "code", required: true, maxlength: 40 })),
      h("label", {}, "Gás", gasSelect()),
      h("label", {}, "Produção", h("input", { name: "production_date", type: "date", required: true })),
      h("label", {}, "Validade", h("input", { name: "expiry_date", type: "date", required: true }))),
    h("div", { class: "row" },
      h("label", {}, "Pureza (%)", h("input", { name: "purity_percent", type: "number", step: "0.001", min: 0, max: 100 })),
      h("label", {}, "Nº laudo de análise", h("input", { name: "analysis_report", maxlength: 60 }))),
    h("button", { type: "submit" }, "Criar lote")),
  h("div", { class: "card" }, list), trace);
  await load();
}

async function viewMovements(main) {
  const rows = await api("/api/movements?limit=200");
  main.append(h("div", { class: "card" }, h("h2", {}, roleIs("GESTOR", "OPERADOR") ? "Últimas movimentações" : "Minhas movimentações"),
    table(["Data", "Operação", "Cilindro", "De → Para", "Cliente", "Lote", "Usuário", "Doc.", "Origem"],
      rows.map((m) => [fmtDT(m.client_occurred_at || m.occurred_at), m.type, m.cylinder.serial, `${m.from_status || "—"} → ${m.to_status}`,
        m.customer ? m.customer.name : "—", m.lot ? m.lot.code : "—", m.user.name, m.document_ref || "—",
        m.offline ? "offline" : "online"]))));
}

async function viewAudit(main) {
  const out = h("p", { class: "muted" });
  const events = await api("/api/audit/events?limit=300");
  main.append(
    h("div", { class: "card" }, h("h2", {}, "Integridade dos registros"),
      h("p", { class: "muted" }, "Movimentações e cadastros são encadeados por hash SHA-256. Qualquer edição direta no banco é detectada."),
      h("button", { onclick: guard(async () => {
        const r = await api("/api/audit/verify");
        out.textContent = r.ok
          ? `✔ Íntegro — ${r.movements_checked} movimentações e ${r.audit_events_checked} eventos de cadastro verificados`
          : `✖ Adulteração detectada: cilindros ${JSON.stringify(r.broken)}; evento de cadastro ${r.audit_broken_event_id ?? "—"}`;
      }) }, "Verificar agora"), out),
    h("div", { class: "card" }, h("h2", {}, "Trilha de auditoria de cadastros"),
      table(["Data", "Usuário", "Ação", "Entidade", "ID", "Detalhes"],
        events.map((e) => [fmtDT(e.occurred_at), e.user ? e.user.name : "sistema", e.action, e.entity, e.entity_id ?? "—",
          h("span", { class: "mono" }, e.data)]))));
}

async function viewUsers(main) {
  const list = h("div");
  const load = async () => {
    const users = await api("/api/users");
    list.replaceChildren(table(["Nome", "E-mail", "Perfil", "Ativo", ""], users.map((u) => [u.name, u.email, u.role, u.active ? "Sim" : "Não",
      u.id === state.me.id ? "—" : h("button", { class: "sm ghost", onclick: guard(async () => {
        await api(`/api/users/${u.id}`, { method: "PATCH", body: { active: !u.active } });
        await load();
      }) }, u.active ? "Desativar" : "Reativar")])));
  };
  main.append(h("form", { class: "card", onsubmit: guard(async (ev) => {
    await api("/api/users", { method: "POST", body: formData(ev.target) });
    toast("Usuário criado");
    ev.target.reset();
    await load();
  }) },
    h("h2", {}, "Novo usuário"),
    h("div", { class: "row" },
      h("label", {}, "Nome", h("input", { name: "name", required: true, maxlength: 120 })),
      h("label", {}, "E-mail", h("input", { name: "email", type: "email", required: true })),
      h("label", {}, "Senha (mín. 10)", h("input", { name: "password", type: "password", required: true, minlength: 10, autocomplete: "new-password" })),
      h("label", {}, "Perfil", h("select", { name: "role" }, ["MOTORISTA", "OPERADOR", "GESTOR", "ADMIN"].map((r) => h("option", { value: r }, r))))),
    h("button", { type: "submit" }, "Criar")), h("div", { class: "card" }, list));
  await load();
}

// ---------------- navegação / sessão ----------------
let currentView = null;
async function go(key) {
  const view = VIEWS[key];
  currentView = key;
  const main = $("#main");
  main.replaceChildren(h("p", { class: "muted" }, "Carregando…"));
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === key));
  location.hash = key;
  try {
    const frag = h("div");
    await view.render(frag);
    main.replaceChildren(...frag.childNodes);
  } catch (e) {
    const msg = e instanceof OfflineError
      ? "Esta tela precisa de internet. Sem conexão, use a tela Operação: os registros ficam salvos e sincronizam depois."
      : e.message;
    main.replaceChildren(h("div", { class: "banner" }, msg));
    if (e instanceof AuthError) promptRelogin();
  }
}

async function enterApp() {
  if (online() && tokenValid()) {
    try {
      state.me = await api("/api/auth/me");
      state.sessionAt = Date.now();
      await saveSession();
    } catch (e) {
      if (!(e instanceof OfflineError)) throw e;
    }
  }
  await refreshSnapshot();
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#who").textContent = `${state.me.name} · ${state.me.role}`;
  const allowed = Object.entries(VIEWS).filter(([, v]) => roleIs(...v.roles));
  $("#nav").replaceChildren(...allowed.map(([k, v]) => h("button", { type: "button", "data-view": k, onclick: () => go(k) }, v.label)));
  const wanted = location.hash.slice(1);
  const fallback = online() ? allowed[0][0] : "operacao";
  await go(allowed.some(([k]) => k === wanted) ? wanted : fallback);
  await renderNet();
  flush({ quiet: true });
}

async function logout() {
  const pending = state.me ? (await outbox.all()).filter((i) => i.user_id === state.me.id).length : 0;
  if (pending && !confirm(`Há ${pending} operação(ões) não sincronizada(s). Elas ficam guardadas neste aparelho e serão enviadas no seu próximo login. Sair mesmo assim?`)) return;
  Object.assign(state, { token: null, me: null, sessionAt: 0, snapshot: null });
  await kv.del("session");
  await kv.del("snapshot");  // dados de clientes não ficam no aparelho após sair
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

$("#login-form").addEventListener("submit", guard(async (ev) => {
  $("#login-error").textContent = "";
  if (!online()) { $("#login-error").textContent = "O primeiro login precisa de internet."; return; }
  try {
    const r = await api("/api/auth/login", { method: "POST", body: formData(ev.target) });
    state.token = r.access_token;
    state.sessionAt = Date.now();
    ev.target.reset();
    await enterApp();
  } catch (e) {
    $("#login-error").textContent = e.message;
  }
}));
$("#logout").addEventListener("click", () => logout());
$("#sync-now").addEventListener("click", () => (tokenValid() ? flush() : promptRelogin()));

window.addEventListener("online", () => { renderNet(); flush(); });
window.addEventListener("offline", () => { renderNet(); if (currentView === "operacao") go("operacao"); });
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") flush({ quiet: true }); });
setInterval(() => flush({ quiet: true }), SYNC_INTERVAL_MS);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((e) => console.warn("SW", e));
}

(async () => {
  try {
    if (await loadSession()) await enterApp();
    else await logout();
  } catch (e) {
    console.warn(e);
    $("#login-view").classList.remove("hidden");
  }
})();
