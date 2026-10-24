/* Hx architecture geometry adapter and SVG presentation. No D2 parsing here. */
(function (global) {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const opt = "org.eclipse.elk.";
  const textWidth = (text, bold = false) => {
    const ctx = document.createElement("canvas").getContext("2d");
    ctx.font = (bold ? "bold 16px" : "13px") + " Arial";
    return Math.ceil(ctx.measureText(text).width);
  };
  function layoutGraph(doc) {
    const root = {id: "root", children: [], edges: [], layoutOptions: {
      [opt + "algorithm"]: "layered", [opt + "direction"]: "RIGHT",
      [opt + "edgeRouting"]: "ORTHOGONAL", [opt + "hierarchyHandling"]: "INCLUDE_CHILDREN",
      [opt + "spacing.nodeNode"]: "60", [opt + "layered.spacing.nodeNodeBetweenLayers"]: "90",
      [opt + "layered.mergeHierarchyEdges"]: "false", [opt + "padding"]: "[top=40,left=40,bottom=40,right=40]"
    }};
    const nodes = new Map(), owners = new Map(doc.blocks.map(b => [b.id, b.parent]));
    for (const block of doc.blocks) {
      const ports = doc.ports.filter(p => p.block === block.id);
      const inputs = ports.filter(p => p.direction === "in"), outputs = ports.filter(p => p.direction === "out");
      const iw = Math.max(0, ...inputs.map(p => textWidth(p.label))), ow = Math.max(0, ...outputs.map(p => textWidth(p.label)));
      const node = {id: "b:" + block.id, hx: block, width: Math.max(180, iw + ow + 90, textWidth(block.label, true) + 36),
        height: Math.max(110, Math.max(inputs.length, outputs.length) * 34 + 60), children: [], edges: [],
        layoutOptions: {[opt + "portConstraints"]: "FIXED_ORDER", [opt + "portLabels.placement"]: "INSIDE",
          [opt + "padding"]: `[top=60,left=${iw + 45},bottom=45,right=${ow + 45}]`,
          // Leave room for hinted glyph bounds when fit-to-window scales text.
          [opt + "spacing.labelPortHorizontal"]: "8",
          [opt + "spacing.portPort"]: "24", [opt + "spacing.nodeNode"]: "60", [opt + "layered.spacing.nodeNodeBetweenLayers"]: "90"},
        ports: ports.map((p, i) => ({id: "p:" + p.id, hx: p, width: 10, height: 10,
          labels: [{id: "pl:" + p.id, text: p.label, width: textWidth(p.label), height: 16}],
          layoutOptions: {[opt + "port.side"]: p.direction === "in" ? "WEST" : "EAST",
            [opt + "port.borderOffset"]: "-5", [opt + "port.index"]: String(i)}}))};
      nodes.set(block.id, node);
    }
    for (const block of doc.blocks) (block.parent ? nodes.get(block.parent) : root).children.push(nodes.get(block.id));
    const ports = new Map(doc.ports.map(p => [p.id, p]));
    function ancestors(id) { const out = []; while (id != null) { out.push(id); id = owners.get(id); } out.push(null); return out; }
    for (const e of doc.connections) {
      const a = ports.get(e.source), b = ports.get(e.target), aa = new Set(ancestors(a.block));
      const owner = ancestors(b.block).find(x => aa.has(x));
      const target = owner == null ? root : nodes.get(owner);
      target.edges.push({id: "e:" + e.id, hx: e, sources: ["p:" + e.source], targets: ["p:" + e.target],
        labels: e.label ? [{id: "el:" + e.id, text: e.label, width: textWidth(e.label) + 8, height: 18}] : []});
    }
    return root;
  }
  function el(tag, attrs = {}, text) {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text != null) node.textContent = text;
    return node;
  }
  function render(doc, graph, container) {
    container.replaceChildren();
    const svg = el("svg", {viewBox: `0 0 ${graph.width} ${graph.height}`, role: "img", "aria-label": "Architecture diagram"});
    const defs = el("defs"), marker = el("marker", {id: "hx-arrow", viewBox: "0 0 8 8", refX: "8", refY: "4", markerWidth: "8", markerHeight: "8", markerUnits: "userSpaceOnUse", orient: "auto"});
    marker.append(el("path", {d: "M0,0 L8,4 L0,8 Z", fill: "#47607e"})); defs.append(marker); svg.append(defs);
    const shapes = el("g"), edges = el("g"), labels = el("g"), pins = el("g"); svg.append(shapes, edges, labels, pins);
    const selection = (record) => {
      const detail = document.getElementById("detail"); if (!detail) return;
      const kind = record.direction ? (record.direction === "in" ? "Input port" : "Output port") : record.kind ? (record.kind === "exposure" ? "Exposure" : "Wire") : "Block";
      const rows = [`${kind}: ${record.label || record.id}`, `Name: ${record.id}`];
      if (record.block || record.parent) rows.push("Within: " + (record.block || record.parent));
      if (record.source) rows.push(`From: ${record.source}`, `To: ${record.target}`);
      const binding = doc.bindings[record.id];
      if (binding) rows.push(binding.status === "resolved" ? "Code: " + binding.signature : "Code target unresolved: " + binding.symbol);
      const source = record.sources[0]; if (source) rows.push(`Authored at ${source.file}:${source.line}`);
      detail.textContent = rows.join("\n\n");
    };
    function label(group, obj, x, y, text, cls) {
      const t = el("text", {x, y, class: cls}, text), href = doc.code_urls[obj.id];
      if (href) { const a = el("a", {href, target: "_blank", rel: "noopener noreferrer"}); a.append(t); group.append(a); }
      else group.append(t);
    }
    function walk(n, px = 0, py = 0) {
      const x = px + (n.x || 0), y = py + (n.y || 0);
      if (n.hx) {
        const g = el("g", {"data-hx-id": n.hx.id, "data-hx-role": "block"});
        g.append(el("rect", {x, y, width: n.width, height: n.height, rx: 4, class: "block"}));
        g.addEventListener("click", () => selection(n.hx)); shapes.append(g);
        label(g, n.hx, x + 16, y + 26, n.hx.label, "title");
        for (const p of n.ports || []) {
          const cx = x + p.x + p.width / 2, cy = y + p.y + p.height / 2;
          const pin = el("g", {"data-hx-id": p.hx.id, "data-hx-role": p.hx.direction === "in" ? "input" : "output"});
          const circle = el("circle", {cx, cy, r: 5, class: "pin " + (p.hx.direction === "out" ? "output" : "input")});
          const href = doc.code_urls[p.hx.id];
          if (href) { const a = el("a", {href, target: "_blank", rel: "noopener noreferrer"}); a.append(circle); pin.append(a); } else pin.append(circle);
          pin.addEventListener("click", () => selection(p.hx)); pins.append(pin);
          const lab = el("g", {"data-hx-label-for": p.hx.id});
          for (const l of p.labels || []) label(lab, p.hx, x + p.x + l.x, y + p.y + l.y + 13, l.text, "label");
          lab.addEventListener("click", () => selection(p.hx));
          labels.append(lab);
        }
      }
      for (const e of n.edges || []) {
        const g = el("g", {"data-hx-id": e.hx.id, "data-hx-role": e.hx.kind, "data-hx-source": e.hx.source, "data-hx-target": e.hx.target});
        if (!e.sections || !e.sections.length) throw new Error("Missing ELK route for " + e.hx.id);
        for (const s of e.sections) {
          const pts = [s.startPoint, ...(s.bendPoints || []), s.endPoint];
          const d = pts.map((p, i) => (i ? "L" : "M") + (x + p.x) + "," + (y + p.y)).join(" ");
          g.append(el("path", {d, class: "wire " + e.hx.kind, "marker-end": "url(#hx-arrow)"}));
        }
        for (const l of e.labels || []) g.append(el("text", {x: x + l.x + 4, y: y + l.y + 14, class: "label edge-label"}, l.text));
        g.addEventListener("click", () => selection(e.hx)); edges.append(g);
      }
      for (const child of n.children || []) walk(child, x, y);
    }
    walk(graph); container.append(svg);
    const fit = () => svg.setAttribute("viewBox", `0 0 ${graph.width} ${graph.height}`);
    const fitButton = document.getElementById("fit"); if (fitButton) fitButton.onclick = fit;
    svg.addEventListener("wheel", event => {
      event.preventDefault(); const box = svg.viewBox.baseVal, rect = svg.getBoundingClientRect(), factor = event.deltaY > 0 ? 1.15 : 1 / 1.15;
      const nx = (event.clientX - rect.left) / rect.width, ny = (event.clientY - rect.top) / rect.height;
      svg.setAttribute("viewBox", `${box.x + box.width * nx * (1-factor)} ${box.y + box.height * ny * (1-factor)} ${box.width*factor} ${box.height*factor}`);
    }, {passive: false});
    let drag;
    svg.addEventListener("pointerdown", event => { if (event.target.closest("a,[data-hx-id],[data-hx-label-for]")) return; drag = [event.clientX, event.clientY, ...[svg.viewBox.baseVal.x, svg.viewBox.baseVal.y, svg.viewBox.baseVal.width, svg.viewBox.baseVal.height]]; svg.setPointerCapture(event.pointerId); });
    svg.addEventListener("pointermove", event => { if (!drag) return; const r = svg.getBoundingClientRect(); svg.setAttribute("viewBox", `${drag[2]-(event.clientX-drag[0])*drag[4]/r.width} ${drag[3]-(event.clientY-drag[1])*drag[5]/r.height} ${drag[4]} ${drag[5]}`); });
    svg.addEventListener("pointerup", () => { drag = null; });
    svg.addEventListener("pointercancel", () => { drag = null; });
    return svg;
  }
  global.hxArchitecture = {layoutGraph, render};
  async function init() {
    try {
      const doc = global.HX_ARCH_DATA || await fetch("/api/architecture").then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail || "Architecture unavailable"); return d; });
      document.getElementById("diagnostics").textContent = doc.diagnostics.map(d => `${d.severity}: ${d.code}: ${d.message}`).join("\n\n");
      if (!doc.valid) throw new Error("Architecture contains errors; inspect diagnostics");
      const elk = new ELK();
      const graph = await elk.layout(layoutGraph(doc));
      render(doc, graph, document.getElementById("canvas"));
      global.HX_ARCH_LAYOUT = graph;
      document.getElementById("status").textContent = `${doc.blocks.length} blocks · ${doc.ports.length} ports · ${doc.connections.length} connections` + (Object.keys(doc.bindings).length && !Object.keys(doc.code_urls).length ? " · code navigation unavailable" : "");
      global.HX_ARCH_READY = true;
    } catch (error) { document.getElementById("canvas").replaceChildren(); document.getElementById("status").textContent = String(error.message); document.getElementById("status").className = "error"; global.HX_ARCH_ERROR = String(error.message); }
  }
  if (typeof document !== "undefined" && document.getElementById("canvas")) init();
})(globalThis);
