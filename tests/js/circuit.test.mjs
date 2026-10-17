import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const {getNet} = require('../../hx/viewer/circuit.js');
const g = JSON.parse(readFileSync(new URL('../fixtures/viewer/circuit-query.json', import.meta.url)));
test('canonical connectivity matches guarded Python query expectations', () => {
  assert.deepEqual(getNet(g, 'out').results.map(r => r.node).sort(), g.expected.all);
  assert.deepEqual(getNet(g, 'x.p', 'r2').results.map(r => r.node).sort(), g.expected.guarded);
  assert.deepEqual(getNet(g, 'out').aliases, g.expected.aliases);
});
