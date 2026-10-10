/* hx viewer — JSON merge-patch helpers (RFC 7396), shared by the browser app and the Node unit tests.
 *   mergePatch(doc, patch)   apply a patch to a document: null deletes the key.
 *   composePatch(a, b)       one patch equivalent to "apply a, then b" — for EVERY document. Unlike
 *                            mergePatch it keeps null (delete) markers. Throws RangeError when no single
 *                            merge patch can express the pair (a deleted or replaced a subtree that b then
 *                            patches field-wise); callers must then send the two patches separately. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.hxPatch = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const isObj = (v) => v !== null && typeof v === "object" && !Array.isArray(v);

  function mergePatch(target, patch) {
    if (!isObj(patch)) return patch;
    const out = isObj(target) ? {...target} : {};
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) delete out[k]; else out[k] = mergePatch(out[k], v);
    }
    return out;
  }

  function composePatch(a, b) {
    if (!isObj(b)) return b;                      // b replaces (or, when null, deletes) whatever a did
    if (a === undefined) return b;                // a did not touch this key
    if (!isObj(a)) throw new RangeError("not composable: a non-object patch followed by an object patch");
    const out = {...a};
    for (const [k, v] of Object.entries(b)) out[k] = composePatch(out[k], v);
    return out;
  }

  return {mergePatch, composePatch};
});
