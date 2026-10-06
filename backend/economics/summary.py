"""Selected-period model profit and known uploaded costs, without DRR allocation."""
from decimal import Decimal, localcontext


def summarize_products(products, *, history_complete=True):
    quantity = sum(p['qty'] for p in products)
    covered = sum(p.get('before_ads_covered_qty', p['covered_qty']) for p in products)
    profits = [p['profit_before_ads_total'] for p in products
               if p['profit_before_ads_total'] is not None]
    reported = [p['advertising'] for p in products
                if p.get('advertising') and p['advertising']['spend'] is not None]
    with localcontext() as context:
        context.prec = 40
        before = (sum(profits, Decimal('0')) if profits else
                  Decimal('0') if products and quantity == 0 and history_complete else None)
        spend = sum((a['spend'] for a in reported), Decimal('0')) if reported else None
        after = before - spend if before is not None and spend is not None else None
    return {'qty': quantity, 'covered_qty': covered,
            'profit_before_ads': before, 'advertising_spend': spend,
            'profit_after_uploaded_ads': after,
            'profit_partial': covered != quantity or not history_complete,
            'advertising_sku_count': len(reported), 'selected_sku_count': len(products)}
