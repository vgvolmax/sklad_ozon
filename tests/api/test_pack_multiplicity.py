from io import BytesIO
from openpyxl import Workbook
from fastapi.testclient import TestClient
import pytest

import backend.api as api
from backend.main import app
from backend.project import PackMultiplicityRecord, Project, load_project, save_project_atomic
from backend.ingestion.supplier_packaging import PackMultiplicityEvidence
from backend.pack_multiplicity import pack_multiplicity_fingerprint
from backend.shipment.api_context import ShipmentPreparationError
from tests.helpers.xlsx_fixtures import make_real_unitka

client=TestClient(app)

def xlsx(rows):
    book=Workbook(); sheet=book.active
    for row in rows: sheet.append(row)
    stream=BytesIO(); book.save(stream); return stream.getvalue()

def test_crud_import_export_and_persistence(tmp_path,monkeypatch):
    path=tmp_path/'project.json'; monkeypatch.setattr(api,'PROJECT_PATH',path)
    save_project_atomic(path,Project(pack_multiplicity={'17261':PackMultiplicityRecord(20)}))
    assert client.get('/api/project/pack-multiplicity').json()['items'][0]['source']=='unitka'
    response=client.put('/api/project/pack-multiplicity/17261',json={'pack_multiple':50})
    assert response.status_code==200 and response.json()['item']['source']=='manual'
    assert load_project(path).pack_multiplicity['17261'].override_pack_multiple==50
    response=client.post('/api/project/pack-multiplicity/import',files={'file':('packs.xlsx',xlsx([['Артикул','Кратность'],['39439',8],['bad',0]]),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert response.json()['accepted']==1 and response.json()['rejected']==1
    assert load_project(path).pack_multiplicity['17261'].override_pack_multiple==50
    assert client.delete('/api/project/pack-multiplicity/17261').json()['item']['pack_multiple']==20
    exported=client.get('/api/project/pack-multiplicity/export')
    assert exported.status_code==200 and exported.content.startswith(b'PK')


def test_mutations_clear_derived_analysis_and_shipment_stores(tmp_path,monkeypatch):
    path=tmp_path/'project.json'; monkeypatch.setattr(api,'PROJECT_PATH',path)
    save_project_atomic(path,Project(pack_multiplicity={'17261':PackMultiplicityRecord(20)}))
    cleared=[]
    monkeypatch.setattr(api.ANALYSIS_STORE,'clear',lambda:cleared.append('analysis'))
    monkeypatch.setattr(api.SHIPMENT_PLAN_STORE,'clear',lambda:cleared.append('shipment'))
    assert client.put('/api/project/pack-multiplicity/17261',json={'pack_multiple':50}).status_code==200
    assert cleared == ['analysis','shipment']


def test_delete_and_xlsx_import_mutations_clear_derived_stores(tmp_path,monkeypatch):
    path=tmp_path/'project.json'; monkeypatch.setattr(api,'PROJECT_PATH',path)
    save_project_atomic(path,Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(20,50,'manual','now')}))
    cleared=[]
    monkeypatch.setattr(api.ANALYSIS_STORE,'clear',lambda:cleared.append('analysis'))
    monkeypatch.setattr(api.SHIPMENT_PLAN_STORE,'clear',lambda:cleared.append('shipment'))

    assert client.delete('/api/project/pack-multiplicity/17261').status_code==200
    assert cleared==['analysis','shipment']
    cleared.clear()
    response=client.post('/api/project/pack-multiplicity/import',files={
        'file':('packs.xlsx',xlsx([['Артикул','Кратность'],['39439',8]]))})
    assert response.status_code==200
    assert cleared==['analysis','shipment']


def test_unitka_change_invalidates_but_noop_preserves_derived_stores(tmp_path,monkeypatch):
    path=tmp_path/'project.json'; monkeypatch.setattr(api,'PROJECT_PATH',path)
    project=Project(pack_multiplicity={'17261':PackMultiplicityRecord(20)})
    save_project_atomic(path,project)
    cleared=[]
    monkeypatch.setattr(api.ANALYSIS_STORE,'clear',lambda:cleared.append('analysis'))
    monkeypatch.setattr(api.SHIPMENT_PLAN_STORE,'clear',lambda:cleared.append('shipment'))

    with api.PROJECT_PERSISTENCE_LOCK:
        unchanged,changed=api._persist_unitka_baseline(project,(
            PackMultiplicityEvidence('17261',20,2,'x / 20',()),))
    assert changed is False and unchanged is project and cleared==[]

    with api.PROJECT_PERSISTENCE_LOCK:
        updated,changed=api._persist_unitka_baseline(project,(
            PackMultiplicityEvidence('17261',50,2,'x / 50',()),))
    assert changed is True and updated.pack_multiplicity['17261'].unitka_pack_multiple==50
    assert cleared==['analysis','shipment']


def test_unitka_import_endpoint_invalidates_only_for_baseline_change(tmp_path,monkeypatch):
    path=tmp_path/'project.json'; monkeypatch.setattr(api,'PROJECT_PATH',path)
    save_project_atomic(path,Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(20)}))
    cleared=[]
    monkeypatch.setattr(api.ANALYSIS_STORE,'clear',lambda:cleared.append('analysis'))
    monkeypatch.setattr(api.SHIPMENT_PLAN_STORE,'clear',lambda:cleared.append('shipment'))

    same=make_real_unitka(pack_rows=[['17261','36/20']])
    assert client.post('/api/import/unitka',files={'file':('unitka.xlsx',same)}).status_code==200
    assert cleared==[]

    changed=make_real_unitka(pack_rows=[['17261','100/50']])
    assert client.post('/api/import/unitka',files={'file':('unitka.xlsx',changed)}).status_code==200
    assert cleared==['analysis','shipment']


def test_failed_unitka_persistence_does_not_invalidate_stores(tmp_path,monkeypatch):
    monkeypatch.setattr(api,'PROJECT_PATH',tmp_path/'project.json')
    project=Project(pack_multiplicity={'17261':PackMultiplicityRecord(20)})
    cleared=[]
    monkeypatch.setattr(api,'save_project_atomic',lambda *_: (_ for _ in ()).throw(OSError('disk')))
    monkeypatch.setattr(api.ANALYSIS_STORE,'clear',lambda:cleared.append('analysis'))
    monkeypatch.setattr(api.SHIPMENT_PLAN_STORE,'clear',lambda:cleared.append('shipment'))
    with pytest.raises(OSError,match='disk'):
        api._persist_unitka_baseline(project,(
            PackMultiplicityEvidence('17261',50,2,'x / 50',()),))
    assert cleared==[]


def test_stale_analysis_commit_is_rejected_without_store_write(tmp_path,monkeypatch):
    path=tmp_path/'project.json'; monkeypatch.setattr(api,'PROJECT_PATH',path)
    old=Project(pack_multiplicity={'17261':PackMultiplicityRecord(20)})
    save_project_atomic(path,old)
    expected=pack_multiplicity_fingerprint(old)
    save_project_atomic(path,Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(50)}))
    writes=[]
    monkeypatch.setattr(api.ANALYSIS_STORE,'put',lambda snapshot:writes.append(snapshot))

    with pytest.raises(ShipmentPreparationError) as caught:
        api.commit_analysis_snapshot_if_current(
            object(),expected_pack_fingerprint=expected)

    assert caught.value.code=='PACK_MULTIPLICITY_CHANGED_DURING_ANALYSIS'
    assert writes==[]
