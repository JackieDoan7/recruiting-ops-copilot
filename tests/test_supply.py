import json
import shutil
import subprocess
from pathlib import Path

import pytest

import supply_order as so
from conftest import ROOT, SKILLS

INVENTORY = SKILLS / "supply-autopilot" / "examples" / "inventory.csv"
CODE_GS = SKILLS / "supply-autopilot" / "apps-script" / "Code.gs"
SETTINGS = {"headcount": 45, "guests": 12, "weeks_between_orders": 1, "safety_pct": 20, "reorder_pct": 60}


def test_example_order():
    lines = {l["item"]: l for l in so.compute_order(so.read_inventory(INVENTORY), SETTINGS)}
    assert lines["KIND bars, dark chocolate, 12 ct"]["target"] == 103
    assert lines["KIND bars, dark chocolate, 12 ct"]["packs"] == 7
    assert lines["Fresh fruit box"]["status"] == "Out"
    assert lines["Copy paper, 10 reams"]["packs"] == 1


def test_entryway_items_scale_the_right_way():
    lines = {l["item"]: l for l in so.compute_order(so.read_inventory(INVENTORY), SETTINGS)}
    assert lines["Name labels for teammate slipper spots"]["target"] == 54  # 45 teammates + 20% cushion
    assert lines["Slipper trial pairs (3 kinds, 2 each)"]["packs"] == 6  # a trial first, not 54 pairs
    assert lines["Washable guest slippers, sized"]["target"] == 15  # 12 guests + 20% cushion
    assert lines["Wall-mounted shoe rack (one-time)"]["packs"] == 4  # 6 wanted, 2 already up
    bigger = dict(SETTINGS, headcount=50)
    team = next(l for l in so.compute_order(so.read_inventory(INVENTORY), bigger) if "teammate" in l["item"])
    assert team["target"] == 60  # five new hires, five more pairs (plus cushion)


def test_items_without_links_go_to_claude_in_chrome():
    lines = so.compute_order(so.read_inventory(INVENTORY), SETTINGS)
    handoff = so.chrome_handoff(lines)
    assert "In my signed-in Amazon tab" in handoff and "Wall-mounted shoe rack" in handoff
    assert "well-reviewed match" in handoff and "B01FV0F13E" not in handoff


def test_cart_link_and_handoff():
    lines = so.compute_order(so.read_inventory(INVENTORY), SETTINGS)
    url = so.amazon_cart_url(lines)
    assert url.startswith("https://www.amazon.com/gp/aws/cart/add.html?ASIN.1=")
    assert url.count("ASIN.") == 3 and "costco" not in url  # LaCroix lime is already on the way
    handoff = so.chrome_handoff(lines)
    assert "Costco Business Delivery" in handoff and handoff.endswith("Do not check out.")


def test_stock_on_the_way_is_never_ordered_twice():
    item = {"item": "Snacks", "fixed_target": "100", "on_hand": "20", "pack_size": "10"}
    (before,) = so.compute_order([item], SETTINGS)
    assert before["packs"] == 8 and before["status"] == "Low"
    (after,) = so.compute_order([dict(item, on_order="80")], SETTINGS)  # last week's order hasn't arrived
    assert after["packs"] == 0 and after["status"] == "On the way"
    (partial,) = so.compute_order([dict(item, on_order="20")], SETTINGS)  # only part of it is coming
    assert partial["packs"] == 6 and partial["status"] == "Low"


def test_nothing_to_order():
    lines = so.compute_order([{"item": "x", "fixed_target": "5", "on_hand": "5", "pack_size": "1"}], SETTINGS)
    assert so.amazon_cart_url(lines) == "" and so.chrome_handoff(lines) == ""
    assert "Nothing to order" in so.markdown(lines, "", "")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node not installed")
def test_google_sheets_and_python_versions_agree():
    """The Apps Script and the Python script must produce the same order for the same inventory."""
    items = so.read_inventory(INVENTORY)
    js_items = [{"item": i["item"], "vendor": i["vendor"], "link": i["link"], "packSize": i["pack_size"],
                 "amount": i["amount"], "basis": i["basis"], "fixedTarget": i["fixed_target"],
                 "onHand": i["on_hand"], "onOrder": i["on_order"], "price": i["price"]} for i in items]
    js_settings = {"headcount": 45, "guests": 12, "weeksBetweenOrders": 1, "safetyPct": 20, "reorderPct": 60}
    script = (
        "const fs=require('fs'),vm=require('vm');const ctx={module:{exports:{}}};"
        f"vm.runInNewContext(fs.readFileSync({json.dumps(str(CODE_GS))},'utf8'),ctx);"
        "const g=ctx.module.exports;"
        f"const lines=g.computeOrder({json.dumps(js_items)},{json.dumps(js_settings)});"
        "console.log(JSON.stringify({lines:lines,url:g.amazonCartUrl(lines,''),handoff:g.chromeHandoff(lines)}));"
    )
    js = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    py_lines = so.compute_order(items, SETTINGS)
    assert [(l["item"], l["target"], l["packs"], l["cost"], l["status"]) for l in py_lines] == \
           [(l["item"], l["target"], l["packs"], l["cost"], l["status"]) for l in js["lines"]]
    assert so.amazon_cart_url(py_lines) == js["url"]
    assert so.chrome_handoff(py_lines) == js["handoff"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node not installed")
def test_apps_script_unit_tests():
    files = [str(f) for f in sorted((ROOT / "tests" / "js").glob("*.test.js"))]
    result = subprocess.run(["node", "--test", *files], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_sheets_style_numbers_and_lowercase_asins():
    lines = so.compute_order([{"item": "x", "vendor": "Amazon", "link": "b01fv0f13e", "fixed_target": "1,000",
                               "on_hand": "1", "pack_size": "500", "price": "$12.50"}], SETTINGS)
    assert lines[0]["asin"] == "B01FV0F13E"
    assert lines[0]["target"] == 1000 and lines[0]["packs"] == 2 and lines[0]["cost"] == 25.0


def test_unreadable_number_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="On hand for x"):
        so.compute_order([{"item": "x", "fixed_target": "5", "on_hand": "a few"}], SETTINGS)
