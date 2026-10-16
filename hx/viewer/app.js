/* hx viewer — single-file app (no build step).
 * Sections: utils · state · data index · annotations · tree · graph · detail · source · events · init
 * Modes: serve (talks to /api, live via SSE) and export (data inlined, edits downloadable). */
(() => {
"use strict";

const CFG = Object.assign({mode: "export", allow_extract: false}, window.HX_CONFIG || {});
const SERVE = CFG.mode === "serve";
const LIVE = SERVE && new URLSearchParams(location.search).get("live") !== "0";  // ?live=0 disables SSE (debug/headless)

// ------------------------------------------------------------------ utils
const $ = (sel) => document.querySelector(sel);
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "dataset") Object.assign(e.dataset, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return e;
}
const shortId = (id) => { const i = id.indexOf("::"); return i >= 0 ? id.slice(i + 2) : id; };   // first "::": C++ ids hold more
const fileOfId = (id) => { const m = /^[a-z+]+:(.*?)::/.exec(id); return m ? m[1] : null; };
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const {mergePatch, composePatch} = window.hxPatch;   // patch.js (shared with the Node tests)
function setStatus(text, isErr) { const s = $("#status"); s.textContent = text || ""; s.classList.toggle("err", !!isErr); }
const fmtTime = () => new Date().toLocaleTimeString();

// ------------------------------------------------------------------ state
const S = {
  graph: null, ann: {nodes: {}, types: {}, globals: {}, view: {hidden: [], pinned_positions: {}}}, rev: 0,
  idx: null, sel: null, history: [],
  depthMax: 3, showFiles: true, showGhosts: true, showRefs: true, layout: "LR",
  collapsed: new Set(), hidden: new Set(), treeOpen: new Set(), search: "",
  cy: null, queue: [], flushing: false, dirty: false, es: null, sourceCache: new Map(),
  graphName: "", graphs: [], diff: null, diffBase: "", history: [],
};
const api = (path, params) => { const u = new URL(path, location.origin); if (S.graphName) u.searchParams.set("name", S.graphName); for (const [k, v] of Object.entries(params || {})) if (v != null) u.searchParams.set(k, v); return u.pathname + u.search; };

// ------------------------------------------------------------------ data index
function buildIndex(g) {
  const out = {}, inc = {}, ghosts = {}, unresolvedById = {}, unresolvedByCall = {}, globalUse = {};
  for (const u of g.unresolved || []) {
    if (u.id) unresolvedById[u.id] = u;
    unresolvedByCall[u.from + "\u0000" + u.name] = u;
  }
  g.edges.forEach((e, i) => {
    e._i = i;
    (out[e.from] ||= []).push(e);
    let target = e.to;
    if (target == null) {
      target = "ghost:" + e.from + "→" + e.name;
      const u = unresolvedByCall[e.from + "\u0000" + e.name];
      ghosts[target] ||= {id: target, label: e.name, kind: "fnptr", reason: u ? u.reason : "indirect call", file: fileOfId(e.from), ptr_type: e.ptr_type};
      e._target = target;
    } else if (!g.nodes[target]) {
      const u = unresolvedById[target];
      ghosts[target] ||= {id: target, label: shortId(target), kind: "ghost", reason: u ? u.reason : "not expanded", file: fileOfId(target)};
      e._target = target;
    } else {
      e._target = target;
    }
    (inc[target] ||= []).push(e);
  });
  for (const n of Object.values(g.nodes)) {
    for (const gid of n.globals.reads) (globalUse[gid] ||= {reads: [], writes: []}).reads.push(n.id);
    for (const gid of n.globals.writes) (globalUse[gid] ||= {reads: [], writes: []}).writes.push(n.id);
  }
  let maxDepth = 0;
  for (const n of Object.values(g.nodes)) maxDepth = Math.max(maxDepth, Math.abs(n.depth));
  return {out, inc, ghosts, unresolvedById, globalUse, maxDepth};
}

function visibleSet() {
  const g = S.graph, vis = new Set([g.entry]), q = [[g.entry, 0]];
  while (q.length) {
    const [id, d] = q.shift();
    if (S.collapsed.has(id) || d >= S.depthMax) continue;
    for (const e of S.idx.out[id] || []) {
      if (e.kind === "ref" && !S.showRefs) continue;
      const t = e.to;
      if (t == null || !g.nodes[t] || vis.has(t) || S.hidden.has(t)) continue;   // hidden: neither drawn nor walked through
      vis.add(t); q.push([t, d + 1]);
    }
  }
  const q2 = [[g.entry, 0]];
  while (q2.length) {
    const [id, d] = q2.shift();
    if (d >= S.depthMax) continue;
    for (const e of S.idx.inc[id] || []) {
      const n = g.nodes[e.from];
      if (!n || n.depth >= 0 || vis.has(e.from) || S.hidden.has(e.from)) continue;
      vis.add(e.from); q2.push([e.from, d + 1]);
    }
  }
  return vis;
}

// ------------------------------------------------------------------ annotations
const annNode = (id) => S.ann.nodes[id] || {};
const annType = (id) => S.ann.types[id] || {};
const annGlobal = (id) => S.ann.globals[id] || {};
function paramDir(node, p) {
  const o = ((annNode(node.id).params || {})[p.name]) || {};
  return o.dir ? {dir: o.dir, source: "user"} : {dir: p.dir, source: p.dir_source};
}
function verifyState(node) {
  const v = annNode(node.id).verified_body_hash;
  if (!v) return "none";
  return v === node.body_hash ? "ok" : "changed";
}
function applyPatch(patch) {
  S.ann = mergePatch(S.ann, patch);
  if (SERVE) {
    // Outgoing patches are a FIFO. Adjacent patches are coalesced only when the composition is exact
    // (composePatch keeps null = delete markers; mergePatch would drop them and deletes would never persist).
    const q = S.queue;
    if (q.length) {
      try { q[q.length - 1] = composePatch(q[q.length - 1], patch); } catch (_) { q.push(patch); }
    } else {
      q.push(patch);
    }
    flushPatch();
  } else {
    S.dirty = true;
    $("#btn-download").hidden = false;
    setStatus("annotations edited (not saved) — download when done");
  }
}
const flushPatch = debounce(() => { void drainQueue(); }, 350);
async function drainQueue() {
  if (S.flushing) return;
  S.flushing = true;
  try {
    while (S.queue.length) {
      const body = S.queue[0];
      let j;
      try {
        const r = await fetch("/api/annotations", {method: "PATCH", headers: {"content-type": "application/json"}, body: JSON.stringify(body)});
        if (!r.ok) throw new Error(await r.text());
        j = await r.json();
      } catch (err) {
        setStatus("save failed: " + err.message + " — retrying", true);   // head stays queued; retry shortly
        setTimeout(flushPatch, 2000);
        return;
      }
      S.queue.shift();
      S.rev = j.rev;
      if (!S.queue.length) S.ann = j.annotations;   // adopt the server's view only once nothing is in flight
      setStatus("saved " + fmtTime());
    }
  } finally {
    S.flushing = false;
  }
}
function downloadAnnotations() {
  const blob = new Blob([JSON.stringify(S.ann, null, 2) + "\n"], {type: "application/json"});
  const a = h("a", {href: URL.createObjectURL(blob), download: "annotations.json"});
  document.body.append(a); a.click(); a.remove();
  S.dirty = false; setStatus("annotations downloaded " + fmtTime());
}

// ------------------------------------------------------------------ diff mode
function diffClass(id) {
  const d = S.diff; if (!d) return "";
  if (d.nodes.removed.includes(id)) return "d-rm";
  if (d.nodes.added.includes(id)) return "d-add";
  if (d.nodes.changed[id]) return "d-chg";
  return "";
}
function diffBadge(id) {
  const c = diffClass(id); if (!c) return null;
  const lbl = {"d-add": "+ new", "d-chg": "~ changed", "d-rm": "− removed"}[c];
  return h("span", {class: "badge " + c}, lbl);
}
async function loadHistory() {
  if (!SERVE) return;
  try {
    const hres = await fetch(api("/api/history"));
    S.history = hres.ok ? (await hres.json()).snapshots : [];
  } catch (e) { S.history = []; }
  const sel = $("#diff-base");
  const cur = S.diffBase;
  sel.replaceChildren(h("option", {value: ""}, S.history.length ? "no diff" : "no snapshots yet"));
  for (const sn of [...S.history].reverse()) sel.append(h("option", {value: sn.ts}, "vs " + snapshotLabel(sn)));
  sel.value = S.history.some((x) => x.ts === cur) ? cur : "";
  if (sel.value !== cur) { S.diffBase = sel.value; }
}
function snapshotLabel(sn) {
  const stamp = sn.generated ? sn.generated.replace("T", " ").slice(0, 19) + " UTC" : sn.ts;
  const git = (sn.provenance || {}).git || {};
  const revision = git.commit ? git.commit.slice(0, 12) : git.status === "no-repo" ? "no Git" : "revision unknown";
  return stamp + " · " + revision + (git.dirty ? " · modified" : "");
}
function diffStamp() { return S.diff.since_generated || S.diff.since; }
async function applyDiff(base) {
  S.diffBase = base || "";
  if (!S.diffBase) { S.diff = null; renderAll(); setStatus(""); updateHash(); return; }
  try {
    const r = await fetch(api("/api/diff", {since: S.diffBase}));
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    S.diff = await r.json();
  } catch (err) { S.diff = null; setStatus("diff failed: " + err.message, true); return; }
  const s = S.diff.summary;
  const st = $("#status"); st.classList.remove("err");
  st.replaceChildren("diff vs " + diffStamp().slice(0, 19).replace("T", " ") + " · functions ",
    h("span", {class: "d-add"}, "+" + s.nodes_added), " ", h("span", {class: "d-rm"}, "−" + s.nodes_removed), " ",
    h("span", {class: "d-chg"}, "~" + s.nodes_changed), " · types ~" + s.types_changed + " · edges +" + s.edges_added + " −" + s.edges_removed);
  renderAll(); updateHash();
}
function renderAll() { renderTree(); if (S.cy) renderGraph({fit: false}); renderDetail(); }

// ------------------------------------------------------------------ hide / show (eye)
// A hidden node is removed from the drawing together with every edge touching it and everything that is only
// reachable through it (its submodules, callees, ghosts); whatever another visible node still reaches stays.
// Persisted in annotations.view.hidden (shared view state, like pinned positions); the entry cannot be hidden.
const EYE_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg>';
const EYE_CLOSED = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.9 17.9A10.9 10.9 0 0 1 12 19c-7 0-11-7-11-7a18 18 0 0 1 5.1-5.9M9.9 4.2A10.9 10.9 0 0 1 12 5c7 0 11 7 11 7a18 18 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2"/><path d="M1 1l22 22"/></svg>';
function drawnCounts() {
  const vis = visibleSet(); let edges = 0;
  for (const id of vis) for (const e of S.idx.out[id] || []) if (e.to != null && vis.has(e.to) && (S.showRefs || e.kind !== "ref")) edges++;
  return {nodes: vis.size, edges};
}
function toggleHidden(id) {
  const g = S.graph; const n = g && g.nodes[id];
  if (!n || id === g.entry) return false;
  const before = drawnCounts();
  if (S.hidden.has(id)) S.hidden.delete(id); else S.hidden.add(id);
  applyPatch({view: {hidden: [...S.hidden]}});
  const after = drawnCounts();
  renderAll();
  const dn = after.nodes - before.nodes, de = after.edges - before.edges;
  setStatus((S.hidden.has(id) ? "hidden " : "shown ") + n.name + " (" + (dn >= 0 ? "+" : "") + dn + " nodes, " + (de >= 0 ? "+" : "") + de + " edges)");
  return true;
}
function showAllHidden() {
  if (!S.hidden.size) return;
  S.hidden = new Set();
  applyPatch({view: {hidden: []}});
  renderAll();
  setStatus("all modules shown");
}
function eyeButton(id) {
  const hidden = S.hidden.has(id);
  const sp = h("span", {class: "eye", role: "button", title: hidden ? "show this module and what it reaches (h)" : "hide this module and everything only reachable through it (h)",
                        onclick: (ev) => { ev.stopPropagation(); toggleHidden(id); }});
  sp.innerHTML = hidden ? EYE_CLOSED : EYE_OPEN;
  return sp;
}
async function takeBaseline() {
  const r = await fetch(api("/api/snapshot"), {method: "POST"});
  if (!r.ok) { setStatus("baseline failed: " + r.statusText, true); return; }
  const j = await r.json();
  await loadHistory();
  setStatus("baseline " + (j.snapshot || "").slice(0, 19).replace("T", " ") + " saved");
}
function changesSection(root) {
  const d = S.diff; if (!d) return;
  root.append(h("div", {class: "tree-h"}, "changes vs " + diffStamp().slice(0, 16).replace("T", " ")));
  const row = (id, cls, label, kind, extra) => {
    const r = h("div", {class: "row " + cls + (S.sel && S.sel.id === id ? " sel" : ""), title: id, onclick: () => select(kind, id)},
      h("span", {class: "caret empty"}), h("span", {class: "nm"}, label), extra ? h("span", {class: "muted small"}, extra) : null);
    root.append(r);
  };
  for (const id of d.nodes.added) row(id, "d-add", "+ " + shortId(id), "node");
  for (const id of d.nodes.removed) row(id, "d-rm", "− " + shortId(id), "removed");
  for (const [id, ch] of Object.entries(d.nodes.changed)) {
    const what = [ch.signature ? "signature" : null, ch.body ? "body" : null, ch.globals ? "globals" : null, ch.calls ? "calls" : null, ch.moved ? "moved" : null, ch.wiring ? "wiring" : null, ch.attrs ? "attrs" : null].filter(Boolean).join(", ");
    row(id, "d-chg", "~ " + shortId(id), "node", what);
  }
  for (const id of d.types.added) row(id, "d-add", "+ " + shortId(id), "type");
  for (const id of d.types.removed) row(id, "d-rm", "− " + shortId(id), "type");
  for (const [id, ch] of Object.entries(d.types.changed)) row(id, "d-chg", "~ " + shortId(id), "type", Object.keys(ch).join(", "));
  if (!d.summary.any) root.append(h("p", {class: "muted small", style: "padding:0 6px"}, "no structural changes"));
}
function diffBlock(id) {
  const d = S.diff; if (!d) return null;
  const ch = d.nodes.changed[id] || d.types.changed[id];
  if (d.nodes.added.includes(id) || d.types.added.includes(id)) return h("div", {class: "diffbox"}, h("b", {class: "new"}, "new since " + diffStamp().slice(0, 16)));
  if (!ch) return null;
  const items = [];
  if (ch.signature) items.push(h("li", null, "signature: ", h("span", {class: "old mono"}, ch.signature.old), " → ", h("span", {class: "new mono"}, ch.signature.new)));
  for (const p of ch.params || []) items.push(h("li", null, "param " + p.name + ": " + p.change + (p.old != null ? " " + JSON.stringify(p.old) : "") + (p.new != null ? " → " + JSON.stringify(p.new) : "")));
  if (ch.returns) items.push(h("li", null, "returns: ", h("span", {class: "old"}, ch.returns.old), " → ", h("span", {class: "new"}, ch.returns.new)));
  if (ch.body) items.push(h("li", null, "body changed" + (ch.body.loc_delta != null ? " (" + (ch.body.loc_delta >= 0 ? "+" : "") + ch.body.loc_delta + " lines)" : "")));
  for (const [what, dd] of Object.entries(ch.globals || {})) items.push(h("li", null, what + ": " + (dd.added.length ? "+" + dd.added.map(shortId).join(", ") : "") + " " + (dd.removed.length ? "−" + dd.removed.map(shortId).join(", ") : "")));
  if (ch.calls) items.push(h("li", null, "calls: " + (ch.calls.added.length ? "+" + ch.calls.added.map(shortId).join(", ") : "") + " " + (ch.calls.removed.length ? "−" + ch.calls.removed.map(shortId).join(", ") : "")));
  for (const k of ["size", "align", "kind", "underlying"]) if (ch[k]) items.push(h("li", null, k + ": ", h("span", {class: "old"}, String(ch[k].old)), " → ", h("span", {class: "new"}, String(ch[k].new))));
  for (const f of ch.fields || []) items.push(h("li", null, "field " + (f.name || "(reorder)") + ": " + f.change + (f.old != null ? " " + JSON.stringify(f.old) : "") + (f.new != null ? " → " + JSON.stringify(f.new) : "")));
  for (const e of ch.enumerators || []) items.push(h("li", null, "enum " + e.name + ": " + e.change + (e.old != null ? " " + e.old : "") + (e.new != null ? " → " + e.new : "")));
  for (const w of ch.wiring || []) items.push(h("li", null, "wiring " + w.terminal + ": ", h("span", {class: "old mono"}, String(w.old)), " → ", h("span", {class: "new mono"}, String(w.new))));
  for (const [k, v] of Object.entries(ch.attrs || {})) items.push(h("li", null, "attr " + k + ": " + ("old" in v || "new" in v ? JSON.stringify(v.old) + " → " + JSON.stringify(v.new) : JSON.stringify(v))));
  if (ch.moved) items.push(h("li", null, "moved " + ch.moved.old + " → " + ch.moved.new));
  if (ch.depth && items.length === 0) items.push(h("li", null, "depth " + ch.depth.old + " → " + ch.depth.new));
  return h("div", {class: "diffbox"}, h("b", null, "changed since " + diffStamp().slice(0, 16)), h("ul", {class: "list"}, items));
}
function renderRemoved(d, id) {
  const info = (S.diff && S.diff.nodes.removed_info[id]) || {};
  d.append(navBar(h("span", {class: "muted small"}, "removed function")));
  d.append(h("h2", null, info.name || shortId(id)));
  d.append(h("div", {class: "diffbox"}, h("b", {class: "old"}, "no longer in the graph since " + diffStamp().slice(0, 16)),
    info.signature ? h("pre", {class: "sig", style: "margin-top:6px"}, info.signature) : null,
    info.loc ? h("div", {class: "muted small"}, info.loc.file + ":" + info.loc.line) : null,
    info.calls && info.calls.length ? h("div", {class: "small"}, "called: " + info.calls.map(shortId).join(", ")) : null));
}

// ------------------------------------------------------------------ selection
function select(kind, id, {push = true, fromGraph = false} = {}) {
  if (S.sel && push && (S.sel.kind !== kind || S.sel.id !== id)) S.history.push(S.sel);
  S.sel = kind ? {kind, id} : null;
  if (S.history.length > 50) S.history.shift();
  renderDetail();
  renderTree();
  if (!fromGraph && S.cy) {
    S.cy.elements().unselect();
    if (kind === "node" || kind === "ghost") { const ele = S.cy.$id(id); if (ele.length) { ele.select(); } }
  }
  updateHash();
}
function back() { const prev = S.history.pop(); if (prev) select(prev.kind, prev.id, {push: false}); }

// ------------------------------------------------------------------ tree
function kindBadge(e) {
  if (!e || e.kind === "call") return null;
  const label = {macro: "macro " + (e.macro || ""), fnptr: "fnptr", ref: "ref", instance: "instance"}[e.kind] || e.kind;
  return h("span", {class: "badge kind-" + e.kind}, label.trim());
}
function nodeBadges(n) {
  const out = [];
  const db = diffBadge(n.id); if (db) out.push(db);
  const vs = verifyState(n);
  if (vs === "ok") out.push(h("span", {class: "badge ok", title: "verified: body unchanged since you marked it"}, "✓ verified"));
  if (vs === "changed") out.push(h("span", {class: "badge chg", title: "body changed since you verified it"}, "! changed"));
  if (annNode(n.id).note) out.push(h("span", {class: "badge note", title: annNode(n.id).note}, "note"));
  for (const t of annNode(n.id).tags || []) out.push(h("span", {class: "badge"}, t));
  return out;
}
function treeRow({id, label, depthLabel, cls, edge, children, open, onToggle, kind, n, noSel = false}) {
  const selected = !noSel && S.sel && S.sel.id === id;
  const hidden = kind === "node" && S.hidden.has(id);
  const caret = h("span", {class: "caret" + (children ? "" : " empty"), onclick: (ev) => { ev.stopPropagation(); onToggle && onToggle(); }}, open ? "▾" : "▸");
  const row = h("div", {class: "row " + (cls || "") + (selected ? " sel" : "") + (hidden ? " hidden" : ""), title: id, onclick: () => select(kind, id)},
    caret, h("span", {class: "nm"}, label), kindBadge(edge),
    depthLabel != null ? h("span", {class: "badge d"}, depthLabel) : null, n ? nodeBadges(n) : null,
    kind === "node" && n && id !== S.graph.entry ? eyeButton(id) : null);
  return row;
}
function renderTree() {
  const root = $("#tree"); root.replaceChildren();
  const g = S.graph; if (!g) return;
  const q = S.search.trim().toLowerCase();
  if (q) return renderSearch(root, q);
  const entry = g.nodes[g.entry];
  changesSection(root);
  const callers = Object.values(g.nodes).filter((n) => n.depth < 0);
  if (callers.length) {
    root.append(h("div", {class: "tree-h"}, "callers"));
    const seen = new Set();
    const addCallers = (id, lvl) => {
      for (const e of S.idx.inc[id] || []) {
        const n = g.nodes[e.from];
        if (!n || n.depth >= 0 || seen.has(e.from) || lvl > S.depthMax) continue;
        seen.add(e.from);
        const key = "c:" + e.from, open = !S.treeOpen.has("!" + key);
        const row = treeRow({id: e.from, label: n.name, depthLabel: n.depth, cls: "caller", edge: e, kind: "node", n,
          children: (S.idx.inc[e.from] || []).some((x) => g.nodes[x.from] && g.nodes[x.from].depth < 0), open,
          onToggle: () => { toggleTree("!" + key); }});
        row.style.paddingLeft = (4 + lvl * 14) + "px";
        root.append(row);
        if (open) addCallers(e.from, lvl + 1);
      }
    };
    addCallers(g.entry, 0);
  }
  root.append(h("div", {class: "tree-h"}, "hierarchy"));
  if (!entry) { root.append(h("p", {class: "muted"}, "entry node missing")); return; }
  const walk = (id, lvl, path, viaEdge) => {
    const n = g.nodes[id];
    const kids = (S.idx.out[id] || []).filter((e) => S.showRefs || e.kind !== "ref");
    const hidden = S.hidden.has(id);
    const hasKids = kids.length > 0 && lvl < S.depthMax && !hidden;
    const key = id + "@" + lvl;
    const open = hasKids && !S.treeOpen.has("!" + key) && !S.collapsed.has(id) && lvl < 2 || (S.treeOpen.has(key) && !hidden);
    const row = treeRow({id, label: n.name, depthLabel: n.depth, cls: id === g.entry ? "entry" : "", edge: viaEdge, kind: "node", n,
      children: hasKids, open, onToggle: () => toggleTree(key, open)});
    row.style.paddingLeft = (4 + lvl * 14) + "px";
    root.append(row);
    if (!open) return;
    const seenHere = new Set();
    for (const e of kids) {
      const t = e._target;
      if (seenHere.has(t)) continue; seenHere.add(t);
      if (g.nodes[t]) {
        if (path.has(t)) {
          const r = treeRow({id: t, label: g.nodes[t].name + " ↺", depthLabel: null, cls: "muted", edge: e, kind: "node"});
          r.style.paddingLeft = (4 + (lvl + 1) * 14) + "px"; r.title = "recursion"; root.append(r);
        } else {
          walk(t, lvl + 1, new Set([...path, t]), e);
        }
      } else if (S.showGhosts) {
        const gh = S.idx.ghosts[t];
        const r = treeRow({id: t, label: gh.label, cls: "ghost", edge: e, kind: "ghost"});
        r.style.paddingLeft = (4 + (lvl + 1) * 14) + "px";
        r.title = gh.reason; root.append(r);
      }
    }
  };
  walk(g.entry, 0, new Set([g.entry]), null);
  if (S.hidden.size) {
    root.append(h("div", {class: "tree-h"}, "hidden (" + S.hidden.size + ")",
      h("span", {class: "link small", style: "margin-left:8px; text-transform:none", title: "show every hidden module", onclick: showAllHidden}, "show all")));
    for (const id of [...S.hidden].sort()) {
      const n = g.nodes[id]; if (!n) continue;
      const r = treeRow({id, label: n.qualname || n.name, depthLabel: n.depth, cls: "", kind: "node", n, noSel: true});
      r.style.paddingLeft = "18px"; root.append(r);
    }
  }
  const unres = g.unresolved || [];
  if (unres.length) {
    const byReason = {};
    for (const u of unres) (byReason[u.reason] ||= []).push(u);
    root.append(h("div", {class: "tree-h"}, "unresolved (" + unres.length + ")"));
    for (const [reason, items] of Object.entries(byReason)) {
      const key = "u:" + reason, open = S.treeOpen.has(key);
      const row = h("div", {class: "row", onclick: () => toggleTree(key, open)},
        h("span", {class: "caret"}, open ? "▾" : "▸"), h("span", {class: "small"}, reason), h("span", {class: "badge d"}, items.length));
      root.append(row);
      if (open) for (const u of items) {
        const r = h("div", {class: "row ghost", style: "padding-left:18px", title: "from " + u.from + (u.loc ? " @ " + u.loc.file + ":" + u.loc.line : ""),
          onclick: () => select(u.id && S.idx.ghosts[u.id] ? "ghost" : "node", u.id && S.idx.ghosts[u.id] ? u.id : u.from)},
          h("span", {class: "caret empty"}), h("span", {class: "nm"}, u.name), h("span", {class: "small muted"}, "← " + shortId(u.from)));
        root.append(r);
      }
    }
  }
}
function toggleTree(key, isOpen) {
  if (key.startsWith("!")) { S.treeOpen.has(key) ? S.treeOpen.delete(key) : S.treeOpen.add(key); }
  else if (isOpen) { S.treeOpen.delete(key); S.treeOpen.add("!" + key); }
  else { S.treeOpen.delete("!" + key); S.treeOpen.add(key); }
  renderTree();
}
function renderSearch(root, q) {
  const g = S.graph;
  const fns = Object.values(g.nodes).filter((n) => n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
  const tys = Object.values(g.types).filter((t) => t.name.toLowerCase().includes(q) || t.id.toLowerCase().includes(q));
  const gls = Object.values(g.globals).filter((v) => v.name.toLowerCase().includes(q) || v.id.toLowerCase().includes(q));
  const ghs = Object.values(S.idx.ghosts).filter((x) => x.label.toLowerCase().includes(q));
  const elementsGraph = Object.values(g.nodes).some((n) => n.kind === "device");
  root.append(h("div", {class: "tree-h"}, (elementsGraph ? "elements (" : "functions (") + fns.length + ")"));
  for (const n of fns.slice(0, 200)) root.append(treeRow({id: n.id, label: n.name, depthLabel: n.depth, cls: n.depth < 0 ? "caller" : "", kind: "node", n}));
  root.append(h("div", {class: "tree-h"}, "types (" + tys.length + ")"));
  for (const t of tys.slice(0, 200)) root.append(treeRow({id: t.id, label: (t.kind === "typedef" ? "" : t.kind + " ") + t.name, kind: "type"}));
  root.append(h("div", {class: "tree-h"}, "globals (" + gls.length + ")"));
  for (const v of gls) root.append(treeRow({id: v.id, label: v.name, kind: "global"}));
  if (ghs.length) {
    root.append(h("div", {class: "tree-h"}, "unresolved (" + ghs.length + ")"));
    for (const x of ghs.slice(0, 100)) root.append(treeRow({id: x.id, label: x.label, cls: "ghost", kind: "ghost"}));
  }
}

// ------------------------------------------------------------------ graph (cytoscape)
function depthColor(n) {
  if (n.depth < 0) return cssVar("--caller");
  return cssVar("--depth-" + Math.min(5, n.depth));
}
function buildStyle() {
  const ink = cssVar("--ink"), ink2 = cssVar("--ink-2"), surface = cssVar("--surface"), muted = cssVar("--muted"), grid = cssVar("--grid"), sel = cssVar("--sel");
  const font = cssVar("--mono") || "monospace";
  return [
    {selector: "node", style: {"shape": "round-rectangle", "background-color": surface, "border-width": 2, "border-color": "data(color)",
      "label": "data(label)", "color": ink, "font-family": font, "font-size": 11, "text-valign": "center", "text-halign": "center",
      "height": 24, "padding": "7px", "text-wrap": "none"}},
    {selector: "node[w]", style: {"width": "data(w)"}},
    {selector: "node.entry", style: {"border-width": 3, "font-weight": "bold"}},
    {selector: "node.ghost", style: {"border-style": "dashed", "border-color": muted, "color": ink2, "font-style": "italic", "background-opacity": 0}},
    {selector: "node.collapsed", style: {"border-style": "double", "border-width": 4}},
    {selector: "node:parent", style: {"shape": "round-rectangle", "background-color": ink, "background-opacity": 0.04, "border-width": 1, "border-color": grid,
      "label": "data(label)", "color": muted, "font-size": 10, "font-family": font, "text-valign": "top", "text-halign": "center", "text-margin-y": -2, "padding": "12px"}},
    {selector: "node:selected", style: {"border-color": sel, "border-width": 3, "overlay-opacity": 0}},
    {selector: "node.changed", style: {"underlay-color": cssVar("--warn"), "underlay-opacity": 0.35, "underlay-padding": 3}},
    {selector: "node.d-add", style: {"underlay-color": cssVar("--good"), "underlay-opacity": 0.35, "underlay-padding": 4}},
    {selector: "node.d-chg", style: {"underlay-color": cssVar("--warn"), "underlay-opacity": 0.45, "underlay-padding": 4}},
    {selector: "node.d-rm", style: {"border-color": cssVar("--crit"), "color": cssVar("--crit"), "border-style": "dashed"}},
    {selector: "edge.d-add", style: {"width": 3, "line-color": cssVar("--good"), "target-arrow-color": cssVar("--good")}},
    {selector: "edge.d-rm", style: {"width": 2, "line-style": "dashed", "line-color": cssVar("--crit"), "target-arrow-color": cssVar("--crit"), "opacity": 0.8}},
    // Orthogonal routing with rounded corners: edges leave along the layout's rank direction, turn 90° (radius 8px)
    // and re-route live while a node is dragged. Parallel edges between the same pair turn at staggered distances
    // (data.pi / data.pn) so they do not collapse into one line; self-loops keep the bezier loop shape.
    {selector: "edge", style: {"curve-style": "round-taxi", "taxi-direction": S.layout === "TB" ? "downward" : "rightward",
      // turn shortly after leaving the source: the cross run then lies in the gap between ranks instead of on the
      // next rank's nodes (taxi edges do not avoid obstacles); parallel edges stagger by 10px
      "taxi-turn": (ele) => `${22 + 10 * (ele.data("pi") || 0)}px`,
      "taxi-turn-min-distance": 10, "taxi-radius": 8,
      "width": 1.5, "line-color": "data(color)", "target-arrow-color": "data(color)",
      "target-arrow-shape": "triangle", "arrow-scale": 0.8, "line-style": "solid", "opacity": 0.9}},
    {selector: "edge:loop", style: {"curve-style": "bezier", "loop-direction": S.layout === "TB" ? "-45deg" : "45deg", "loop-sweep": "-60deg"}},
    {selector: "edge[kind='macro']", style: {"line-style": "dashed", "line-dash-pattern": [6, 3]}},
    {selector: "edge[kind='fnptr']", style: {"line-style": "dotted"}},
    {selector: "edge[kind='ref']", style: {"line-style": "dashed", "line-dash-pattern": [8, 3, 2, 3], "target-arrow-shape": "circle"}},
    {selector: "edge[kind='instance']", style: {"width": 2, "target-arrow-shape": "diamond", "arrow-scale": 1}},
    {selector: "edge.ghostedge", style: {"opacity": 0.6}},
    {selector: "edge:selected", style: {"width": 3, "line-color": sel, "target-arrow-color": sel}},
    {selector: "edge.hl", style: {"width": 3}},
    {selector: ".dim", style: {"opacity": 0.25}},
  ];
}
const labelWidth = (text) => Math.max(28, Math.round(text.length * 6.7) + 6);  // 11px monospace ≈ 6.7px per glyph
function edgeColor(kind) { return cssVar({macro: "--edge-macro", fnptr: "--edge-fnptr", ref: "--edge-ref", instance: "--ink-2"}[kind] || "--edge-call"); }
const BIT_LANGS = new Set(["sv", "vhdl"]);
const sizeUnit = (t) => BIT_LANGS.has(t.lang) ? "b" : "";
function buildElements() {
  const g = S.graph, vis = visibleSet(), els = [], parents = new Set();
  // In a hierarchy graph (HDL) a file's module instances and that module's own functions/tasks get SEPARATE groups.
  // A group mixing an instance with its module's routine, joined by a call edge, is exactly what makes dagre's
  // ranker throw on nested compounds (CVA6 at depth 3; tests/fixtures/viewer/layout-fail.json).
  const hierarchical = Object.values(g.nodes).some((n) => n.kind === "module" || n.kind === "instance" || n.kind === "device");
  const parentFor = (file, kind) => {
    if (!S.showFiles || !file) return undefined;
    const routine = hierarchical && (kind === "function" || kind === "task");
    const pid = "file:" + file + (routine ? "#functions" : "");
    if (!parents.has(pid)) { parents.add(pid); els.push({data: {id: pid, label: file + (routine ? " · functions" : "")}, classes: "file", selectable: false}); }
    return pid;
  };
  for (const id of vis) {
    const n = g.nodes[id];
    const cls = [id === g.entry ? "entry" : "", S.collapsed.has(id) ? "collapsed" : "", verifyState(n) === "changed" ? "changed" : "", diffClass(id)].filter(Boolean).join(" ");
    els.push({data: {id, label: n.name, w: labelWidth(n.name), color: depthColor(n), parent: parentFor(n.loc.file, n.kind), kind: "node"}, classes: cls});
  }
  const ghostAdded = new Set();
  for (const id of vis) {
    for (const e of S.idx.out[id] || []) {
      if (e.kind === "ref" && !S.showRefs) continue;
      const t = e._target;
      let isGhost = !g.nodes[t];
      if (isGhost) {
        if (!S.showGhosts || S.collapsed.has(id)) continue;
        if (!ghostAdded.has(t)) {
          ghostAdded.add(t);
          const gh = S.idx.ghosts[t];
          els.push({data: {id: t, label: gh.label, w: labelWidth(gh.label), color: cssVar("--muted"), parent: parentFor(gh.file), kind: "ghost"}, classes: "ghost"});
        }
      } else if (!vis.has(t)) continue;
      els.push({data: {id: "e" + e._i, source: id, target: t, kind: e.kind, color: edgeColor(e.kind), ei: e._i}, classes: isGhost ? "ghostedge" : ""});
    }
  }
  tagParallelEdges(els);
  if (S.diff) {
    const info = S.diff.nodes.removed_info || {};
    for (const id of S.diff.nodes.removed) {
      const inf = info[id] || {};
      els.push({data: {id, label: inf.name || shortId(id), w: labelWidth(inf.name || shortId(id)), color: cssVar("--crit"), parent: parentFor(inf.loc && inf.loc.file), kind: "removed"}, classes: "ghost d-rm"});
    }
    const present = new Set(els.filter((e) => !e.data.source).map((e) => e.data.id));
    S.diff.edges.removed.forEach((e, i) => {
      if (present.has(e.from) && present.has(e.to)) els.push({data: {id: "rm" + i, source: e.from, target: e.to, kind: e.kind, color: cssVar("--crit"), ei: -1}, classes: "d-rm"});
    });
    for (const e of S.diff.edges.added) {
      // mark the matching live edges as added
      for (const el of els) if (el.data.source === e.from && el.data.target === e.to && el.data.kind === e.kind) el.classes = (el.classes || "") + " d-add";
    }
  }
  return els;
}
// Test hook (also handy in the console): HX_TEST.lastLayout tells a genuine dagre layout from a fallback;
// HX_TEST.failLayouts = n makes the next n layout attempts throw so the fallback paths can be exercised.
const HX_TEST = window.HX_TEST = Object.assign({failLayouts: 0, lastLayout: null, ranker: null, layoutErrors: []}, window.HX_TEST || {});
function runLayout(fit = true) {
  const cy = S.cy;
  const dagreOpts = {name: "dagre", rankDir: S.layout, nodeSep: 18, rankSep: 60, edgeSep: 8, animate: false, fit: false, padding: 30, nodeDimensionsIncludeLabels: true};
  const flat = () => {   // dagre without compound (file) parents: lift children out, lay out, put them back
    const moved = cy.nodes().children().map((n) => [n, n.data("parent")]);
    moved.forEach(([n]) => n.move({parent: null}));
    return () => moved.forEach(([n, par]) => n.move({parent: par}));
  };
  // dagre's default network-simplex ranker throws "Not possible to find intersection inside of the rectangle" on
  // some nested-compound graphs (CVA6 at depth 3; reproduced with dagre 0.8.5 and 1.1.4 — tests/fixtures/viewer/
  // layout-fail.json). The longest-path ranker lays out the same elements, file groups intact, so it is tried
  // before any flattening. Both are "dagre" layouts; HX_TEST.ranker records which one ran.
  const attempts = [["dagre", "network-simplex", dagreOpts, null], ["dagre", "longest-path", {...dagreOpts, ranker: "longest-path"}, null],
                    ["dagre-flat", "network-simplex", dagreOpts, flat],
                    ["breadthfirst", null, {name: "breadthfirst", directed: true, roots: cy.$id(S.graph.entry), spacingFactor: 1.1, animate: false, fit: false, padding: 30}, null]];
  let done = false;
  for (const [name, ranker, opts, prep] of attempts) {
    let restore = null;
    try {
      if (HX_TEST.failLayouts > 0) { HX_TEST.failLayouts--; throw new Error("injected layout failure"); }
      restore = prep ? prep() : null;
      cy.layout(opts).run();
      HX_TEST.lastLayout = name; HX_TEST.ranker = ranker;
      if (name !== "dagre") notice("layout fallback: " + name + " (dagre failed: " + HX_TEST.layoutErrors[HX_TEST.layoutErrors.length - 1] + ")");
      done = true;
    } catch (err) {
      HX_TEST.layoutErrors.push(String((err && err.message) || err));
      console.warn("layout " + name + " failed:", err);
    } finally {
      if (restore) { try { restore(); } catch (e) { /* ignore */ } }
    }
    if (done) break;
  }
  if (!done) { HX_TEST.lastLayout = null; notice("layout failed: " + HX_TEST.layoutErrors.slice(-1)[0]); }
  const pins = (S.ann.view && S.ann.view.pinned_positions) || {};
  for (const [id, p] of Object.entries(pins)) { const ele = cy.$id(id); if (ele.length && !ele.isParent()) ele.position(p); }
  if (fit) cy.fit(undefined, 30);
}
function tagParallelEdges(els) {
  // pi = index among edges that share (source, target) in either direction, pn = their count → staggered taxi turns
  const groups = new Map();
  for (const el of els) {
    if (!el.data.source || el.data.source === el.data.target) continue;
    const k = [el.data.source, el.data.target].sort().join("\u0000");
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(el);
  }
  for (const grp of groups.values()) grp.forEach((el, i) => { el.data.pi = i; el.data.pn = grp.length; });
}

function renderGraph({fit = true} = {}) {
  if (!S.cy) {
    S.cy = cytoscape({container: $("#cy"), style: buildStyle(), minZoom: 0.1, maxZoom: 4, boxSelectionEnabled: false});
    bindGraphEvents(S.cy);
  }
  const cy = S.cy;
  cy.startBatch();
  cy.elements().remove();
  cy.add(buildElements());
  cy.endBatch();
  runLayout(fit);
  if (S.sel && (S.sel.kind === "node" || S.sel.kind === "ghost" || S.sel.kind === "removed")) { const ele = cy.$id(S.sel.id); if (ele.length) ele.select(); }
}
function bindGraphEvents(cy) {
  const tip = $("#edge-tip");
  cy.on("tap", "node", (evt) => {
    const d = evt.target.data();
    if (evt.target.isParent()) return;
    select(d.kind === "ghost" ? "ghost" : (d.kind === "removed" ? "removed" : "node"), d.id, {fromGraph: true});
  });
  cy.on("dbltap", "node", (evt) => { const d = evt.target.data(); if (d.kind === "node") toggleCollapse(d.id); });
  cy.on("tap", "edge", (evt) => { const ei = evt.target.data("ei"); if (ei >= 0) select("edge", String(ei), {fromGraph: true}); });
  cy.on("tap", (evt) => { if (evt.target === cy) { select(null, null); } });
  cy.on("mouseover", "edge", (evt) => {
    const e = S.graph.edges[evt.target.data("ei")];
    if (!e) { tip.replaceChildren(h("div", {class: "k"}, "edge removed since baseline")); tip.hidden = false; return; }
    tip.replaceChildren(
      h("div", null, h("span", {class: "k"}, e.kind + (e.macro ? " via " + e.macro : "") + " → "), h("b", null, e.name || shortId(e.to || ""))),
      e.args && e.args.length ? h("div", {class: "mono"}, "(" + e.args.join(", ") + ")") : null,
      e.loc ? h("div", {class: "k"}, e.loc.file + ":" + e.loc.line) : null,
      e.ptr_type ? h("div", {class: "k"}, "pointer type " + e.ptr_type) : null);
    tip.hidden = false;
    evt.target.addClass("hl");
  });
  cy.on("mousemove", "edge", (evt) => { const p = evt.renderedPosition || evt.position; tip.style.left = (p.x + 14) + "px"; tip.style.top = (p.y + 14) + "px"; });
  cy.on("mouseout", "edge", (evt) => { tip.hidden = true; evt.target.removeClass("hl"); });
  cy.on("mouseover", "node", (evt) => {
    const d = evt.target.data(); if (evt.target.isParent()) return;
    const n = S.graph.nodes[d.id];
    const gh = S.idx.ghosts[d.id];
    tip.replaceChildren(n ? h("div", {class: "mono"}, n.signature) : h("div", null, h("span", {class: "k"}, gh ? gh.reason : "removed since baseline")),
      n ? h("div", {class: "k"}, n.loc.file + ":" + n.loc.line + " · depth " + n.depth) : null);
    const p = evt.renderedPosition; tip.style.left = (p.x + 14) + "px"; tip.style.top = (p.y + 14) + "px"; tip.hidden = false;
  });
  cy.on("mouseout", "node", () => { tip.hidden = true; });
  cy.on("dragfree", "node", (evt) => {
    if (evt.target.isParent()) return;
    const p = evt.target.position();
    applyPatch({view: {pinned_positions: {[evt.target.id()]: {x: Math.round(p.x), y: Math.round(p.y)}}}});
  });
}
function toggleCollapse(id) {
  const now = !S.collapsed.has(id);
  if (now) S.collapsed.add(id); else S.collapsed.delete(id);
  applyPatch({nodes: {[id]: {collapsed: now ? true : null}}});
  renderGraph({fit: false}); renderTree();
}

// ------------------------------------------------------------------ detail
function typeLink(ref, text) {
  if (!ref) return h("span", {class: "mono"}, text);
  const exists = !!S.graph.types[ref];
  return h("span", {class: "mono " + (exists ? "link" : "muted"), title: exists ? ref : ref + " (not expanded: raise --type-depth)", onclick: exists ? () => select("type", ref) : null}, text);
}
function nodeLink(id, text) {
  const n = S.graph.nodes[id];
  if (n) return h("span", {class: "mono link", title: id, onclick: () => select("node", id)}, text || n.name);
  const gh = S.idx.ghosts[id];
  if (gh) return h("span", {class: "mono link muted", title: id + " — " + gh.reason, onclick: () => select("ghost", id)}, text || gh.label);
  return h("span", {class: "mono muted", title: id}, text || shortId(id));
}
function globalLink(id) { const v = S.graph.globals[id]; return h("span", {class: "mono link", title: id, onclick: () => select("global", id)}, v ? v.name : shortId(id)); }
function navBar(...extra) {
  return h("div", {class: "nav"}, h("button", {onclick: back, disabled: !S.history.length, title: "back"}, "←"), ...extra);
}
function noteBox(current, onChange) {
  return h("textarea", {class: "note", placeholder: "notes (markdown-ish, saved per symbol id)", onchange: (ev) => onChange(ev.target.value.trim() || null)}, current || "");
}
function renderDetail() {
  const d = $("#detail"); d.replaceChildren();
  if (!S.sel) { d.append(h("p", {class: "muted"}, "Select a function in the tree or graph. Double-click a node to collapse its subtree; drag to pin; the eye on a tree row (or h) hides a module and everything only reachable through it.")); return; }
  const {kind, id} = S.sel;
  if (kind === "node") renderNode(d, S.graph.nodes[id]);
  else if (kind === "type") renderType(d, S.graph.types[id]);
  else if (kind === "global") renderGlobal(d, S.graph.globals[id]);
  else if (kind === "ghost") renderGhost(d, S.idx.ghosts[id]);
  else if (kind === "edge") renderEdge(d, S.graph.edges[Number(id)]);
  else if (kind === "removed") renderRemoved(d, id);
  if (!d.childNodes.length) d.append(h("p", {class: "muted"}, "not in this graph: " + id));
}
function renderNode(d, n) {
  if (!n) return;
  const a = annNode(n.id);
  const vs = verifyState(n);
  d.append(navBar(h("span", {class: "muted small"}, n.kind + (n.storage ? " · " + n.storage : "") + " · depth " + n.depth + " · " + n.precision),
    n.id !== S.graph.entry ? h("button", {class: "hide-btn", title: "h", onclick: () => toggleHidden(n.id)}, S.hidden.has(n.id) ? "show module" : "hide module") : null));
  d.append(h("h2", null, n.qualname));
  d.append(h("div", {class: "meta"},
    h("span", {class: "link mono", title: "show source", onclick: () => showSource(n)}, n.loc.file + ":" + n.loc.line + (n.loc.end_line ? "–" + n.loc.end_line : "")),
    h("span", {class: "muted mono small", title: "body hash (whitespace-insensitive)"}, (n.body_hash || "").slice(5, 13))));
  d.append(h("pre", {class: "sig"}, n.signature));
  if (n.kind === "device" && n.attrs) d.append(h("div", {style: "margin-top:4px"}, h("span", {class: "badge kind-device"}, (n.attrs.family || "?") + " " + (n.attrs.element || "")),
    n.attrs.guard ? h("span", {class: "badge", title: "conditional branch (guard id " + (n.attrs.guard_id || "") + ")"}, "if " + n.attrs.guard) : null));
  const dbn = diffBlock(n.id); if (dbn) d.append(dbn);
  if (n.attrs && Object.keys(n.attrs).length) d.append(attrsBlock(n.attrs));
  d.append(h("div", {class: "verify", style: "margin-top:8px"},
    h("label", null, h("input", {type: "checkbox", checked: vs !== "none", onchange: (ev) => { applyPatch({nodes: {[n.id]: {verified_body_hash: ev.target.checked ? n.body_hash : null}}}); rerenderSoft(); }}), " verified"),
    vs === "ok" ? h("span", {class: "badge ok"}, "✓ unchanged since verified") : null,
    vs === "changed" ? h("span", {class: "badge chg", title: "verified " + a.verified_body_hash}, "! body changed since verified") : null));
  if (n.params.length) {
    d.append(h("h3", null, n.kind === "device" ? "terminals" : (n.lang === "sp" ? "ports" : "parameters")));
    d.append(h("table", {class: "t"}, h("thead", null, h("tr", null, h("th", null, "name"), h("th", null, "type"), h("th", {title: "click to override; heuristic = guessed from constness"}, "dir"), h("th", null, "note"))),
      h("tbody", null, n.params.map((p) => {
        const pd = paramDir(n, p);
        const pnote = ((a.params || {})[p.name] || {}).note || "";
        return h("tr", null, h("td", {class: "mono"}, p.name), h("td", null, typeLink(p.type_ref, p.type)),
          h("td", null, h("span", {class: "chip " + pd.dir + (pd.source === "user" ? " user" : ""), title: "source: " + pd.source + " (click to cycle in → out → inout → reset)", onclick: () => cycleDir(n, p)}, pd.dir)),
          h("td", null, h("input", {class: "tags", value: pnote, placeholder: "…", onchange: (ev) => applyPatch({nodes: {[n.id]: {params: {[p.name]: {note: ev.target.value.trim() || null}}}}})})));
      }))));
  }
  const tt = terminalsTable(n); if (tt) d.append(tt);
  if (n.returns || !["module", "instance", "task", "device"].includes(n.kind)) d.append(h("h3", null, "returns"), h("div", null, typeLink(n.returns && n.returns.type_ref, n.returns ? n.returns.type : "void")));
  if (n.globals.reads.length || n.globals.writes.length) {
    d.append(h("h3", null, "globals"));
    d.append(h("dl", {class: "kv"},
      h("dt", null, "reads"), h("dd", null, n.globals.reads.length ? n.globals.reads.map((g, i) => [i ? ", " : "", globalLink(g)]) : "—"),
      h("dt", null, "writes"), h("dd", null, n.globals.writes.length ? n.globals.writes.map((g, i) => [i ? ", " : "", globalLink(g)]) : "—")));
  }
  const out = S.idx.out[n.id] || [];
  if (out.length) {
    d.append(h("h3", null, "calls (" + out.length + ")"));
    d.append(h("ul", {class: "list"}, out.map((e) => h("li", null, nodeLink(e._target, e.name || shortId(e.to || "")), kindBadge(e),
      h("span", {class: "args"}, e.args && e.args.length ? "(" + e.args.join(", ") + ")" : ""),
      e.loc ? h("span", {class: "muted small link", onclick: () => showSource(n, e.loc.line)}, ":" + e.loc.line) : null))));
  }
  const inc = S.idx.inc[n.id] || [];
  if (inc.length) {
    d.append(h("h3", null, "called by (" + inc.length + ")"));
    d.append(h("ul", {class: "list"}, inc.map((e) => h("li", null, nodeLink(e.from), kindBadge(e), h("span", {class: "args"}, e.args && e.args.length ? "(" + e.args.join(", ") + ")" : ""),
      e.loc ? h("span", {class: "muted small"}, e.loc.file + ":" + e.loc.line) : null))));
  }
  const unres = (S.graph.unresolved || []).filter((u) => u.from === n.id);
  if (unres.length) {
    d.append(h("h3", null, "not expanded from here"));
    d.append(h("ul", {class: "list"}, unres.map((u) => h("li", null, h("span", {class: "mono"}, u.name), h("span", {class: "muted small"}, u.reason)))));
  }
  d.append(h("h3", null, "notes"));
  d.append(noteBox(a.note, (v) => { applyPatch({nodes: {[n.id]: {note: v}}}); renderTree(); }));
  d.append(h("input", {class: "tags", style: "margin-top:6px", placeholder: "tags, comma separated", value: (a.tags || []).join(", "),
    onchange: (ev) => { const tags = ev.target.value.split(",").map((s) => s.trim()).filter(Boolean); applyPatch({nodes: {[n.id]: {tags: tags.length ? tags : null}}}); renderTree(); }}));
  d.append(h("h3", null, "source"));
  const holder = h("div", {id: "source-holder"});
  d.append(holder);
  if (SERVE) showSource(n); else holder.append(h("p", {class: "muted small"}, "source snippets are available in `hx serve` mode"));
}
// Wide values arrive as canonical strings (hx/values.py); show them compact, keep the lossless text in the tooltip.
function fmtValue(v) {
  if (v === null || v === undefined) return "?";
  const s = String(v);
  if (s.length <= 24) return s;
  const m = /^(\d*'[sS]?[bodhBODH]|-?0[xX])(.*)$/.exec(s);
  const short = m && m[2].length > 12 ? m[1] + m[2].slice(0, 8) + "…" + m[2].slice(-4) : s.slice(0, 23) + "…";
  return h("span", {class: "mono", title: s + " (" + s.length + " chars)"}, short);
}
function terminalsTable(n) {
  // Netlist graphs: the circuit block maps a device's terminals and an instance's ports to nets (hx/3 `circuit`).
  const c = S.graph.circuit; if (!c) return null;
  const rows = n.kind === "device" ? (c.terminals || {})[n.id] : (c.ports || {})[n.id];
  if (!rows || !rows.length) return null;
  const isDev = n.kind === "device";
  return h("div", null, h("h3", null, isDev ? "terminals → nets" : "ports → nets"),
    h("table", {class: "t"}, h("thead", null, h("tr", null, h("th", null, isDev ? "terminal" : "port"), h("th", null, "net"), h("th", null, "as written"))),
      h("tbody", null, rows.map((r) => h("tr", null, h("td", {class: "mono"}, isDev ? r.terminal : r.port),
        // the outermost net reached through the enclosing instances' bindings, with the net in this scope when it differs
        h("td", {class: "mono"}, isDev ? (r.canonical && r.canonical !== r.net ? r.canonical + " (via " + r.net + ")" : r.net) : r.net + (r.outer !== r.net ? " (via " + r.outer + ")" : "")),
        h("td", {class: "mono muted"}, r.as_written))))));
}
function attrsBlock(attrs) {
  const dl = h("dl", {class: "kv", style: "margin-top:8px"});
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || (Array.isArray(v) && !v.length) || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length)) continue;
    let val;
    if (k === "signals" && Array.isArray(v)) val = h("details", null, h("summary", {class: "link small"}, v.length + " internal signals"),
      h("ul", {class: "list"}, v.map((sg) => h("li", null, h("span", {class: "mono"}, sg.name), h("span", {class: "muted small"}, sg.type)))));
    else if (Array.isArray(v) && v.length && v.every((x) => x && typeof x === "object" && ("key" in x || "target" in x)))
      val = v.map((x, i) => [i ? ", " : null, x.target ? nodeLink(x.target, x.as_written || shortId(x.target)) : h("span", {class: "mono"}, x.key + (x.guard_id ? "#" + x.guard_id : ""))]).flat().filter((x) => x !== null);
    else if (typeof v === "object" && !Array.isArray(v)) val = Object.entries(v).flatMap(([pk, pv], i) => [i ? ", " : null, pk + "=", fmtValue(pv)]).filter((x) => x !== null);
    else if (Array.isArray(v)) val = v.map((x) => typeof x === "object" ? JSON.stringify(x) : String(x)).join(", ");
    else val = String(v);
    dl.append(h("dt", null, k), h("dd", null, val));
  }
  return dl;
}
function cycleDir(n, p) {
  const cur = paramDir(n, p);
  const order = ["in", "out", "inout"];
  let next;
  if (cur.source !== "user") next = order[(order.indexOf(cur.dir) + 1) % 3];
  else { const i = order.indexOf(cur.dir); next = order[(i + 1) % 3]; if (next === p.dir) next = null; }
  applyPatch({nodes: {[n.id]: {params: {[p.name]: {dir: next}}}}});
  renderDetail();
}
function rerenderSoft() { renderTree(); renderDetail(); if (S.cy) renderGraph({fit: false}); }
function fieldsTable(t, depth = 0, seen = new Set()) {
  const a = annType(t.id);
  const rows = t.fields.map((f) => {
    const sub = f.type_ref && S.graph.types[f.type_ref];
    const key = f.name || "(anon)";
    const note = ((a.fields || {})[key] || {}).note || "";
    const bits = BIT_LANGS.has(t.lang);
    const offCell = bits ? (f.bit_offset != null && f.bit_width != null ? "[" + (f.bit_offset + f.bit_width - 1) + ":" + f.bit_offset + "]" : "") : (f.offset != null ? f.offset : "");
    const sizeCell = bits ? (f.bit_width != null ? f.bit_width + "b" : "") : (f.size != null ? f.size : (f.bit_width != null ? f.bit_width + "b@" + f.bit_offset : ""));
    const tr = h("tr", null, h("td", {class: "mono"}, f.name || h("i", {class: "muted"}, "(anonymous)")), h("td", null, typeLink(f.type_ref, f.type)),
      h("td", {class: "num"}, offCell), h("td", {class: "num"}, sizeCell),
      h("td", null, h("input", {class: "tags", value: note, placeholder: "…", onchange: (ev) => applyPatch({types: {[t.id]: {fields: {[key]: {note: ev.target.value.trim() || null}}}}})})));
    if (sub && sub.fields && sub.fields.length && depth < 3 && !seen.has(sub.id)) {
      const nested = h("tr", null, h("td", {colspan: 5}, h("div", {class: "fields-nested"}, fieldsTable(sub, depth + 1, new Set([...seen, t.id])))));
      return [tr, nested];
    }
    return tr;
  });
  const bitsHdr = BIT_LANGS.has(t.lang);
  return h("table", {class: "t"}, h("thead", null, h("tr", null, h("th", null, "field"), h("th", null, "type"), h("th", null, bitsHdr ? "bits" : "off"), h("th", null, bitsHdr ? "width" : "size"), h("th", null, "note"))), h("tbody", null, rows));
}
function renderType(d, t) {
  if (!t) return;
  const a = annType(t.id);
  d.append(navBar(h("span", {class: "muted small"}, t.kind + (t.system ? " · system header" : "") + (t.anonymous ? " · anonymous" : ""))));
  d.append(h("h2", null, (t.kind === "typedef" ? "" : t.kind + " ") + t.name));
  d.append(h("div", {class: "meta"}, t.loc ? h("span", {class: "mono"}, t.loc.file + ":" + t.loc.line) : null,
    t.size != null ? h("span", null, "size ", h("b", {class: "mono"}, t.size + sizeUnit(t)), t.align != null ? [" align ", h("b", {class: "mono"}, t.align)] : null) : h("span", {class: "muted"}, "size unknown")));
  const dbt = diffBlock(t.id); if (dbt) d.append(dbt);
  if (t.kind === "typedef") {
    d.append(h("h3", null, "alias of"));
    d.append(h("div", null, typeLink(t.underlying_ref, t.underlying || "?")));
    const u = t.underlying_ref && S.graph.types[t.underlying_ref];
    if (u && u.fields && u.fields.length) { d.append(h("h3", null, "fields of " + u.kind + " " + u.name)); d.append(fieldsTable(u)); }
  }
  if (t.fields && t.fields.length) { d.append(h("h3", null, "fields")); d.append(fieldsTable(t)); }
  else if (t.kind !== "typedef" && t.kind !== "enum") d.append(h("p", {class: "muted small"}, t.system ? "fields omitted for system types (use --include-system)" : "no fields recorded (incomplete type?)"));
  if (t.enumerators && t.enumerators.length) {
    d.append(h("h3", null, "enumerators" + (t.underlying ? " (" + t.underlying + ")" : "")));
    d.append(h("table", {class: "t"}, h("tbody", null, t.enumerators.map((e) => h("tr", null, h("td", {class: "mono"}, e.name), h("td", {class: "num"}, e.value))))));
  }
  if (t.used_by && t.used_by.length) { d.append(h("h3", null, "used by")); d.append(h("ul", {class: "list"}, t.used_by.map((id) => h("li", null, nodeLink(id))))); }
  const users = Object.values(S.graph.types).filter((x) => x.underlying_ref === t.id || (x.fields || []).some((f) => f.type_ref === t.id));
  if (users.length) { d.append(h("h3", null, "referenced from types")); d.append(h("ul", {class: "list"}, users.map((x) => h("li", null, typeLink(x.id, (x.kind === "typedef" ? "" : x.kind + " ") + x.name))))); }
  d.append(h("h3", null, "notes"));
  d.append(noteBox(a.note, (v) => applyPatch({types: {[t.id]: {note: v}}})));
}
function renderGlobal(d, v) {
  if (!v) return;
  const use = S.idx.globalUse[v.id] || {reads: [], writes: []};
  d.append(navBar(h("span", {class: "muted small"}, "global · " + v.scope + " · " + (v.storage || ""))));
  d.append(h("h2", null, v.name));
  d.append(h("div", {class: "meta"}, v.loc ? h("span", {class: "mono"}, v.loc.file + ":" + v.loc.line) : null));
  d.append(h("dl", {class: "kv"}, h("dt", null, "type"), h("dd", null, typeLink(v.type_ref, v.type)),
    h("dt", null, "read by"), h("dd", null, use.reads.length ? use.reads.map((id, i) => [i ? ", " : "", nodeLink(id)]) : "—"),
    h("dt", null, "written by"), h("dd", null, use.writes.length ? use.writes.map((id, i) => [i ? ", " : "", nodeLink(id)]) : "—")));
  d.append(h("p", {class: "muted small"}, "writes are approximate: assignment targets, ++/--, compound assignment and address-taken count as writes."));
  d.append(h("h3", null, "notes"));
  d.append(noteBox(annGlobal(v.id).note, (val) => applyPatch({globals: {[v.id]: {note: val}}})));
}
function renderGhost(d, gh) {
  if (!gh) return;
  d.append(navBar(h("span", {class: "muted small"}, "unresolved")));
  d.append(h("h2", null, gh.label));
  d.append(h("div", {class: "warnbox"}, h("b", null, gh.reason), gh.ptr_type ? h("div", {class: "mono small"}, "pointer type: " + gh.ptr_type) : null,
    gh.kind === "ghost" ? h("div", {class: "mono small muted"}, gh.id) : null));
  const inc = S.idx.inc[gh.id] || [];
  if (inc.length) {
    d.append(h("h3", null, "reached from"));
    d.append(h("ul", {class: "list"}, inc.map((e) => h("li", null, nodeLink(e.from), kindBadge(e), h("span", {class: "args"}, e.args && e.args.length ? "(" + e.args.join(", ") + ")" : ""), e.loc ? h("span", {class: "muted small"}, e.loc.file + ":" + e.loc.line) : null))));
  }
  const hint = {"beyond depth limit": "raise the depth slider or re-extract with a larger --depth", "no definition in TU set": "the definition is not in any translation unit of compile_commands.json (library, other build config, or weak symbol)",
    "system header excluded": "re-extract with --include-system to expand", "indirect call through function pointer": "static analysis cannot resolve the target; check `ref` edges for candidate callbacks", "excluded by filter": "matched an --exclude glob"}[gh.reason];
  if (hint) d.append(h("p", {class: "muted small"}, hint));
}
function renderEdge(d, e) {
  if (!e) return;
  d.append(navBar(h("span", {class: "muted small"}, "edge · " + e.kind)));
  d.append(h("h2", null, shortId(e.from), " → ", e.name || shortId(e.to || "?")));
  d.append(h("dl", {class: "kv"}, h("dt", null, "from"), h("dd", null, nodeLink(e.from)), h("dt", null, "to"), h("dd", null, nodeLink(e._target)),
    h("dt", null, "kind"), h("dd", null, e.kind + (e.macro ? " via macro " + e.macro : "")),
    h("dt", null, "args"), h("dd", null, e.args && e.args.length ? e.args.join(", ") : "—"),
    h("dt", null, "site"), h("dd", null, e.loc ? e.loc.file + ":" + e.loc.line : "?"), e.ptr_type ? [h("dt", null, "pointer"), h("dd", null, e.ptr_type)] : null));
  const n = S.graph.nodes[e.from];
  if (n && SERVE && e.loc) { d.append(h("h3", null, "source")); d.append(h("div", {id: "source-holder"})); showSource(n, e.loc.line); }
}

