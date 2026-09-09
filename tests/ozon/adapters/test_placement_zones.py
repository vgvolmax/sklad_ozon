from backend.ozon.adapters.placement_zones import normalize_placement_zones
def test_exact_multiple_and_unknown_zones():
 rows,diags=normalize_placement_zones({'result':{'items':[{'sku':'S','zones':['A','B']},{'sku':'X'}]}})
 assert rows[0].zones==('A','B') and not rows[1].complete and diags
