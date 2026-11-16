// GasControl SPA. Regra de segurança: nenhum dado do servidor é inserido via innerHTML.
// Todo texto passa por textContent (h()), eliminando XSS refletido/armazenado.
"use strict";

const TOKEN_KEY = "gc_token";
const QR_PREFIX = "GC1:";
const state = { token: sessionStorage.getItem(TOKEN_KEY), me: null, gases: [], customers: [] };

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
const fmtDT = (d) => (d ? new Date(d.endsWith("Z") || d.includes("+") ? d : d + "Z").toLocaleString("pt-BR") : "—");
const roleIs = (...r) => state.me && (state.me.role === "ADMIN" || r.includes(state.me.role));
const cleanSerial = (s) => String(s || "").trim().toUpperCase().replace(QR_PREFIX, "");

function toast(msg, isErr = false) {
  const t = h("div", { class: "toast" + (isErr ? " err" : "") }, msg);
  $("#toast").append(t);
  setTimeout(() => t.remove(), isErr ? 7000 : 3500);
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") out[el.name] = el.checked;
    else if (el.value === "") continue;
    else if (el.type === "number" || el.dataset.int !== undefined) out[el.name] = Number(el.value);
    else out[el.name] = el.value.trim();
  }
  return out;
}

async function api(path, { method = "GET", body, raw = false } = {}) {
  const headers = { Accept: "application/json" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 15000);
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body),
                              signal: ctrl.signal, credentials: "omit" });
  } catch (e) {
    throw new Error(e.name === "AbortError" ? "Tempo de resposta esgotado" : "Falha de rede");
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401 && path !== "/api/auth/login") {
    logout();
    throw new Error("Sessão expirada");
  }
  if (raw) return res;
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
    try { await fn(ev); } catch (e) { toast(e.message, true); } finally { if (btn) btn.disabled = false; }
  };
}

function table(headers, rows) {
  return h("table", {}, h("thead", {}, h("tr", {}, headers.map((x) => h("th", {}, x)))),
    h("tbody", {}, rows.length ? rows.map((r) => h("tr", {}, r.map((c) => h("td", {}, c))))
                                : h("tr", {}, h("td", { colspan: headers.length, class: "muted" }, "Nenhum registro"))));
}

function gasSelect(name = "gas_type_id", filterCat = null) {
  return h("select", { name, required: true, "data-int": "" },
    state.gases.filter((g) => !filterCat || g.category === filterCat)
      .map((g) => h("option", { value: g.id }, `${g.code} — ${g.name}`)));
}

function customerSelect(name = "customer_id", required = true) {
  return h("select", { name, required, "data-int": "" }, h("option", { value: "" }, "— selecione o cliente —"),
    state.customers.filter((c) => c.active).map((c) => h("option", { value: c.id }, `${c.name} (${c.document})`)));
}

async function refreshRefs() {
  [state.gases, state.customers] = await Promise.all([api("/api/gas-types"), api("/api/customers?limit=200")]);
}

