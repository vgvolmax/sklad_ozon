"""Optional historical prices: background work and immutable published evidence.

Demand/source snapshots never wait for these requests or change in place. Raw
posting references exist only in the active worker. The cache persists strictly
validated digests, SKU, lifecycle and numeric prices for one credential context.
"""

from dataclasses import dataclass, replace
import json
from math import isfinite
from pathlib import Path
from threading import RLock, Thread

from backend.domain.contracts import OrderLifecycle
from backend.ozon.adapters.orders import OrderPriceReader


@dataclass(frozen=True, slots=True)
class PriceEvidence:
    source_id: str
    orders: tuple
    prices: tuple
    completed: int
    total: int
    pending: bool
    failures: int = 0
    persistence_error: bool = False


class OrderPriceEnrichment:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = RLock()
        self._generation = 0
        self._thread = None
        self._published = None
        self._context = None
        self._cache = {}
        self._queue = []
        self._restore()

    def _restore(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data['context'], str):
                return
            cache = {}
            if not isinstance(data['prices'], list) or len(data['prices']) > 500000:
                return
            for key, lifecycle, sku, amount in data['prices']:
                if (not isinstance(key, str) or len(key) != 64 or
                    any(c not in '0123456789abcdef' for c in key) or
                    lifecycle not in {x.value for x in OrderLifecycle} or
                    not isinstance(sku, str) or not sku or len(sku) > 80 or
                    amount is not None and (isinstance(amount, bool) or
                        not isinstance(amount, (int, float)) or not isfinite(amount) or amount < 0)):
                    return
                cache.setdefault((key, lifecycle), {})[sku] = amount
            self._context, self._cache = data['context'], cache
        except (OSError, ValueError, TypeError, KeyError):
            pass

    def cache(self, context):
        with self._lock:
            if context != self._context:
                return {}
            final = {OrderLifecycle.FULFILLED.value, OrderLifecycle.CANCELLED.value}
            return {key: (dict(prices), False) for key, prices in self._cache.items() if key[1] in final}

    def cancel(self, *, clear=False):
        with self._lock:
            self._generation += 1
            if self._published:
                self._published = replace(self._published, pending=False)
            if clear:
                self._published = None; self._cache = {}; self._context = None
                self.path.unlink(missing_ok=True)

    def start(self, source, requests, client, *, is_current, commit=None, reset=False):
        with self._lock:
            self._generation += 1
            run = self._generation
            if reset or self._context != source.credential_context_id:
                self._cache = {}
            self._context = source.credential_context_id
            keys = {(r.buyer_price_key, r.lifecycle.value) for r in source.orders if r.buyer_price_key}
            self._cache = {key: prices for key, prices in self._cache.items() if key in keys}
            unique = {(r.key, r.lifecycle.value): r for r in requests if (r.key, r.lifecycle.value) in keys}
            # The normalizer supplies a key only for known prices or uniquely
            # recoverable absent prices, never explicit invalid/duplicate lines.
            allowed = {(r.buyer_price_key, r.lifecycle.value, r.sku) for r in source.orders
                       if r.buyer_price_key is not None}
            allowed.update((r.key, r.lifecycle.value, sku) for r in unique.values() for sku in r.skus)
            self._cache = {key: {sku:price for sku, price in prices.items()
                                if (*key, sku) in allowed}
                           for key, prices in self._cache.items()}
            self._queue = list(unique.values())
            self._published = PriceEvidence(source.source_snapshot_id, source.orders,
                self._frozen_prices(), 0, len(unique), bool(unique))
            self._thread = Thread(target=self._work, args=(run, tuple(unique.values()), client,
                is_current, commit), daemon=True, name='ozon-order-prices')
            self._thread.start()

    def _frozen_prices(self):
        return tuple((key, lifecycle, sku, price) for (key, lifecycle), prices in self._cache.items()
                     for sku, price in prices.items())

    def _persist(self):
        import os
        import tempfile
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent,
                    prefix='.'+self.path.name, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({'version':1, 'context':self._context, 'prices':self._frozen_prices()},
                          handle, ensure_ascii=False, separators=(',', ':'))
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def _work(self, run, requests, client, is_current, commit):
        reader = OrderPriceReader(client)
        def publish(action):
            if commit is not None:
                return commit(action)
            if is_current():
                return action()
        try:
            for index in range(1, len(requests) + 1):
                if run != self._generation or not is_current():
                    return
                with self._lock:
                    if run != self._generation:
                        return
                    request = self._queue.pop(0)
                prices, failed = reader.read(request)
                def update():
                    with self._lock:
                        if run != self._generation:
                            return
                        if not failed:
                            self._cache[request.key, request.lifecycle.value] = prices
                        state = self._published
                        checkpoint = index % 25 == 0 or index == len(requests)
                        self._published = replace(state, completed=index,
                            prices=self._frozen_prices() if checkpoint else state.prices,
                            pending=index < len(requests),
                            failures=state.failures + int(failed))
                        if checkpoint:
                            try:
                                self._persist()
                            except OSError:
                                self._published = replace(self._published, persistence_error=True)
                publish(update)
        except Exception:
            # No exception/body text crosses the private-price boundary.
            with self._lock:
                if run == self._generation:
                    self._published = replace(self._published, pending=False,
                        failures=self._published.failures + 1)
        finally:
            with self._lock:
                if run == self._generation and self._published:
                    self._published = replace(self._published, pending=False)

    def wait(self, timeout):
        thread = self._thread
        if thread:
            thread.join(timeout)

    def status(self, source_id):
        with self._lock:
            state = self._published
            if state is None or state.source_id != source_id:
                return {'pending':False, 'completed':0, 'total':0, 'failures':0}
            return {name:getattr(state, name) for name in
                    ('pending', 'completed', 'total', 'failures', 'persistence_error')}

    def prioritize(self, source_id, skus):
        with self._lock:
            if self._published is not None and self._published.source_id == source_id:
                selected = set(skus)
                self._queue.sort(key=lambda request: not bool(selected.intersection(request.skus)))

    def evidence(self, source_id, original):
        with self._lock:
            state = self._published
        status = self.status(source_id)
        if state is None or state.source_id != source_id or original is None:
            return original, status
        from backend.analytics._weeks import ObservationCoverage
        from backend.economics.daily_series import build_daily_evidence
        prices = {(key, lifecycle, sku):price for key, lifecycle, sku, price in state.prices}
        orders = tuple(replace(row, buyer_price=prices.get((row.buyer_price_key,
            row.lifecycle.value, row.sku), row.buyer_price)) if row.buyer_price is None else row
            for row in state.orders)
        fresh = build_daily_evidence(orders, ObservationCoverage(original.period_start, original.period_end),
                                     orders_complete=original.complete)
        return replace(fresh, incomplete_skus=original.incomplete_skus), status
