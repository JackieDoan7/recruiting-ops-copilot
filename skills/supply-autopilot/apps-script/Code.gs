/**
 * Supply Autopilot for Google Sheets.
 *
 * Paste into Extensions > Apps Script in a new Google Sheet, save, reload the
 * sheet, then run "Supply Autopilot > Set up this sheet" once.
 *
 * What it does:
 *   - Targets that scale with headcount and guests (onsites, events)
 *   - Order amounts rounded up to full packs
 *   - One link that puts every Amazon item in the cart (Amazon's documented
 *     "Add to Cart form": /gp/aws/cart/add.html?ASIN.1=..&Quantity.1=..)
 *   - A ready-to-paste list for Claude in Chrome for every other vendor
 *     (Claude in Chrome adds items to a cart but never purchases)
 *   - A Monday email with the low-stock list, the cart link and an estimate
 *
 * It never buys anything. A person reviews the cart and checks out.
 *
 * The pure functions at the top are tested with Node (tests/supply_code_gs.test.js).
 */

/* ------------------------------------------------------------------ pure logic */

var AMAZON_CART = 'https://www.amazon.com/gp/aws/cart/add.html';

/** Pull a 10-character ASIN out of an Amazon link, or accept a bare ASIN. */
function extractAsin(linkOrAsin) {
  var s = String(linkOrAsin || '').trim();
  if (/^[A-Z0-9]{10}$/i.test(s)) return s.toUpperCase();
  var m = s.match(/\/(?:dp|gp\/product|gp\/aw\/d|product)\/([A-Z0-9]{10})(?:[/?#]|$)/i);
  return m ? m[1].toUpperCase() : '';
}

/** Read a number the way people type it in Sheets ("$12.50", "1,200"). Blank = fallback. */
function num(v, fallback) {
  if (v === '' || v === null || v === undefined) return fallback;
  if (typeof v === 'number') return v;
  var text = String(v).replace(/[$,\s]/g, '');
  if (text === '') return fallback;
  var n = Number(text);
  if (isNaN(n)) throw new Error('Can\'t read "' + v + '" as a number.');
  return n;
}

/**
 * What an item's amount is multiplied by ("Scales with"):
 *   weekly  Everyone, per week: consumed by the whole office each week (snacks, wipes)
 *   team    Team, one each: one per teammate, kept until worn out (their own slippers)
 *   guests  Guests, one each: one per guest this period (guest slippers, visitor badges)
 */
function basisOf(value) {
  var v = String(value || '').toLowerCase();
  if (/guest/.test(v)) return 'guests';
  if (/team|headcount|one each|per person/.test(v)) return 'team';
  return 'weekly';
}

/** Units to keep on hand for one item. A fixed target wins over everything else. */
function computeTarget(item, settings) {
  var fixed = num(item.fixedTarget, 0);
  if (fixed > 0) return Math.ceil(fixed);
  var amount = num(item.amount, 0);
  var cushion = 1 + num(settings.safetyPct, 0) / 100;
  var team = num(settings.headcount, 0), guests = num(settings.guests, 0);
  var basis = basisOf(item.basis);
  var raw = basis === 'team' ? amount * team * cushion
      : basis === 'guests' ? amount * guests * cushion
      : amount * (team + guests) * num(settings.weeksBetweenOrders, 1) * cushion;
  return Math.ceil(raw - 1e-9);
}

/** Decide what to order for every item. Returns one line per item. */
function computeOrder(items, settings) {
  var reorderAt = num(settings.reorderPct, 60) / 100;
  return items.map(function (item) {
    var target = computeTarget(item, settings);
    var onHand = Math.max(0, num(item.onHand, 0));
    var onOrder = Math.max(0, num(item.onOrder, 0));  // bought, not arrived yet: never order it twice
    var pack = Math.max(1, num(item.packSize, 1));
    var line = target * reorderAt, stock = onHand + onOrder;
    var low = stock <= line;
    var packs = (low && target > stock) ? Math.ceil((target - stock) / pack) : 0;
    var price = num(item.price, 0);
    return {
      item: item.item,
      vendor: String(item.vendor || '').trim(),
      link: String(item.link || '').trim(),
      asin: extractAsin(item.link),
      target: target,
      onHand: onHand,
      onOrder: onOrder,
      pack: pack,
      packs: packs,
      cost: Math.round(packs * price * 100) / 100,
      status: target <= 0 ? 'OK' : stock === 0 ? 'Out' : low ? 'Low' : (onOrder > 0 && onHand <= line ? 'On the way' : 'OK')
    };
  });
}

function isAmazon(line) {
  return /amazon/i.test(line.vendor) && line.asin !== '';
}

/** One URL that adds every Amazon line to the signed-in user's cart. */
function amazonCartUrl(lines, associateTag) {
  var parts = [];
  var n = 0;
  lines.forEach(function (l) {
    if (l.packs > 0 && isAmazon(l)) {
      n += 1;
      parts.push('ASIN.' + n + '=' + l.asin, 'Quantity.' + n + '=' + l.packs);
    }
  });
  if (!n) return '';
  if (associateTag) parts.push('AssociateTag=' + encodeURIComponent(associateTag));
  return AMAZON_CART + '?' + parts.join('&');
}

/** A prompt for Claude in Chrome covering every non-Amazon vendor. */
function chromeHandoff(lines) {
  var byVendor = {};
  lines.forEach(function (l) {
    if (l.packs > 0 && !isAmazon(l)) {
      var v = l.vendor || 'the vendor';
      (byVendor[v] = byVendor[v] || []).push(l);
    }
  });
  var vendors = Object.keys(byVendor).sort();
  if (!vendors.length) return '';
  var out = [];
  vendors.forEach(function (v) {
    out.push('In my signed-in ' + v + ' tab, add these to the cart:');
    byVendor[v].forEach(function (l) {
      out.push('- ' + l.item + ' x ' + l.packs + (l.link ? ' (' + l.link + ')' : ''));
    });
    out.push('');
  });
  out.push('Use the links when given. For an item without a link, pick a well-reviewed match for the description. ' +
           'If something is out of stock, pick the closest match. Tell me anything you chose or swapped. ' +
           'Stop at the cart and show me the total. Do not check out.');
  return out.join('\n');
}

/** Plain-text weekly digest. */
function digestText(lines, cartUrl, handoff) {
  var toOrder = lines.filter(function (l) { return l.packs > 0; });
  var total = toOrder.reduce(function (s, l) { return s + l.cost; }, 0);
  var out = [];
  if (!toOrder.length) return 'Everything is stocked this week. Nothing to order.';
  out.push(toOrder.length + ' item(s) to order, estimated $' + total.toFixed(2) + ':');
  toOrder.forEach(function (l) {
    out.push('- ' + l.item + ': ' + l.packs + ' pack(s) from ' + (l.vendor || '?') +
             ' (on hand ' + l.onHand + (l.onOrder ? ', on order ' + l.onOrder : '') + ', target ' + l.target + ', ' + l.status.toLowerCase() + ')');
  });
  if (cartUrl) out.push('', 'Amazon: open this link, check the cart, then check out yourself:', cartUrl);
  if (handoff) out.push('', 'Other vendors: paste this into Claude in Chrome:', '', handoff);
  return out.join('\n');
}

/* ------------------------------------------------------------------ Google Sheets glue */

var SETTINGS = [
  ['Headcount', 45, 'People in the office on a normal week'],
  ['Guests this period', 0, 'Onsite candidates, event attendees, visitors'],
  ['Weeks between orders', 1, ''],
  ['Safety stock %', 20, 'Extra cushion on top of expected use'],
  ['Reorder when at or below % of target', 60, 'Below this, order back up to target'],
  ['Digest email', '', 'Blank = your own email'],
  ['Amazon associate tag', '', 'Optional; leave blank'],
  ['Amazon cart link', '', 'Filled in by Refresh'],
  ['Estimated total', '', 'Filled in by Refresh'],
  ['Last refreshed', '', '']
];
var INVENTORY_HEADERS = ['Item', 'Category', 'Vendor', 'Link or ASIN', 'Pack size (units)',
  'Amount per person (units)', 'Scales with', 'Fixed target (units)', 'On hand (units)', 'On order (units)', 'Est. price per pack ($)',
  'Target (units)', 'Packs to order', 'Est. cost ($)', 'Status'];
var INPUT_COLUMNS = 11;
var BASIS_CHOICES = ['Everyone, per week', 'Team, one each', 'Guests, one each'];
var SAMPLE_ITEMS = [
  ['Copy paper, 10 reams', 'Office', 'Amazon', 'https://www.amazon.com/dp/B01FV0F13E', 10, 0, 'Everyone, per week', 6, 3, 0, 70],
  ['Disinfecting wipes, 3 x 75', 'Cleaning', 'Amazon', 'https://www.amazon.com/dp/B00HSC9F2C', 3, 0.1, 'Everyone, per week', '', 2, 0, 15],
  ['KIND bars, dark chocolate, 12 ct', 'Snacks', 'Amazon', 'https://www.amazon.com/dp/B007PE7ANY', 12, 1.5, 'Everyone, per week', '', 20, 0, 16],
  ['LaCroix lime, 12 cans', 'Drinks', 'Amazon', 'https://www.amazon.com/dp/B07812QWNH', 12, 3, 'Everyone, per week', '', 60, 96, 7],
  ['LaCroix variety, 24 cans', 'Drinks', 'Costco Business Delivery',
   'https://www.costcobusinessdelivery.com/lacroix-sparkling-water-variety-pack-12-fl-oz-24-ct.product.100273326.html',
   24, 2, 'Everyone, per week', '', 30, 0, 15],
  ['Fresh fruit box', 'Snacks', 'Local produce vendor', '', 1, 0, '', 2, 0, 0, 45],
  ['Sticky notes, 3x3, 24 pads', 'Office', 'Amazon', '', 24, 0, '', 24, 30, 0, 22],
  ['Washable slippers, teammate pairs', 'Entryway', 'Amazon', '', 1, 1, 'Team, one each', '', 0, 0, 12],
  ['Washable guest slippers, sized', 'Entryway', 'Amazon', '', 1, 1, 'Guests, one each', '', 4, 0, 12],
  ['Wall-mounted shoe rack (one-time)', 'Entryway', 'Amazon', '', 1, 0, '', 6, 2, 0, 60],
  ['Slipper bins with size labels (one-time)', 'Entryway', 'Amazon', '', 1, 0, '', 2, 0, 0, 25],
  ['Hamper for used guest slippers (one-time)', 'Entryway', 'Amazon', '', 1, 0, '', 1, 0, 0, 30]
];
var FIX_HEADERS = ['Spotted', 'What\'s wrong', 'The fix', 'What to buy (Inventory rows)', 'Owner', 'Status'];
var SAMPLE_FIXES = [
  ['Entryway', 'Only a couple of shoe racks for the whole team, so shoes pile up by the door. Shared one-size ' +
   'slippers from a bulk pack end up scattered around the office.',
   'Go vertical with wall-mounted racks. Every teammate gets their own washable pair in their size, kept in a ' +
   'labeled spot. Sized guest bins plus a hamper for used guest pairs. Two-minute end-of-day sweep. ' +
   'Before buying for everyone, try 3 kinds of slippers with a few teammates for two weeks, then check: ' +
   'no loose pairs by the door, and people actually like them.',
   'Entryway rows: wall racks, slippers (team and guest), bins, hamper', 'Office manager', 'To do']
];
var VENDOR_HEADERS = ['Category', 'Preferred vendor', 'Backup vendor', 'Contact', 'Notes'];
var SAMPLE_VENDORS = [
  ['Office supplies', 'Amazon Business', 'Staples', '', 'Most items arrive next day'],
  ['Snacks and drinks', 'Amazon / Costco Business Delivery', 'Instacart', '', ''],
  ['Team lunch catering', '[Preferred caterer]', '[Backup caterer]', '[phone]',
   'If a delivery is 15+ min late with no answer: call backup, or send delivery credits to the team'],
  ['Cleaning', '[Cleaning vendor]', '[Backup]', '[phone]', '']
];

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Supply Autopilot')
    .addItem('Set up this sheet', 'setupSheet')
    .addItem('Refresh order', 'refreshOrder')
    .addItem('Email me this week\'s order', 'emailDigest')
    .addItem('Log the order as placed', 'logOrderPlaced')
    .addItem('Mark everything on order as arrived', 'markArrived')
    .addSeparator()
    .addItem('Turn on the Monday email', 'installWeeklyTrigger')
    .addToUi();
}

function sheet_(name) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(name) || ss.insertSheet(name);
}

function setupSheet() {
  var s = sheet_('Settings');
  if (s.getLastRow() < 2) {  // never overwrite settings someone already filled in
    s.getRange(1, 1, 1, 3).setValues([['Setting', 'Value', 'Notes']]).setFontWeight('bold');
    s.getRange(2, 1, SETTINGS.length, 3).setValues(SETTINGS);
    s.autoResizeColumns(1, 3);
  }

  var inv = sheet_('Inventory');
  if (inv.getLastRow() < 2) {
    inv.getRange(1, 1, 1, INVENTORY_HEADERS.length).setValues([INVENTORY_HEADERS]).setFontWeight('bold');
    inv.getRange(2, 1, SAMPLE_ITEMS.length, SAMPLE_ITEMS[0].length).setValues(SAMPLE_ITEMS);
    inv.setFrozenRows(1);
    inv.getRange(2, 7, 200, 1).setDataValidation(SpreadsheetApp.newDataValidation()
      .requireValueInList(BASIS_CHOICES, true).setAllowInvalid(false).build());
    inv.getRange(2, INPUT_COLUMNS + 1, 200, 4).setBackground('#f3f3f3'); // calculated columns
  }
  var v = sheet_('Vendors');
  if (v.getLastRow() < 2) {
    v.getRange(1, 1, 1, VENDOR_HEADERS.length).setValues([VENDOR_HEADERS]).setFontWeight('bold');
    v.getRange(2, 1, SAMPLE_VENDORS.length, VENDOR_HEADERS.length).setValues(SAMPLE_VENDORS);
  }
  var fixes = sheet_('Office fixes');
  if (fixes.getLastRow() < 2) {
    fixes.getRange(1, 1, 1, FIX_HEADERS.length).setValues([FIX_HEADERS]).setFontWeight('bold');
    fixes.getRange(2, 1, SAMPLE_FIXES.length, FIX_HEADERS.length).setValues(SAMPLE_FIXES).setWrap(true);
    fixes.getRange(2, 6, 200, 1).setDataValidation(SpreadsheetApp.newDataValidation()
      .requireValueInList(['To do', 'In progress', 'Done'], true).build());
    fixes.setFrozenRows(1);
  }
  var log = sheet_('Order log');
  if (log.getLastRow() < 1) {
    log.getRange(1, 1, 1, 5).setValues([['Date', 'Vendors', 'Items', 'Est. total ($)', 'Placed by']])
      .setFontWeight('bold');
  }
  refreshOrder();
}

function readSettings_() {
  var rows = sheet_('Settings').getRange(2, 1, SETTINGS.length, 2).getValues();
  var get = function (label) {
    for (var i = 0; i < rows.length; i++) if (rows[i][0] === label) return rows[i][1];
    return '';
  };
  return {
    headcount: get('Headcount'),
    guests: get('Guests this period'),
    weeksBetweenOrders: get('Weeks between orders'),
    safetyPct: get('Safety stock %'),
    reorderPct: get('Reorder when at or below % of target'),
    email: get('Digest email'),
    tag: get('Amazon associate tag')
  };
}

function readItems_() {
  var inv = sheet_('Inventory');
  var n = inv.getLastRow() - 1;
  if (n < 1) return [];
  return inv.getRange(2, 1, n, INPUT_COLUMNS).getValues()
    .map(function (r, i) {
      return { row: i + 2, item: r[0], vendor: r[2], link: r[3], packSize: r[4], amount: r[5], basis: r[6],
               fixedTarget: r[7], onHand: r[8], onOrder: r[9], price: r[10] };
    })
    .filter(function (it) { return String(it.item).trim() !== ''; });
}

function refreshOrder() {
  var settings = readSettings_();
  var items = readItems_();
  var lines = computeOrder(items, settings);
  var inv = sheet_('Inventory');
  var rows = Math.max(inv.getLastRow() - 1, 0);
  if (rows) {
    // One output row per sheet row, so blank rows never shift results onto the wrong item.
    var out = [];
    for (var i = 0; i < rows; i++) out.push(['', '', '', '']);
    items.forEach(function (it, k) {
      var l = lines[k];
      out[it.row - 2] = [l.target, l.packs, l.cost, l.status];
    });
    inv.getRange(2, INPUT_COLUMNS + 1, rows, 4).setValues(out);
  }
  var url = amazonCartUrl(lines, settings.tag);
  var total = lines.reduce(function (s, l) { return s + l.cost; }, 0);
  setSetting_('Amazon cart link', url ? url : 'Nothing to order from Amazon');
  setSetting_('Estimated total', Math.round(total * 100) / 100);
  setSetting_('Last refreshed', new Date());
  return { lines: lines, url: url, handoff: chromeHandoff(lines) };
}

function setSetting_(label, value) {
  var s = sheet_('Settings');
  var labels = s.getRange(2, 1, SETTINGS.length, 1).getValues();
  for (var i = 0; i < labels.length; i++) {
    if (labels[i][0] === label) { s.getRange(i + 2, 2).setValue(value); return; }
  }
}

function emailDigest() {
  var r = refreshOrder();
  // In a time-based trigger getActiveUser() is often blank, so fall back to the trigger's owner.
  var to = readSettings_().email || Session.getActiveUser().getEmail() || Session.getEffectiveUser().getEmail();
  if (!to) throw new Error('Add an address to "Digest email" on the Settings tab.');
  var body = digestText(r.lines, r.url, r.handoff) +
      '\n\nSheet: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl();
  MailApp.sendEmail(to, 'Supply Autopilot: this week\'s order', body);
}

function logOrderPlaced() {
  var r = refreshOrder();
  var toOrder = r.lines.filter(function (l) { return l.packs > 0; });
  if (!toOrder.length) return;
  var vendors = toOrder.map(function (l) { return l.vendor; })
    .filter(function (v, i, a) { return a.indexOf(v) === i; }).join(', ');
  var items = toOrder.map(function (l) { return l.item + ' x' + l.packs; }).join('; ');
  var total = toOrder.reduce(function (s, l) { return s + l.cost; }, 0);
  sheet_('Order log').appendRow([new Date(), vendors, items, Math.round(total * 100) / 100,
    Session.getActiveUser().getEmail()]);
  // What was just bought now counts as "on order", so next week's refresh won't buy it again.
  var inv = sheet_('Inventory'), items_ = readItems_(), lines = computeOrder(items_, readSettings_());
  items_.forEach(function (it, k) {
    if (lines[k].packs > 0) inv.getRange(it.row, 10).setValue(lines[k].onOrder + lines[k].packs * lines[k].pack);
  });
  refreshOrder();
}

/** When the boxes arrive: move "On order" onto the shelf ("On hand") and clear it. */
function markArrived() {
  var inv = sheet_('Inventory');
  readItems_().forEach(function (it) {
    var coming = Math.max(0, num(it.onOrder, 0));
    if (coming > 0) {
      inv.getRange(it.row, 9).setValue(Math.max(0, num(it.onHand, 0)) + coming);
      inv.getRange(it.row, 10).setValue('');
    }
  });
  refreshOrder();
}

function installWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'emailDigest') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('emailDigest').timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(8).create();
}

/* Let Node load the pure functions for tests; Apps Script ignores this. */
if (typeof module !== 'undefined') {
  module.exports = { extractAsin: extractAsin, basisOf: basisOf, computeTarget: computeTarget, computeOrder: computeOrder,
                     amazonCartUrl: amazonCartUrl, chromeHandoff: chromeHandoff, digestText: digestText };
}