// ------------------------------------------------------------------ source
async function showSource(n, hlLine) {
  const holder = $("#source-holder"); if (!holder || !SERVE) return;
  let start = Math.max(1, n.loc.line), end = n.loc.end_line || n.loc.line + 30;
  let span = Math.min(400, end - start + 1);
  if (hlLine && (hlLine < start || hlLine > start + span - 1 || end - start + 1 > 400)) { start = Math.max(1, hlLine - 60); span = 120; }   // navigate to a distant call site
  const key = n.loc.file + ":" + start + ":" + span;
  try {
    let data = S.sourceCache.get(key);
    if (!data) {
      const r = await fetch(api("/api/source", {file: n.loc.file, line: start, span}));
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      data = await r.json(); S.sourceCache.set(key, data);
    }
    const siteLines = new Set((S.idx.out[n.id] || []).filter((e) => e.loc && e.loc.file === n.loc.file).map((e) => e.loc.line));
    holder.replaceChildren(h("div", {class: "src"}, data.lines.map((text, i) => {
      const ln = data.start + i;
      return h("div", {class: "ln" + (ln === hlLine ? " hl" : "") + (siteLines.has(ln) ? " site" : ""), title: siteLines.has(ln) ? "call site" : null}, h("span", {class: "n"}, ln), h("pre", null, text || " "));
    })));
    if (hlLine) { const el = holder.querySelector(".ln.hl"); if (el) el.scrollIntoView({block: "center"}); }
  } catch (err) {
    holder.replaceChildren(h("div", {class: "errbox"}, "source unavailable: " + err.message));
  }
}

