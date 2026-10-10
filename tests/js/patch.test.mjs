// Unit tests for hx/viewer/patch.js (run: node --test tests/js). Checks the composition law
//   merge(merge(doc, a), b) == merge(doc, compose(a, b))   for every doc, whenever compose does not throw,
// and that compose throws only for "delete/replace a subtree, then patch inside it".
import {test} from "node:test";
import assert from "node:assert/strict";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {mergePatch, composePatch} = require("../../hx/viewer/patch.js");

const docs = [
  {}, {nodes: {}}, {nodes: {f: {note: "x", tags: ["a"], verified_body_hash: "sha1:1", params: {ch: {dir: "out"}}}}},
  {view: {pinned_positions: {f: {x: 1, y: 2}, g: {x: 3, y: 4}}, hidden: ["g"]}},
  {nodes: {f: {note: "old"}}, view: {pinned_positions: {f: {x: 0, y: 0}}}},
];
const patches = [
  {nodes: {f: {note: "new"}}}, {nodes: {f: {note: null}}}, {nodes: {f: {tags: null}}}, {nodes: {f: {verified_body_hash: null}}},
  {nodes: {f: {params: {ch: {dir: null}}}}}, {nodes: {f: {params: {ch: {dir: "in"}}}}}, {nodes: {f: null}},
  {view: {pinned_positions: null}}, {view: {pinned_positions: {f: {x: 9, y: 9}}}}, {view: {hidden: ["f"]}}, {view: {hidden: null}},
  {nodes: {f: {note: "a"}}, view: {pinned_positions: {g: null}}},
];

test("mergePatch follows RFC 7396", () => {
  assert.deepEqual(mergePatch({a: {b: 1, c: 2}}, {a: {b: null, d: 3}}), {a: {c: 2, d: 3}});
  assert.deepEqual(mergePatch({a: 1}, {a: {b: 1}}), {a: {b: 1}});
  assert.deepEqual(mergePatch({a: [1]}, {a: [2]}), {a: [2]});
  assert.equal(mergePatch({a: 1}, null), null);
});

test("composePatch keeps delete markers", () => {
  const c = composePatch({}, {nodes: {f: {note: null}}});
  assert.deepEqual(c, {nodes: {f: {note: null}}});
  assert.deepEqual(composePatch({nodes: {f: {note: "x"}}}, {nodes: {f: {note: null}}}), {nodes: {f: {note: null}}});
  assert.deepEqual(composePatch({nodes: {f: {note: null}}}, {nodes: {f: {note: "y"}}}), {nodes: {f: {note: "y"}}});
});

test("composition law holds for every doc × patch × patch (or compose refuses)", () => {
  let composed = 0, refused = 0;
  for (const a of patches) for (const b of patches) {
    let c;
    try { c = composePatch(a, b); } catch (e) { assert.ok(e instanceof RangeError); refused++; continue; }
    composed++;
    for (const d of docs) assert.deepEqual(mergePatch(d, c), mergePatch(mergePatch(d, a), b), JSON.stringify({a, b, d}));
  }
  assert.ok(composed > 100 && refused > 0, `${composed} composed, ${refused} refused`);
});

test("compose refuses exactly the delete-then-patch-inside case", () => {
  assert.throws(() => composePatch({view: {pinned_positions: null}}, {view: {pinned_positions: {f: {x: 1, y: 1}}}}), RangeError);
  assert.throws(() => composePatch({nodes: {f: null}}, {nodes: {f: {note: "n"}}}), RangeError);
  assert.doesNotThrow(() => composePatch({nodes: {f: null}}, {nodes: {g: {note: "n"}}}));
  assert.doesNotThrow(() => composePatch({nodes: {f: null}}, {nodes: {f: "scalar"}}));
});
