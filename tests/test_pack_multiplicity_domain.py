from dataclasses import replace
from io import BytesIO
import json

import pytest
from openpyxl import Workbook, load_workbook

from backend.pack_multiplicity import (
    export_xlsx, parse_import_xlsx, reset_override, resolve_pack_multiplicity,
    set_override, sync_unitka_baseline, validate_pack_multiple,
)
from backend.ingestion.supplier_packaging import PackMultiplicityEvidence
from backend.project import PackMultiplicityRecord, Project, load_project, save_project_atomic


def workbook(rows):
    book=Workbook(); sheet=book.active
    for row in rows: sheet.append(row)
    stream=BytesIO(); book.save(stream); book.close(); return stream.getvalue()


def test_effective_precedence_reset_and_origins():
    base=PackMultiplicityRecord(unitka_pack_multiple=20)
    assert resolve_pack_multiplicity(base).source == 'unitka'
    project,article=set_override(Project(pack_multiplicity={'17261':base}),17261.0,40,'manual',updated_at='now')
    resolved=resolve_pack_multiplicity(project.pack_multiplicity[article])
    assert (resolved.pack_multiple,resolved.source,resolved.unitka_pack_multiple)==(40,'manual',20)
    project,_=set_override(project,'17261',50,'import',updated_at='later')
    assert resolve_pack_multiplicity(project.pack_multiplicity['17261']).source == 'import'
    project,_=reset_override(project,'17261')
    assert resolve_pack_multiplicity(project.pack_multiplicity['17261']).pack_multiple == 20
    assert resolve_pack_multiplicity(None).source == 'unknown'

@pytest.mark.parametrize('value', [1,50])
def test_valid_pack_multiple(value): assert validate_pack_multiple(value)==value
@pytest.mark.parametrize('value', [0,-1,1.5,True,'50 шт.',float('nan')])
def test_invalid_pack_multiple(value):
    with pytest.raises(ValueError): validate_pack_multiple(value)

def test_unitka_refresh_preserves_override_and_updates_baseline():
    project=Project(pack_multiplicity={'17261':PackMultiplicityRecord(20,40,'manual','now')})
    evidence=(PackMultiplicityEvidence('17261',25,2,'x / 25',()),)
    updated=sync_unitka_baseline(project,evidence).pack_multiplicity['17261']
    assert (updated.unitka_pack_multiple,updated.override_pack_multiple)==(25,40)

def test_v1_migrates_and_v2_round_trip_persists(tmp_path):
    path=tmp_path/'project.json'; save_project_atomic(path,Project())
    payload=json.loads(path.read_text()); payload['schema_version']=1; payload.pop('pack_multiplicity'); path.write_text(json.dumps(payload))
    assert load_project(path).pack_multiplicity=={}
    project=Project(pack_multiplicity={'17261':PackMultiplicityRecord(20,50,'manual','now')})
    save_project_atomic(path,project); assert load_project(path)==project

def test_xlsx_mixed_duplicate_upsert_and_reimportable_export():
    values,errors=parse_import_xlsx(workbook([['Артикул','Кратность'],[17261.0,50],['BAD',0],['39439',8],['39439',9]]))
    assert values=={'17261':50}
    assert {e.code for e in errors}=={'INVALID_PACK_MULTIPLICITY','DUPLICATE_ARTICLE'}
    data=export_xlsx([{'article':'17261','pack_multiple':50,'source':'manual','unitka_pack_multiple':20,'updated_at':'now','skus':['1'],'product_name':'Товар'}])
    imported,errors=parse_import_xlsx(data)
    assert imported=={'17261':50} and not errors
    sheet=load_workbook(BytesIO(data),read_only=True).active
    assert next(sheet.values)[:2]==('Артикул','Кратность')