// ------------------------------------------------------------------ hash / events / loading
function updateHash() {
  const p = new URLSearchParams();
  if (S.sel) { p.set("sel", S.sel.id); p.set("kind", S.sel.kind); }
  p.set("depth", S.depthMax); p.set("layout", S.layout);
  if (S.graphName) p.set("graph", S.graphName);
  if (S.diffBase) p.set("diff", S.diffBase);
  history.replaceState(null, "", "#" + p.toString());
}
function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  if (p.get("depth")) S.depthMax = Number(p.get("depth"));
  if (p.get("layout")) S.layout = p.get("layout");
  if (p.get("graph")) S.graphName = p.get("graph");
  if (p.get("diff")) S.diffBase = p.get("diff").replace(/ /g, "+");   // a hand-typed '+' in the hash arrives as a space
  return p.get("sel") ? {kind: p.get("kind") || "node", id: p.get("sel")} : null;
}
async function loadData() {
  if (SERVE) {
    try { S.graphs = await (await fetch("/api/graphs")).json(); } catch (e) { S.graphs = []; }
    if (S.graphName && !S.graphs.some((x) => x.name === S.graphName)) S.graphName = "";
    const pick = $("#graph-pick");
    pick.replaceChildren(...S.graphs.map((x) => h("option", {value: x.name}, x.name + "  (" + shortId(x.entry || "") + ", " + x.nodes + ")")));
    pick.hidden = S.graphs.length < 2;
    if (!S.graphName && S.graphs.length) S.graphName = S.graphs[0].name;
    pick.value = S.graphName;
    const [g, a] = await Promise.all([fetch(api("/api/graph")).then((r) => { if (!r.ok) throw new Error("graph: " + r.status); return r.json(); }),
      fetch("/api/annotations").then((r) => r.json())]);
    S.graph = g; S.ann = a.annotations; S.rev = a.rev;
    await loadHistory();
  } else {
    S.graph = JSON.parse($("#hx-graph").textContent);
    const a = JSON.parse($("#hx-annotations").textContent || "{}");
    S.ann = Object.assign({nodes: {}, types: {}, globals: {}, view: {hidden: [], pinned_positions: {}}}, a);
  }
  S.idx = buildIndex(S.graph);
  S.collapsed = new Set(Object.entries(S.ann.nodes).filter(([, v]) => v.collapsed).map(([k]) => k));
  S.hidden = new Set(((S.ann.view && S.ann.view.hidden) || []).filter((id) => S.graph.nodes[id] && id !== S.graph.entry));
  const slider = $("#depth"); slider.max = Math.max(1, S.idx.maxDepth); if (S.depthMax > Number(slider.max)) S.depthMax = Number(slider.max); slider.value = S.depthMax; $("#depth-val").textContent = S.depthMax;
  $("#entry-label").textContent = S.graph.entry;
  $("#entry-label").title = S.graph.entry + " · " + snapshotLabel({generated: S.graph.generated, ts: "", provenance: (S.graph.meta || {}).provenance});
  document.title = "hx · " + shortId(S.graph.entry);
}
function notice(text) {   // persistent notice in the banner strip (the status line is overwritten by later events)
  const b = $("#banner"); if (!b) { setStatus(text, true); return; }
  const line = h("div", {class: "notice"}, text);
  const old = [...b.querySelectorAll(".notice")].find((x) => x.textContent === text);
  if (!old) b.append(line);
  b.hidden = false;
}
function showMigrationBanner() {
  const b = $("#banner"); if (!b) return;
  const mig = (S.graph && S.graph.meta && S.graph.meta.migration) || null;
  b.querySelectorAll(".migration").forEach((x) => x.remove());
  if (mig && mig.needs_reextract_total) {
    b.append(h("div", {class: "migration"}, h("span", null, "This graph was written by hx schema " + mig.from + " and upgraded in memory; " + mig.needs_reextract_total +
      " type id(s) can only be settled by re-extraction. Run "), h("code", null, "hx migrate"), h("span", null, " in the project to re-extract tracked entries and carry annotations over.")));
  }
  b.hidden = !b.children.length;
}
async function reloadGraph() {
  const keep = S.sel;
  await loadData();
  showMigrationBanner();
  renderTree(); renderGraph({fit: false});
  if (keep) select(keep.kind, keep.id, {push: false}); else renderDetail();
  S.sourceCache.clear();
  if (S.diffBase) await applyDiff(S.diffBase);
  else setStatus("graph reloaded " + fmtTime() + " · " + Object.keys(S.graph.nodes).length + " nodes");
}
async function switchGraph(name) {
  S.graphName = name; S.diff = null; S.diffBase = ""; S.sel = null; S.history = []; S.collapsed = new Set(); S.hidden = new Set();
  await loadData();
  renderTree(); renderGraph(); renderDetail(); updateHash();
  setStatus("");
}
function connectEvents() {
  if (!LIVE || !window.EventSource) return;
  const es = new EventSource("/events"); S.es = es;
  es.addEventListener("graph", (ev) => {
    let name = null; try { name = JSON.parse(ev.data).name; } catch (e) { /* ignore */ }
    if (name && S.graphName && name !== S.graphName) { setStatus("graph " + name + " updated " + fmtTime()); return; }
    reloadGraph().catch((e) => setStatus("reload failed: " + e.message, true));
  });
  es.addEventListener("annotations", async (ev) => {
    const rev = JSON.parse(ev.data).rev;
    if (rev === S.rev || S.queue.length || S.flushing) return;   // our own write, or ours still in flight
    const a = await (await fetch("/api/annotations")).json();
    S.ann = a.annotations; S.rev = a.rev; rerenderSoft(); setStatus("annotations updated elsewhere " + fmtTime());
  });
  es.addEventListener("extract-start", () => { setStatus("re-extracting…"); $("#btn-extract").disabled = true; });
  es.addEventListener("extract-done", () => { loadHistory(); });
  es.addEventListener("extract-done", (ev) => { const d = JSON.parse(ev.data); setStatus("extracted " + d.nodes + " nodes " + fmtTime()); $("#btn-extract").disabled = false; });
  es.addEventListener("extract-error", (ev) => { setStatus("extract failed: " + JSON.parse(ev.data).error, true); $("#btn-extract").disabled = false; });
  es.onerror = () => setStatus("live connection lost; retrying…", true);
  es.addEventListener("hello", () => { if ($("#status").classList.contains("err")) setStatus(""); });
}
function bindUI() {
  $("#search").addEventListener("input", (ev) => { S.search = ev.target.value; renderTree(); });
  $("#search").addEventListener("keydown", (ev) => { if (ev.key === "Enter") { const first = $("#tree .row"); if (first) first.click(); } if (ev.key === "Escape") { ev.target.value = ""; S.search = ""; renderTree(); ev.target.blur(); } });
  $("#depth").addEventListener("input", (ev) => { S.depthMax = Number(ev.target.value); $("#depth-val").textContent = S.depthMax; renderTree(); renderGraph(); updateHash(); });
  $("#opt-files").addEventListener("change", (ev) => { S.showFiles = ev.target.checked; renderGraph(); });
  $("#opt-ghosts").addEventListener("change", (ev) => { S.showGhosts = ev.target.checked; renderTree(); renderGraph(); });
  $("#opt-refs").addEventListener("change", (ev) => { S.showRefs = ev.target.checked; renderTree(); renderGraph(); });
  $("#layout").value = S.layout;
  $("#layout").addEventListener("change", (ev) => { S.layout = ev.target.value; renderGraph(); updateHash(); });
  $("#btn-fit").addEventListener("click", () => S.cy && S.cy.fit(undefined, 30));
  $("#btn-relayout").addEventListener("click", () => { applyPatch({view: {pinned_positions: null}}); S.ann.view = S.ann.view || {}; S.ann.view.pinned_positions = {}; renderGraph(); });
  const bx = $("#btn-extract");
  if (!SERVE || !CFG.allow_extract) bx.hidden = true;
  bx.addEventListener("click", async () => { bx.disabled = true; const r = await fetch(api("/api/extract"), {method: "POST"}); if (!r.ok && r.status !== 202) { setStatus("extract: " + (await r.json()).detail, true); bx.disabled = false; } });
  $("#graph-pick").addEventListener("change", (ev) => switchGraph(ev.target.value));
  $("#diff-base").addEventListener("change", (ev) => applyDiff(ev.target.value));
  const bb = $("#btn-baseline");
  if (!SERVE) { bb.hidden = true; $("#diff-base").hidden = true; }
  bb.addEventListener("click", takeBaseline);
  $("#btn-download").addEventListener("click", downloadAnnotations);
  $("#btn-theme").addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme || "auto";
    const next = {auto: "light", light: "dark", dark: "auto"}[cur];
    if (next === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = next;
    try { localStorage.setItem("hx-theme", next); } catch (e) { /* private mode */ }
    if (S.cy) { S.cy.style(buildStyle()); renderGraph({fit: false}); }
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (S.cy) { S.cy.style(buildStyle()); renderGraph({fit: false}); } });
  document.addEventListener("keydown", (ev) => {
    if (ev.target.matches("input, textarea, select")) return;
    if (ev.key === "/") { ev.preventDefault(); $("#search").focus(); }
    else if (ev.key === "f") S.cy && S.cy.fit(undefined, 30);
    else if (ev.key === "h") { if (S.sel && S.sel.kind === "node") toggleHidden(S.sel.id); }
    else if (ev.key === "Escape") select(null, null);
    else if (ev.key === "Backspace") back();
  });
  for (const sp of document.querySelectorAll(".splitter")) {
    sp.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      const pane = $("#" + sp.dataset.pane), left = sp.dataset.pane === "left", startX = ev.clientX, startW = pane.getBoundingClientRect().width;
      const move = (e) => { pane.style.width = Math.max(160, startW + (left ? 1 : -1) * (e.clientX - startX)) + "px"; S.cy && S.cy.resize(); };
      const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
      window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
    });
  }
  window.addEventListener("beforeunload", (ev) => { if (!SERVE && S.dirty) { ev.preventDefault(); ev.returnValue = ""; } });
}
async function init() {
  const forced = new URLSearchParams(location.search).get("theme");   // ?theme=dark|light wins over the stored choice
  if (forced === "dark" || forced === "light") document.documentElement.dataset.theme = forced;
  else { try { const t = localStorage.getItem("hx-theme"); if (t && t !== "auto") document.documentElement.dataset.theme = t; } catch (e) { /* ignore */ } }
  const initialSel = readHash();
  bindUI();
  try { await loadData(); } catch (err) { $("#detail").replaceChildren(h("div", {class: "errbox"}, "failed to load graph: " + err.message)); setStatus(String(err.message), true); return; }
  showMigrationBanner();
  try { renderTree(); renderGraph(); } catch (err) { console.error(err); setStatus("render failed: " + err.message, true); }
  try { if (initialSel) select(initialSel.kind, initialSel.id, {push: false}); else renderDetail(); } catch (err) { console.error(err); }
  if (SERVE && S.diffBase) { try { $("#diff-base").value = S.diffBase; await applyDiff(S.diffBase); } catch (err) { console.error(err); } }
  connectEvents();
  if (!SERVE) setStatus("static export · generated " + S.graph.generated);
}
window.HX_DEBUG = {buildElements, visibleSet, buildStyle, buildIndex, toggleHidden, showAllHidden, hidden: () => S.hidden, state: () => S,   // hooks for tests and bisection
  setGraph: (g) => { S.graph = g; S.idx = buildIndex(g); S.collapsed = new Set(); S.hidden = new Set(); S.depthMax = 99; S.diff = null; }};
init();
})();
