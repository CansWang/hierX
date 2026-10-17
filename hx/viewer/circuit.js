/* Pure circuit queries shared by served/export viewers and Node regression tests. */
(function (root) {
  "use strict";
  function connections(g) {
    const out = [], c = g.circuit || {};
    for (const [table, kind] of [["terminals", "terminal"], ["ports", "port"]]) {
      for (const [node, rows] of Object.entries(c[table] || {})) {
        const n = g.nodes[node] || {}, attrs = n.attrs || {};
        for (const r of rows) out.push({node, kind, terminal: r[kind], net: kind === "terminal" ? r.net : r.inner,
          canonical: r.canonical || r.net, outer: r.outer || null, guard_id: attrs.guard_id || null,
          guard: attrs.guard_constraints || [], loc: n.loc});
      }
    }
    return out;
  }
  function getNet(g, key, node = "") {
    const c = g.circuit || {}, record = (c.nets || {})[key];
    if (!record) return null;
    const rows = connections(g), direct = rows.filter(r => [r.net, r.canonical, r.outer].includes(key) && (!node || r.node === node));
    const canonical = new Set(direct.map(r => r.canonical));
    if (!node) for (const b of record.bindings || []) if (b.canonical) canonical.add(b.canonical);
    if (!canonical.size) canonical.add(key);
    const guard = Object.fromEntries((((g.nodes[node] || {}).attrs || {}).guard_constraints || []).map(g => [g.chain, g.branch]));
    const results = rows.filter(r => canonical.has(r.canonical) && r.guard.every(g => !(g.chain in guard) || guard[g.chain] === g.branch));
    const aliases = [...new Set([...results.map(r => r.net), ...canonical])].filter(Boolean).sort();
    const legacy = Object.values(g.nodes).some(n => n.attrs && n.attrs.guard_id && !("guard_constraints" in n.attrs));
    return {key, record, canonical: [...canonical].sort(), aliases, results, total: results.length,
      notice: legacy ? "Legacy graph lacks guard constraints; re-extract to filter conditional alternatives." : ""};
  }
  const api = {connections, getNet};
  root.hxCircuit = api;
  if (typeof module !== "undefined") module.exports = api;
})(typeof window === "undefined" ? globalThis : window);
