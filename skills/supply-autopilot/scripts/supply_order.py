#!/usr/bin/env python3
"""Supply Autopilot, command-line version.

Same logic as apps-script/Code.gs (the Google Sheets version), for when the
inventory comes in as a CSV export: compute what to order, build the one-click
Amazon cart link, and write the Claude in Chrome list for other vendors.

    python supply_order.py examples/inventory.csv --headcount 45 --guests 12

It never buys anything. A person opens the cart, checks it, and checks out.
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path
from urllib.parse import quote

AMAZON_CART = "https://www.amazon.com/gp/aws/cart/add.html"
COLUMNS = {
    "item": "Item", "vendor": "Vendor", "link": "Link or ASIN", "pack_size": "Pack size (units)",
    "amount": "Amount per person (units)", "basis": "Scales with", "fixed_target": "Fixed target (units)",
    "on_hand": "On hand (units)", "on_order": "On order (units)", "price": "Est. price per pack ($)",
}


def extract_asin(link_or_asin: str) -> str:
    s = (link_or_asin or "").strip()
    if re.fullmatch(r"[A-Z0-9]{10}", s, re.I):
        return s.upper()
    m = re.search(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})(?:[/?#]|$)", s, re.I)
    return m.group(1).upper() if m else ""


def num(v, default: float = 0.0, field: str = "") -> float:
    """Read a number the way Sheets exports it ("$12.50", "1,200"). Blank = default.
    Anything else unreadable is an error, not a silent zero (a wrong zero means a wrong order)."""
    text = str(v if v is not None else "").strip().replace("$", "").replace(",", "").replace(" ", "")
    if text == "":
        return default
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"Can't read {v!r}{' in ' + field if field else ''} as a number.") from None


def basis_of(value: str) -> str:
    """What an item's amount is multiplied by ("Scales with" column):
    weekly = everyone, per week (snacks); team = one per teammate (their own slippers);
    guests = one per guest this period (guest slippers)."""
    v = (value or "").lower()
    if "guest" in v:
        return "guests"
    if any(w in v for w in ("team", "headcount", "one each", "per person")):
        return "team"
    return "weekly"


def compute_target(item: dict, s: dict) -> int:
    fixed = num(item.get("fixed_target"))
    if fixed > 0:
        return math.ceil(fixed)
    amount = num(item.get("amount"))
    cushion = 1 + num(s.get("safety_pct")) / 100
    team, guests = num(s.get("headcount")), num(s.get("guests"))
    basis = basis_of(item.get("basis", ""))
    if basis == "team":
        raw = amount * team * cushion
    elif basis == "guests":
        raw = amount * guests * cushion
    else:
        raw = amount * (team + guests) * num(s.get("weeks_between_orders"), 1) * cushion
    return math.ceil(raw - 1e-9)


def compute_order(items: list[dict], s: dict) -> list[dict]:
    reorder_at = num(s.get("reorder_pct"), 60) / 100
    lines = []
    for item in items:
        name = item.get("item", "")
        target = compute_target(item, s)
        on_hand = max(0.0, num(item.get("on_hand"), 0, f"On hand for {name}"))
        on_order = max(0.0, num(item.get("on_order"), 0, f"On order for {name}"))  # bought, not arrived
        pack = max(1.0, num(item.get("pack_size"), 1, f"Pack size for {name}"))
        line, stock = target * reorder_at, on_hand + on_order
        low = stock <= line
        packs = math.ceil((target - stock) / pack) if low and target > stock else 0
        if target <= 0:
            status = "OK"
        elif stock == 0:
            status = "Out"
        elif low:
            status = "Low"
        else:
            status = "On the way" if on_order > 0 and on_hand <= line else "OK"
        lines.append({
            "item": item.get("item", ""), "vendor": (item.get("vendor") or "").strip(),
            "link": (item.get("link") or "").strip(), "asin": extract_asin(item.get("link", "")),
            "target": target, "on_hand": int(on_hand) if on_hand == int(on_hand) else on_hand,
            "on_order": int(on_order) if on_order == int(on_order) else on_order,
            "packs": packs, "cost": round(packs * num(item.get("price"), 0, f"Price for {name}"), 2),
            "status": status,
        })
    return lines


def is_amazon(line: dict) -> bool:
    return "amazon" in line["vendor"].lower() and bool(line["asin"])


def amazon_cart_url(lines: list[dict], associate_tag: str = "") -> str:
    parts = []
    for n, l in enumerate([l for l in lines if l["packs"] > 0 and is_amazon(l)], 1):
        parts += [f"ASIN.{n}={l['asin']}", f"Quantity.{n}={l['packs']}"]
    if not parts:
        return ""
    if associate_tag:
        parts.append(f"AssociateTag={quote(associate_tag)}")
    return f"{AMAZON_CART}?{'&'.join(parts)}"


def chrome_handoff(lines: list[dict]) -> str:
    by_vendor: dict[str, list[dict]] = {}
    for l in lines:
        if l["packs"] > 0 and not is_amazon(l):
            by_vendor.setdefault(l["vendor"] or "the vendor", []).append(l)
    if not by_vendor:
        return ""
    out = []
    for v in sorted(by_vendor):
        out.append(f"In my signed-in {v} tab, add these to the cart:")
        out += [f"- {l['item']} x {l['packs']}" + (f" ({l['link']})" if l["link"] else "") for l in by_vendor[v]]
        out.append("")
    out.append("Use the links when given. For an item without a link, pick a well-reviewed match for the description. "
               "If something is out of stock, pick the closest match. Tell me anything you chose or swapped. "
               "Stop at the cart and show me the total. Do not check out.")
    return "\n".join(out)


def read_inventory(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    items = []
    for r in rows:
        item = {key: r.get(col, "") for key, col in COLUMNS.items()}
        if item["item"].strip():
            items.append(item)
    return items


def markdown(lines: list[dict], url: str, handoff: str) -> str:
    to_order = [l for l in lines if l["packs"] > 0]
    total = sum(l["cost"] for l in to_order)
    out = ["# This week's supply order", ""]
    if not to_order:
        return "\n".join(out + ["Everything is stocked. Nothing to order.", ""])
    out += [f"{len(to_order)} item(s) to order, estimated **${total:,.2f}**.", "",
            "| Item | Vendor | On hand | On order | Target | Packs | Est. cost | Status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    out += [f"| {l['item']} | {l['vendor']} | {l['on_hand']} | {l['on_order']} | {l['target']} | {l['packs']} | ${l['cost']:,.2f} | "
            f"{l['status']} |" for l in to_order]
    if url:
        out += ["", "## Amazon", "", f"[Open the cart with everything added]({url}). Check quantities and prices, "
                "then check out yourself.", ""]
    if handoff:
        out += ["## Other vendors (paste into Claude in Chrome)", "", "```text", handoff, "```", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Work out this week's supply order and build the carts.")
    p.add_argument("inventory", type=Path, help="CSV with the Inventory tab's columns")
    p.add_argument("--headcount", type=float, default=45)
    p.add_argument("--guests", type=float, default=0, help="Onsite candidates, event guests, visitors")
    p.add_argument("--weeks", type=float, default=1, help="Weeks between orders")
    p.add_argument("--safety", type=float, default=20, help="Safety stock %%")
    p.add_argument("--reorder", type=float, default=60, help="Reorder at or below this %% of target")
    p.add_argument("--associate-tag", default="")
    p.add_argument("-o", "--output", type=Path)
    a = p.parse_args(argv)
    settings = {"headcount": a.headcount, "guests": a.guests, "weeks_between_orders": a.weeks,
                "safety_pct": a.safety, "reorder_pct": a.reorder}
    try:
        lines = compute_order(read_inventory(a.inventory), settings)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    text = markdown(lines, amazon_cart_url(lines, a.associate_tag), chrome_handoff(lines))
    if a.output:
        a.output.write_text(text)
        print(f"Wrote {a.output}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
