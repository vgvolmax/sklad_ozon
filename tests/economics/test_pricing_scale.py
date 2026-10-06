from datetime import date
from decimal import Decimal as D
from time import perf_counter
from types import SimpleNamespace as NS

import backend.application
from backend.domain.contracts import ImportResult, ProductEconomicsInput, ReportMeta, TariffRow
from backend.economics.workspace_pricing import enrich_pricing
from tests.economics.test_pricing import settings


def test_catalog_pricing_on_9000_tariff_rows_stays_within_interactive_budget():
    rows = tuple(TariffRow(f'O{o}', f'D{d}', D(v), D(v+1), None, None, D(10+d+v))
                 for o in range(30) for d in range(30) for v in range(10))
    tariffs = ImportResult(rows, (), ReportMeta('tariffs.xlsx', 'now'), tuple(range(2,9002)))
    products = tuple(ProductEconomicsInput(f'S{i}', f'A{i}', D(100+i), 0,
        D(1000+i), D('.1'), D('1.5')) for i in range(100))
    history = tuple(NS(sku=p.sku, origin_cluster_id='O0', destination_cluster_id=f'D{d}',
        observed_qty=1) for p in products for d in range(10))
    snapshot = NS(snapshot_id='SCALE',economics_tariffs=tariffs,economics_pricing_inputs=products,
        economics_settings=settings(),route_economics=history)
    period = {'from':date(2026,9,1),'to':date(2026,9,30)}
    report = dict(period=period,observation_period=period,target_margin=D('.2'),target_roi=D('.4'),goal='margin',
        products=[dict(sku=p.sku,applied_drr_rate=D('.05'),planned_drr_rate=D('.05'),
            groups={'destination':[],'origin':[]},buyer_prices=None) for p in products])
    started = perf_counter()
    enrich_pricing(snapshot,report,{})
    elapsed = perf_counter()-started
    assert all(p['pricing_complete'] and p['target_price_all_routes'] is not None for p in report['products'])
    assert report['products'][0]['line_items']['COST'] == D('100')
    assert report['products'][-1]['line_items']['COST'] == D('199')
    assert elapsed < 5, f'100 SKU × 10 routes: {elapsed:.2f}s; budget 5s'
