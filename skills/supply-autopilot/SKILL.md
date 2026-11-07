---
name: supply-autopilot
description: Office supply and snack ordering. Use when asked what to reorder, to build the Amazon cart, fill vendor carts, or set up the supply tracking sheet. Never checks out.
---

# Supply Autopilot

Keeps the office stocked without anyone walking around opening drawers.
Targets scale with headcount and guests, orders round up to full packs, and
the carts get built automatically. **A person always reviews the cart and
checks out.**

## Two ways to run it

**In Google Sheets (day to day).** Paste `apps-script/Code.gs` into
Extensions > Apps Script, reload, and run *Supply Autopilot > Set up this
sheet*. Full steps in `apps-script/README.md`. The menu refreshes the order,
fills the Amazon cart link, emails a Monday digest, and logs orders.

**In Claude (from an export).** When the user shares the Inventory tab as a
CSV (or the Google Drive connector can read it):

1. Ask for anything that changes this week's numbers: headcount, onsite
   candidates and event guests, and how many weeks until the next order.
2. Run `python scripts/supply_order.py inventory.csv --headcount <n> --guests <n> --weeks <n>`.
3. Show the order table and the Amazon link. Tell the user to open it,
   check the cart, and check out themselves.
4. For other vendors, offer to fill those carts with Claude in Chrome using
   the generated list, and stop at the cart. Never check out, enter payment
   details, or accept new terms.

## How the numbers work

- Each item has an amount per person and a **Scales with** setting:
  - *Everyone, per week* (snacks, wipes): amount x (headcount + guests) x
    weeks between orders x (1 + safety stock)
  - *Team, one each* (teammates' own slippers, mugs): amount x headcount x
    (1 + safety stock), so new hires trigger their own items
  - *Guests, one each* (guest slippers, visitor badges): amount x guests x
    (1 + safety stock)
  - A fixed target overrides all three (toner, fruit boxes, one-time purchases
    like racks or bins, which then order once and stop).
- Order only when on hand is at or below the reorder point (60% of target by
  default), then order back up to target, rounded up to full packs.
- The Amazon link uses Amazon's documented Add to Cart form
  (`/gp/aws/cart/add.html?ASIN.1=...&Quantity.1=...`). Opening it shows the
  items to add; the user confirms and reviews the cart.
- If an item's link isn't an Amazon product link, it goes to the Claude in
  Chrome list instead.

## Office fixes

Not everything is a reorder. When the user describes something that isn't
working in the office (a messy entryway, a broken chair, a meeting room that's
always booked), turn it into an entry on the **Office fixes** tab:

1. What's wrong, in one or two plain sentences.
2. The fix: what changes physically, who owns it, and the routine that keeps
   it fixed. Prefer fixes that make the right thing the easy thing (a labeled
   spot for every pair beats a reminder email).
3. Anything to buy, added as Inventory rows: one-time items as fixed targets,
   recurring items with the right *Scales with* setting.
4. How you'll know it worked (a count, a photo, a quick ask).

`references/entryway.md` is a worked example: a shoes-off office with
shoes piling up and shared slippers everywhere.

## Also in the sheet

- **Vendors** tab: preferred and backup vendor per category, so a catering
  no-show is a phone call, not a scramble.
- **Order log** tab: what was ordered and when, to tune per-person use after
  a few weeks.
