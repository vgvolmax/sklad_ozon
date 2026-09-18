from io import BytesIO
from openpyxl import Workbook
from fastapi.testclient import TestClient

import backend.api as api
from backend.main import app
from backend.project import PackMultiplicityRecord, Project, load_project, save_project_atomic

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
