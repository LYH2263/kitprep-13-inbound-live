"""Inbound must move stock, the latest prep sheet's lines and the shortage
sticky count together — or not at all. Archived prep runs stay untouched."""
import json

import pytest

from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepRun


def seed_basic(db):
    """pork: need 5.0 vs stock 1.0 -> shortage 4.0; rice never short."""
    dish = Dish(code="D-HS", name="红烧肉套餐")
    pork = Ingredient(code="I-PR", name="五花肉", unit="kg", stock_qty=1.0)
    rice = Ingredient(code="I-RC", name="大米", unit="kg", stock_qty=50.0)
    db.add_all([dish, pork, rice]); db.flush()
    db.add_all([
        BomLine(dish_id=dish.id, ingredient_id=pork.id, qty_per_portion=0.5),
        BomLine(dish_id=dish.id, ingredient_id=rice.id, qty_per_portion=0.1),
    ])
    order = KitchenOrder(code="KO-1", outlet="城西门店")
    db.add(order); db.flush()
    db.add(OrderLine(order_id=order.id, dish_id=dish.id, portions=10))
    db.commit()
    return order, pork, rice


def line_of(sheet, ingredient_id):
    return next(l for l in sheet["prep_lines"] if l["ingredient_id"] == ingredient_id)


def test_inbound_aligns_stock_latest_sheet_and_stickers(client, db):
    order, pork, _ = seed_basic(db)
    run = client.post("/api/prep/run", params={"order_id": order.id}).json()
    assert line_of(run, pork.id)["shortage"] == 4.0
    assert run["stats"]["shortage_count"] == 1

    res = client.post("/api/inventory/inbound", json={"ingredient_id": pork.id, "qty": 10})
    assert res.status_code == 200
    assert res.json()["stock_qty"] == 11.0
    assert res.json()["refreshed_runs"] == 1

    # 1) 库存页结存
    inv = {r["id"]: r for r in client.get("/api/inventory").json()}
    assert inv[pork.id]["stock_qty"] == 11.0

    # 2) 最新备料单每一行：同一张单被刷新，缺料按入库后结存
    latest = client.get("/api/prep/latest", params={"order_id": order.id}).json()
    assert latest["id"] == run["id"]
    line = line_of(latest, pork.id)
    assert line["stock_qty"] == 11.0
    assert line["shortage"] == 0.0

    # 3) 缺料贴张数
    sh = client.get("/api/prep/shortages", params={"order_id": order.id}).json()
    assert sh["stats"]["shortage_count"] == 0
    assert sh["shortages"] == []


def test_partial_inbound_reduces_shortage(client, db):
    order, pork, _ = seed_basic(db)
    client.post("/api/prep/run", params={"order_id": order.id})
    client.post("/api/inventory/inbound", json={"ingredient_id": pork.id, "qty": 2.5})
    sh = client.get("/api/prep/shortages", params={"order_id": order.id}).json()
    assert sh["stats"]["shortage_count"] == 1
    line = line_of({"prep_lines": sh["shortages"]}, pork.id)
    assert line["stock_qty"] == 3.5
    assert line["shortage"] == 1.5


def test_archived_runs_keep_original_text(client, db):
    order, pork, _ = seed_basic(db)
    run1 = client.post("/api/prep/run", params={"order_id": order.id}).json()
    run2 = client.post("/api/prep/run", params={"order_id": order.id}).json()
    archived_before = db.get(PrepRun, run1["id"]).result_json

    client.post("/api/inventory/inbound", json={"ingredient_id": pork.id, "qty": 10})
    db.expire_all()

    # 存档旧单全文不变；最新单被刷新；入库不新增单
    assert db.get(PrepRun, run1["id"]).result_json == archived_before
    refreshed = json.loads(db.get(PrepRun, run2["id"]).result_json)
    assert refreshed["stats"]["shortage_count"] == 0
    assert db.query(PrepRun).count() == 2


@pytest.mark.parametrize("qty", [-3, 0])
def test_non_positive_qty_rejected_all_or_nothing(client, db, qty):
    order, pork, _ = seed_basic(db)
    client.post("/api/prep/run", params={"order_id": order.id})
    latest_before = client.get("/api/prep/latest", params={"order_id": order.id}).json()

    res = client.post("/api/inventory/inbound", json={"ingredient_id": pork.id, "qty": qty})
    assert res.status_code == 422

    # 库存没动、单也没动
    inv = {r["id"]: r for r in client.get("/api/inventory").json()}
    assert inv[pork.id]["stock_qty"] == 1.0
    assert client.get("/api/prep/latest", params={"order_id": order.id}).json() == latest_before
    sh = client.get("/api/prep/shortages", params={"order_id": order.id}).json()
    assert sh["stats"]["shortage_count"] == 1


def test_unknown_ingredient_rejected_all_or_nothing(client, db):
    order, pork, _ = seed_basic(db)
    client.post("/api/prep/run", params={"order_id": order.id})
    latest_before = client.get("/api/prep/latest", params={"order_id": order.id}).json()

    res = client.post("/api/inventory/inbound", json={"ingredient_id": 9999, "qty": 5})
    assert res.status_code == 404

    inv = {r["id"]: r for r in client.get("/api/inventory").json()}
    assert inv[pork.id]["stock_qty"] == 1.0
    assert client.get("/api/prep/latest", params={"order_id": order.id}).json() == latest_before
    sh = client.get("/api/prep/shortages", params={"order_id": order.id}).json()
    assert sh["stats"]["shortage_count"] == 1
