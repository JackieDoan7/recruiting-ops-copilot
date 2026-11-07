// Tests for the pure functions in apps-script/Code.gs. Run: node --test tests/js/*.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const file = path.join(__dirname, '..', '..', 'skills', 'supply-autopilot', 'apps-script', 'Code.gs');
const ctx = { module: { exports: {} } };
vm.runInNewContext(fs.readFileSync(file, 'utf8'), ctx);
const gs = ctx.module.exports;

const settings = { headcount: 45, guests: 12, weeksBetweenOrders: 1, safetyPct: 20, reorderPct: 60 };

test('extracts ASINs from common Amazon link shapes', () => {
  assert.equal(gs.extractAsin('https://www.amazon.com/dp/B01FV0F13E'), 'B01FV0F13E');
  assert.equal(gs.extractAsin('https://www.amazon.com/Some-Name/dp/B00HSC9F2C/ref=sr_1_1?k=x'), 'B00HSC9F2C');
  assert.equal(gs.extractAsin('https://www.amazon.com/gp/product/b007pe7any?th=1'), 'B007PE7ANY');
  assert.equal(gs.extractAsin('B07812QWNH'), 'B07812QWNH');
  assert.equal(gs.extractAsin('https://www.costco.com/item.html'), '');
  assert.equal(gs.extractAsin(''), '');
});

test('targets scale with people; fixed targets win', () => {
  assert.equal(gs.computeTarget({ amount: 1.5 }, settings), 103); // 1.5 * 57 * 1.2 = 102.6
  assert.equal(gs.computeTarget({ amount: 1.5, fixedTarget: 10 }, settings), 10);
  assert.equal(gs.computeTarget({ amount: 0.5 }, { headcount: 10, safetyPct: 0 }), 5);
});

test('"Scales with" picks what the amount is multiplied by', () => {
  const s = { headcount: 45, guests: 12, weeksBetweenOrders: 2, safetyPct: 20 };
  // Everyone, per week: whole office, for every week until the next order.
  assert.equal(gs.computeTarget({ amount: 1, basis: 'Everyone, per week' }, s), 137); // 57 * 2 * 1.2 = 136.8
  // Team, one each: one per teammate, no matter how long between orders (54 = 45 + cushion).
  assert.equal(gs.computeTarget({ amount: 1, basis: 'Team, one each' }, s), 54);
  // Guests, one each: one per guest this period.
  assert.equal(gs.computeTarget({ amount: 1, basis: 'Guests, one each' }, s), 15);
  // A new hire raises the team target by one pair (plus cushion).
  assert.equal(gs.computeTarget({ amount: 1, basis: 'Team, one each' }, { headcount: 50, safetyPct: 0 }), 50);
  assert.equal(gs.basisOf(''), 'weekly');
});

test('one-time purchases order once, then stop', () => {
  const s = { headcount: 45, reorderPct: 60 };
  const before = gs.computeOrder([{ item: 'Wall rack', fixedTarget: 6, onHand: 2, packSize: 1 }], s)[0];
  const after = gs.computeOrder([{ item: 'Wall rack', fixedTarget: 6, onHand: 6, packSize: 1 }], s)[0];
  assert.equal(before.packs, 4);
  assert.equal(after.packs, 0);
});

test('orders only at the reorder point, rounded up to packs', () => {
  const [ok, low, out] = gs.computeOrder([
    { item: 'ok', amount: 0, fixedTarget: 10, onHand: 7, packSize: 4 },
    { item: 'low', amount: 0, fixedTarget: 10, onHand: 6, packSize: 4, price: 2.5 },
    { item: 'out', amount: 0, fixedTarget: 3, onHand: 0, packSize: 1 },
  ], settings);
  assert.equal(ok.packs, 0); assert.equal(ok.status, 'OK');
  assert.equal(low.packs, 1); assert.equal(low.cost, 2.5); assert.equal(low.status, 'Low');
  assert.equal(out.packs, 3); assert.equal(out.status, 'Out');
});

test('Amazon cart link numbers items from 1 and skips non-Amazon lines', () => {
  const lines = [
    { packs: 2, vendor: 'Amazon', asin: 'B01FV0F13E' },
    { packs: 0, vendor: 'Amazon', asin: 'B00HSC9F2C' },
    { packs: 1, vendor: 'Costco', asin: '' },
    { packs: 3, vendor: 'Amazon Business', asin: 'B007PE7ANY' },
  ];
  assert.equal(gs.amazonCartUrl(lines, ''),
    'https://www.amazon.com/gp/aws/cart/add.html?ASIN.1=B01FV0F13E&Quantity.1=2&ASIN.2=B007PE7ANY&Quantity.2=3');
  assert.match(gs.amazonCartUrl(lines, 'my tag'), /&AssociateTag=my%20tag$/);
  assert.equal(gs.amazonCartUrl([{ packs: 0, vendor: 'Amazon', asin: 'B01FV0F13E' }], ''), '');
});

test('Claude in Chrome list never asks it to check out', () => {
  const text = gs.chromeHandoff([{ packs: 2, vendor: 'Costco', item: 'Water', link: 'https://x' }]);
  assert.match(text, /In my signed-in Costco tab/);
  assert.match(text, /Do not check out\./);
  assert.equal(gs.chromeHandoff([{ packs: 2, vendor: 'Amazon', asin: 'B01FV0F13E', item: 'Paper' }]), '');
});

test('digest says when nothing is needed', () => {
  assert.match(gs.digestText([{ packs: 0 }], '', ''), /Nothing to order/);
});

test('stock already on order is never ordered twice', () => {
  const s = { headcount: 45, guests: 12, weeksBetweenOrders: 1, safetyPct: 20, reorderPct: 60 };
  const [l] = gs.computeOrder([{ item: 'Snacks', fixedTarget: 100, onHand: 20, onOrder: 80, packSize: 10 }], s);
  assert.equal(l.packs, 0); assert.equal(l.status, 'On the way');
});
