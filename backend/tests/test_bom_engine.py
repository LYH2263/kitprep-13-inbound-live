from app.services.bom_engine import explode_and_merge, project_with_live_stock

def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 10*0.2 + 5*0.3
    assert by_id[1].shortage == 2.5
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0

def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0

def test_project_with_live_stock_recalculates_after_inbound():
    snapshot = {
        "prep_lines": [
            {"ingredient_id": 1, "ingredient_code": "A", "ingredient_name": "肉", "unit": "kg",
             "need_qty": 3.5, "stock_qty": 1.0, "shortage": 2.5},
            {"ingredient_id": 2, "ingredient_code": "B", "ingredient_name": "米", "unit": "kg",
             "need_qty": 1.0, "stock_qty": 5.0, "shortage": 0.0},
        ],
        "shortages": [{"ingredient_id": 1, "shortage": 2.5}],
        "stats": {"ingredient_count": 2, "shortage_count": 1, "total_shortage_qty": 2.5},
        "order": {"id": 1, "code": "KO-1", "outlet": "城西"},
    }
    ings = {
        # 入库后结存：肉 3.5（刚好齐），米 5.0
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 3.5},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    out = project_with_live_stock(snapshot, ings)
    by_id = {l["ingredient_id"]: l for l in out["prep_lines"]}
    assert by_id[1]["need_qty"] == 3.5          # 需求仍是存档值
    assert by_id[1]["stock_qty"] == 3.5         # 库存按入库后结存
    assert by_id[1]["shortage"] == 0.0          # 缺料清零
    assert by_id[2]["shortage"] == 0.0
    assert out["shortages"] == []               # 缺料贴张数 = 0
    assert out["stats"]["shortage_count"] == 0
    assert out["stats"]["total_shortage_qty"] == 0.0
    # 存档快照本身不能被修改
    assert snapshot["prep_lines"][0]["stock_qty"] == 1.0
    assert snapshot["shortages"][0]["shortage"] == 2.5
    assert snapshot["stats"]["shortage_count"] == 1

def test_project_with_live_stock_missing_ingredient_counts_as_short():
    snapshot = {"prep_lines": [
        {"ingredient_id": 9, "ingredient_code": "X", "ingredient_name": "未知料", "unit": "kg",
         "need_qty": 2.0, "stock_qty": 2.0, "shortage": 0.0}]}
    out = project_with_live_stock(snapshot, {})
    assert out["prep_lines"][0]["stock_qty"] == 0.0
    assert out["prep_lines"][0]["shortage"] == 2.0
    assert out["stats"]["shortage_count"] == 1
