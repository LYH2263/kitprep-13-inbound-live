import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import (
    BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepRun, StockReceipt,
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    dish = Dish(code="D1", name="测试菜", portion_unit="份")
    ing_meat = Ingredient(code="M", name="肉", unit="kg", stock_qty=1.0)
    ing_rice = Ingredient(code="R", name="米", unit="kg", stock_qty=5.0)
    db.add_all([dish, ing_meat, ing_rice]); db.flush()
    db.add(BomLine(dish_id=dish.id, ingredient_id=ing_meat.id, qty_per_portion=0.2))
    db.add(BomLine(dish_id=dish.id, ingredient_id=ing_rice.id, qty_per_portion=0.1))
    order = KitchenOrder(code="KO-1", outlet="测试门店", status="open")
    db.add(order); db.flush()
    db.add(OrderLine(order_id=order.id, dish_id=dish.id, portions=10))
    db.commit()
    meat_id, rice_id, order_id = ing_meat.id, ing_rice.id, order.id
    db.close()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    # 不使用 with：避免触发 lifespan 里对真实 Postgres 的 create_all
    c = TestClient(app)
    try:
        yield c, TestingSession, meat_id, rice_id, order_id
    finally:
        app.dependency_overrides.clear()


def test_negative_qty_moves_nothing(client):
    c, Session, meat_id, _rice_id, _oid = client
    r = c.post("/api/inventory/inbound", json={"lines": [{"ingredient_id": meat_id, "qty": -3}]})
    assert r.status_code == 400
    with Session() as s:
        assert s.get(Ingredient, meat_id).stock_qty == 1.0  # 结存没动
        assert s.scalars(select(StockReceipt)).all() == []  # 流水没动


def test_unknown_ingredient_moves_nothing(client):
    c, Session, _meat_id, _rice_id, _oid = client
    r = c.post("/api/inventory/inbound", json={"lines": [{"ingredient_id": 99999, "qty": 2}]})
    assert r.status_code == 400
    with Session() as s:
        assert s.scalar(select(func.count()).select_from(StockReceipt)) == 0


def test_id_code_mismatch_moves_nothing(client):
    c, Session, meat_id, rice_id, _oid = client
    r = c.post("/api/inventory/inbound",
               json={"lines": [{"ingredient_id": meat_id, "ingredient_code": "R", "qty": 1}]})
    assert r.status_code == 400
    with Session() as s:
        assert s.get(Ingredient, meat_id).stock_qty == 1.0
        assert s.get(Ingredient, rice_id).stock_qty == 5.0
        assert s.scalars(select(StockReceipt)).all() == []


def test_empty_lines_rejected(client):
    c, _Session, _m, _r, _o = client
    assert c.post("/api/inventory/inbound", json={"lines": []}).status_code == 400


def test_one_bad_line_aborts_whole_receipt(client):
    # 同一入库单中：合法行 + 非法行混合，合法行也必须一起停（结存/流水都不动）
    c, Session, meat_id, rice_id, _oid = client
    r = c.post("/api/inventory/inbound", json={"lines": [
        {"ingredient_id": meat_id, "qty": 2.0},
        {"ingredient_id": rice_id, "qty": -1.0},
    ]})
    assert r.status_code == 400
    with Session() as s:
        assert s.get(Ingredient, meat_id).stock_qty == 1.0
        assert s.get(Ingredient, rice_id).stock_qty == 5.0
        assert s.scalar(select(func.count()).select_from(StockReceipt)) == 0


def test_multi_line_inbound_same_ingredient_accumulates(client):
    c, Session, meat_id, rice_id, _oid = client
    r = c.post("/api/inventory/inbound", json={"lines": [
        {"ingredient_id": meat_id, "qty": 2.0},
        {"ingredient_id": meat_id, "qty": 0.5},
        {"ingredient_code": "R", "qty": 1.0},
    ]})
    assert r.status_code == 200
    inv = {x["id"]: x["stock_qty"] for x in r.json()["inventory"]}
    assert inv[meat_id] == 3.5
    assert inv[rice_id] == 6.0
    with Session() as s:
        assert s.scalar(select(func.count()).select_from(StockReceipt)) == 3


def test_inbound_aligns_inventory_latest_sheet_and_shortages_but_keeps_archive(client):
    c, Session, meat_id, rice_id, order_id = client
    # 生成备料单：肉需 2kg、结存 1kg → 缺 1kg；米需 1kg、结存 5kg → 不缺
    run = c.post(f"/api/prep/run?order_id={order_id}").json()
    run_id = run["id"]
    assert {(s["ingredient_id"], s["shortage"]) for s in run["shortages"]} == {(meat_id, 1.0)}

    # 入库 1kg 肉，恰好补齐
    r = c.post("/api/inventory/inbound", json={"lines": [{"ingredient_id": meat_id, "qty": 1.0}]})
    assert r.status_code == 200
    inv = {x["id"]: x["stock_qty"] for x in r.json()["inventory"]}
    assert inv[meat_id] == 2.0

    # 流水已落账
    with Session() as s:
        rcpts = s.scalars(select(StockReceipt).where(StockReceipt.ingredient_id == meat_id)).all()
        assert [x.qty for x in rcpts] == [1.0]
        archived = json.loads(s.get(PrepRun, run_id).result_json)

    # 最新备料单每行：结存按入库后对齐、缺料清零
    latest = c.get(f"/api/prep/latest?order_id={order_id}").json()
    by_id = {l["ingredient_id"]: l for l in latest["prep_lines"]}
    assert by_id[meat_id]["stock_qty"] == 2.0
    assert by_id[meat_id]["shortage"] == 0.0
    assert by_id[rice_id]["stock_qty"] == 5.0
    assert latest["shortages"] == []

    # 缺料贴张数 / 合计同步对齐
    sh = c.get(f"/api/prep/shortages?order_id={order_id}").json()
    assert sh["shortages"] == []
    assert sh["stats"]["shortage_count"] == 0
    assert sh["stats"]["total_shortage_qty"] == 0.0

    # 已存档旧备料单全文保持入库前原样
    old = c.get(f"/api/prep/runs/{run_id}").json()
    old_meat = {l["ingredient_id"]: l for l in old["prep_lines"]}[meat_id]
    assert old_meat["stock_qty"] == 1.0
    assert old_meat["shortage"] == 1.0
    assert old["stats"]["shortage_count"] == 1
    arch_meat = {l["ingredient_id"]: l for l in archived["prep_lines"]}[meat_id]
    assert arch_meat["stock_qty"] == 1.0 and arch_meat["shortage"] == 1.0


def test_partial_inbound_recomputes_shortage_qty(client):
    c, _Session, meat_id, _rice_id, order_id = client
    c.post(f"/api/prep/run?order_id={order_id}")
    # 只补 0.4，缺口从 1.0 降到 0.6
    assert c.post("/api/inventory/inbound",
                  json={"lines": [{"ingredient_id": meat_id, "qty": 0.4}]}).status_code == 200
    sh = c.get(f"/api/prep/shortages?order_id={order_id}").json()
    assert sh["stats"]["shortage_count"] == 1
    assert sh["shortages"][0]["ingredient_id"] == meat_id
    assert sh["shortages"][0]["stock_qty"] == 1.4
    assert sh["shortages"][0]["shortage"] == 0.6
