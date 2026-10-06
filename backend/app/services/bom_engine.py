"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients, shortage = need - stock."""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float
def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion."""
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
        ))
    return lines

def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
        },
    }

def project_with_live_stock(snapshot: dict, ingredients: dict[int, dict]) -> dict:
    """用当前结存重算已生成备料单快照中的 stock_qty / shortage / 缺料张数。

    - prep_lines 的需求量(need_qty)、原料行保持存档时原样，只替换库存与缺料；
    - 库存里已对不上号的原料（被删除等）按结存 0 处理，缺料即全部需求，不会漏报；
    - 不改写传入的快照（存档 result_json 原样保留）。
    """
    projected: list[dict] = []
    for line in snapshot.get("prep_lines", []):
        iid = line["ingredient_id"]
        ing = ingredients.get(iid)
        stock = round(float(ing.get("stock_qty", 0.0)), 3) if ing else 0.0
        row = dict(line)
        row["stock_qty"] = stock
        row["shortage"] = round(max(0.0, float(line["need_qty"]) - stock), 3)
        if ing:
            row["ingredient_code"] = ing.get("code", row.get("ingredient_code", ""))
            row["ingredient_name"] = ing.get("name", row.get("ingredient_name", ""))
            row["unit"] = ing.get("unit", row.get("unit", ""))
        projected.append(row)
    result = dict(snapshot)
    result["prep_lines"] = projected
    result["shortages"] = [dict(l) for l in projected if l["shortage"] > 0]
    result["stats"] = {
        "ingredient_count": len(projected),
        "shortage_count": len(result["shortages"]),
        "total_shortage_qty": round(sum(l["shortage"] for l in projected), 3),
    }
    result["stock_live"] = True
    return result
