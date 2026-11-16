// IndexedDB mínimo (sem dependências). Stores:
//  kv      -> sessão, snapshot de referência
//  outbox  -> operações aguardando envio (chave: client_uuid)
//  failed  -> operações recusadas pelo servidor (para revisão humana; nunca somem sozinhas)
"use strict";
const DB_NAME = "gascontrol";
const DB_VERSION = 1;
let dbPromise = null;

function open() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
      if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "client_uuid" });
      if (!db.objectStoreNames.contains("failed")) db.createObjectStore("failed", { keyPath: "client_uuid" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

async function tx(store, mode, fn) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const s = t.objectStore(store);
    let result;
    Promise.resolve(fn(s)).then((r) => { result = r; });
    t.oncomplete = () => resolve(result);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error || new Error("transação abortada"));
  });
}

const wrap = (req) => new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); });

export const kv = {
  get: (key) => tx("kv", "readonly", (s) => wrap(s.get(key))),
  set: (key, value) => tx("kv", "readwrite", (s) => { s.put(value, key); }),
  del: (key) => tx("kv", "readwrite", (s) => { s.delete(key); }),
};

function storeApi(name) {
  return {
    all: () => tx(name, "readonly", (s) => wrap(s.getAll())),
    put: (item) => tx(name, "readwrite", (s) => { s.put(item); }),
    del: (key) => tx(name, "readwrite", (s) => { s.delete(key); }),
    count: () => tx(name, "readonly", (s) => wrap(s.count())),
  };
}
export const outbox = storeApi("outbox");
export const failed = storeApi("failed");

// Move atomicamente da fila para "recusadas".
export async function moveToFailed(item, error) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(["outbox", "failed"], "readwrite");
    t.objectStore("outbox").delete(item.client_uuid);
    t.objectStore("failed").put({ ...item, error, failed_at: new Date().toISOString() });
    t.oncomplete = () => resolve();
    t.onerror = () => reject(t.error);
  });
}

export async function retryFailed(item) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(["outbox", "failed"], "readwrite");
    t.objectStore("failed").delete(item.client_uuid);
    const { error, failed_at, ...clean } = item;
    t.objectStore("outbox").put({ ...clean, attempts: 0 });
    t.oncomplete = () => resolve();
    t.onerror = () => reject(t.error);
  });
}
