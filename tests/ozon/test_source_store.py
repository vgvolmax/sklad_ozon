from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
import pytest
from backend.domain.contracts import SourceMode
from backend.ozon.source_contracts import OzonSourceSnapshot, source_business_date
from backend.ozon.source_store import OzonSourceSnapshotStore

def snap(identity):
 return OzonSourceSnapshot(identity,'x',date(2026,1,1),'UTC+03:00',date(2025,1,1),date(2026,1,1),(),(),(),(),(),(),(),())
def test_source_contract_and_bounded_identity_store():
 assert (SourceMode.API.value,SourceMode.FILES.value)==('api','files')
 assert source_business_date(datetime(2026,1,1,21,1,tzinfo=timezone.utc))==date(2026,1,2)
 store=OzonSourceSnapshotStore(2)
 for x in 'abc': store.put(snap(x))
 assert store.get('a') is None and store.require('c').source_snapshot_id=='c'
 with pytest.raises(FrozenInstanceError): store.require('c').source_timezone='x'