// ---------------- leitor de QR (câmera) ----------------
async function scanInto(input) {
  if (!("BarcodeDetector" in window)) {
    toast("Navegador sem leitor nativo; use leitor USB/Bluetooth ou digite o número de série.", true);
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
    toast("Câmera indisponível: " + e.message, true);
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
  operacao: { label: "Operação", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewOperation },
  cilindros: { label: "Cilindros", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewCylinders },
  clientes: { label: "Clientes", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewCustomers },
  lotes: { label: "Lotes", roles: ["GESTOR", "OPERADOR"], render: viewLots },
  historico: { label: "Movimentações", roles: ["GESTOR", "OPERADOR", "MOTORISTA"], render: viewMovements },
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
        table(["Cliente", "Cilindros", "Comodato"], d.customer_balance.map((r) => [r.customer, r.cylinders, r.loans])) ),
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
  const lots = roleIs("GESTOR", "OPERADOR") ? await api("/api/lots?limit=200") : [];
  const usableLots = lots.filter((l) => l.status !== "REPROVADO");
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
    if (t === "ENVASE") extra.append(h("label", {}, "Lote (obrigatório para medicinal)",
      h("select", { name: "lot_id", "data-int": "" }, h("option", { value: "" }, "— sem lote (industrial) —"),
        usableLots.map((l) => h("option", { value: l.id }, `${l.code} · ${l.gas_type.code} · ${l.status}`)))));
    if (t === "RETORNO_MANUTENCAO") extra.append(h("label", {}, "Novo teste hidrostático (se realizado)", h("input", { type: "date", name: "new_hydro_test" })));
    if (["ENTREGA", "COLETA"].includes(t)) extra.append(h("label", {}, "NF-e / romaneio", h("input", { name: "document_ref", maxlength: 60 })));
  };
  typeSel.addEventListener("change", renderExtra);
  renderExtra();

  const single = h("form", { class: "card", onsubmit: guard(async (ev) => {
    const body = formData(ev.target);
    body.serial = cleanSerial(body.serial);
    Object.assign(body, await geo());
    const m = await api("/api/movements", { method: "POST", body });
    toast(`${m.type}: ${m.cylinder.serial} → ${m.to_status}`);
    ev.target.serial.value = "";
    ev.target.serial.focus();
  }) },
    h("h2", {}, "Movimentação de cilindro"),
    h("label", {}, "Operação", typeSel), serialField("serial", "Cilindro"), extra,
    h("label", {}, "Observações", h("textarea", { name: "notes", maxlength: 1000, rows: 2 })),
    h("button", { type: "submit" }, "Registrar"));

  const exchange = h("form", { class: "card", onsubmit: guard(async (ev) => {
    const body = formData(ev.target);
    body.full_serial = cleanSerial(body.full_serial);
    body.empty_serial = cleanSerial(body.empty_serial);
    Object.assign(body, await geo());
    await api("/api/movements/exchange", { method: "POST", body });
    toast(`Troca registrada: entregue ${body.full_serial}, recolhido ${body.empty_serial}`);
    ev.target.reset();
  }) },
    h("h2", {}, "Troca (entrega cheio + recolhe vazio)"),
    h("label", {}, "Cliente", customerSelect()),
    serialField("full_serial", "Cilindro CHEIO entregue"), serialField("empty_serial", "Cilindro VAZIO recolhido"),
    h("label", {}, h("input", { type: "checkbox", name: "is_loan" }), "Comodato"),
    h("label", {}, "NF-e / romaneio", h("input", { name: "document_ref", maxlength: 60 })),
    h("button", { type: "submit" }, "Registrar troca"));

  main.append(h("div", { class: "cols" }, single, exchange));
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
        h("button", { class: "sm ghost", onclick: () => showHistory(c.serial) }, "Rastrear")])));
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
          h("p", {}, `${hist.cylinder.gas_type.name} · ${hist.cylinder.capacity_liters} L · último teste ${fmtDate(hist.cylinder.last_hydro_test)}`)),
        h("div", { style: null }, h("img", { class: "qr", src: url, alt: `QR ${serial}` }),
          h("button", { class: "sm ghost", onclick: () => window.print() }, "Imprimir etiqueta"))),
      table(["Data", "Operação", "De → Para", "Cliente", "Lote", "Usuário", "Doc.", "Hash"],
        hist.movements.map((m) => [fmtDT(m.occurred_at), m.type, `${m.from_status || "—"} → ${m.to_status}`,
          m.customer ? m.customer.name : "—", m.lot ? m.lot.code : "—", m.user.name, m.document_ref || "—",
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
      await load();
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
  await refreshRefs();
  const list = h("div");
  const render = () => list.replaceChildren(table(["Nome", "CPF/CNPJ", "Telefone", "Estab. saúde", "Ativo", ""],
    state.customers.map((c) => [c.name, c.document, c.phone || "—", c.is_health_facility ? "Sim" : "Não", c.active ? "Sim" : "Não",
      h("button", { class: "sm ghost", onclick: guard(async () => {
        const rows = await api(`/api/cylinders?customer_id=${c.id}&limit=500`);
        toast(`${c.name}: ${rows.length} cilindro(s) em posse — ${rows.map((r) => r.serial).join(", ") || "nenhum"}`);
      }) }, "Saldo")])));
  if (roleIs("GESTOR", "OPERADOR")) {
    main.append(h("form", { class: "card", onsubmit: guard(async (ev) => {
      await api("/api/customers", { method: "POST", body: formData(ev.target) });
      toast("Cliente cadastrado");
      ev.target.reset();
      await refreshRefs();
      render();
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
  render();
}

async function viewLots(main) {
  const list = h("div");
  const trace = h("div");
  const load = async () => {
    const lots = await api("/api/lots?limit=200");
    list.replaceChildren(table(["Lote", "Gás", "Produção", "Validade", "Laudo", "Status", ""],
      lots.map((l) => [l.code, l.gas_type.code, fmtDate(l.production_date), fmtDate(l.expiry_date), l.analysis_report || "—", badge(l.status),
        h("span", {},
          l.status === "QUARENTENA" && roleIs("GESTOR") ? [
            h("button", { class: "sm", onclick: guard(() => decide(l.id, true)) }, "Aprovar"), " ",
            h("button", { class: "sm danger", onclick: guard(() => decide(l.id, false)) }, "Reprovar"), " "] : null,
          h("button", { class: "sm ghost", onclick: guard(() => showTrace(l.id)) }, "Recall"))])));
  };
  const decide = async (id, approve) => {
    const notes = prompt(approve ? "Observação da liberação (responsável técnico):" : "Motivo da reprovação:");
    if (notes === null) return;
    await api(`/api/lots/${id}/decision`, { method: "POST", body: { approve, notes: notes || null } });
    toast(approve ? "Lote aprovado" : "Lote reprovado");
    await load();
  };
  const showTrace = async (id) => {
    const t = await api(`/api/lots/${id}/trace`);
    trace.replaceChildren(h("div", { class: "card" }, h("h2", {}, `Recall do lote ${t.lot.code}`),
      table(["Data", "Operação", "Cilindro", "Cliente", "Usuário"],
        t.movements.map((m) => [fmtDT(m.occurred_at), m.type, m.cylinder.serial, m.customer ? m.customer.name : "—", m.user.name]))));
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
  const box = h("div", { class: "card" }, h("h2", {}, roleIs("GESTOR", "OPERADOR") ? "Últimas movimentações" : "Minhas movimentações"),
    table(["Data", "Operação", "Cilindro", "De → Para", "Cliente", "Lote", "Usuário", "Doc."],
      rows.map((m) => [fmtDT(m.occurred_at), m.type, m.cylinder.serial, `${m.from_status || "—"} → ${m.to_status}`,
        m.customer ? m.customer.name : "—", m.lot ? m.lot.code : "—", m.user.name, m.document_ref || "—"])));
  main.append(box);
  if (roleIs("GESTOR")) {
    const out = h("p", { class: "muted" });
    main.append(h("div", { class: "card" }, h("h2", {}, "Integridade da trilha de auditoria"),
      h("button", { onclick: guard(async () => {
        const r = await api("/api/audit/verify");
        out.textContent = r.ok ? `✔ Íntegra — ${r.movements_checked} movimentações verificadas`
                               : `✖ Adulteração detectada em ${r.broken.length} cilindro(s): ${JSON.stringify(r.broken)}`;
      }) }, "Verificar cadeia de hashes"), out));
  }
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
async function go(key) {
  const view = VIEWS[key];
  const main = $("#main");
  main.replaceChildren(h("p", { class: "muted" }, "Carregando…"));
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === key));
  location.hash = key;
  try {
    const frag = h("div");
    await view.render(frag);
    main.replaceChildren(...frag.childNodes);
  } catch (e) {
    main.replaceChildren(h("p", { class: "error" }, e.message));
  }
}

async function enterApp() {
  state.me = await api("/api/auth/me");
  await refreshRefs();
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#who").textContent = `${state.me.name} · ${state.me.role}`;
  const allowed = Object.entries(VIEWS).filter(([, v]) => roleIs(...v.roles));
  $("#nav").replaceChildren(...allowed.map(([k, v]) => h("button", { type: "button", "data-view": k, onclick: () => go(k) }, v.label)));
  const wanted = location.hash.slice(1);
  go(allowed.some(([k]) => k === wanted) ? wanted : allowed[0][0]);
}

function logout() {
  state.token = null;
  state.me = null;
  sessionStorage.removeItem(TOKEN_KEY);
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

$("#login-form").addEventListener("submit", guard(async (ev) => {
  $("#login-error").textContent = "";
  try {
    const r = await api("/api/auth/login", { method: "POST", body: formData(ev.target) });
    state.token = r.access_token;
    sessionStorage.setItem(TOKEN_KEY, r.access_token);
    ev.target.reset();
    await enterApp();
  } catch (e) {
    $("#login-error").textContent = e.message;
  }
}));
$("#logout").addEventListener("click", logout);

if (state.token) enterApp().catch(logout); else logout();
