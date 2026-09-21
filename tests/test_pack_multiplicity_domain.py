from dataclasses import replace
from io import BytesIO
import json

import pytest
from openpyxl import Workbook, load_workbook

from backend.pack_multiplicity import (
    build_effective_pack_evidence, export_xlsx, parse_import_xlsx, reset_override, resolve_pack_multiplicity,
    pack_multiplicity_fingerprint, set_override, sync_unitka_baseline,
    validate_pack_multiple,
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


def test_effective_analysis_evidence_override_masks_invalid_unitka():
    invalid=(PackMultiplicityEvidence('17261',None,2,None,('INVALID_PACK_MULTIPLICITY',)),)
    project=Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(None,50,'manual','now'),
    })
    assert build_effective_pack_evidence(project,invalid)[0] == \
        build_effective_pack_evidence(project,invalid)[0].__class__('17261',50,'manual',())
    unknown=build_effective_pack_evidence(Project(),invalid)[0]
    assert (unknown.pack_multiple,unknown.source,unknown.reason_codes) == \
        (None,'unknown',('INVALID_PACK_MULTIPLICITY',))


def test_effective_analysis_evidence_prefers_current_unitka_over_persisted():
    current=(PackMultiplicityEvidence('17261',50,2,'x / 50',()),)
    project=Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(unitka_pack_multiple=20),
    })

    effective=build_effective_pack_evidence(project,current)[0]

    assert (effective.pack_multiple,effective.source,effective.reason_codes) == \
        (50,'unitka',())


def test_effective_analysis_evidence_prefers_override_over_current_unitka():
    current=(PackMultiplicityEvidence('17261',50,2,'x / 50',()),)
    project=Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(20,40,'manual','now'),
    })
    assert build_effective_pack_evidence(project,current)[0].pack_multiple == 40


def test_effective_analysis_evidence_current_invalid_blocks_persisted_fallback():
    current=(PackMultiplicityEvidence(
        '17261',None,2,None,('CONFLICTING_PACK_MULTIPLICITY',)),)
    project=Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(unitka_pack_multiple=20),
    })

    effective=build_effective_pack_evidence(project,current)[0]

    assert (effective.pack_multiple,effective.source,effective.reason_codes) == \
        (None,'unknown',('CONFLICTING_PACK_MULTIPLICITY',))


def test_effective_analysis_evidence_falls_back_only_when_current_is_missing():
    project=Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(unitka_pack_multiple=20),
    })
    effective=build_effective_pack_evidence(project,())[0]
    assert (effective.pack_multiple,effective.source,effective.reason_codes) == \
        (20,'unitka',())
    assert build_effective_pack_evidence(Project(),()) == ()


def test_pack_fingerprint_is_deterministic_and_pack_specific():
    left=Project(pack_multiplicity={
        'B':PackMultiplicityRecord(20), 'A':PackMultiplicityRecord(10),
    },manual_cluster_mappings={'old':'new'})
    reordered=Project(pack_multiplicity={
        'A':PackMultiplicityRecord(10), 'B':PackMultiplicityRecord(20),
    })
    changed=Project(pack_multiplicity={
        'A':PackMultiplicityRecord(10), 'B':PackMultiplicityRecord(50),
    })
    assert pack_multiplicity_fingerprint(left) == pack_multiplicity_fingerprint(reordered)
    assert pack_multiplicity_fingerprint(left) != pack_multiplicity_fingerprint(changed)

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

@pytest.mark.parametrize('reason_code', [
    'INVALID_PACK_MULTIPLICITY',
    'CONFLICTING_PACK_MULTIPLICITY',
])
def test_unitka_refresh_clears_stale_baseline_for_present_invalid_evidence(reason_code):
    project=Project(pack_multiplicity={'17261':PackMultiplicityRecord(unitka_pack_multiple=50)})
    evidence=(PackMultiplicityEvidence('17261',None,2,None,(reason_code,)),)

    updated=sync_unitka_baseline(project,evidence).pack_multiplicity['17261']

    assert updated.unitka_pack_multiple is None

def test_unitka_refresh_clears_baseline_but_preserves_override():
    project=Project(pack_multiplicity={
        '17261':PackMultiplicityRecord(50,40,'manual','now'),
    })
    evidence=(PackMultiplicityEvidence('17261',None,2,None,('INVALID_PACK_MULTIPLICITY',)),)

    updated=sync_unitka_baseline(project,evidence).pack_multiplicity['17261']
    resolved=resolve_pack_multiplicity(updated)

    assert updated.unitka_pack_multiple is None
    assert updated.override_pack_multiple == 40
    assert (resolved.pack_multiple,resolved.source)==(40,'manual')

def test_unitka_refresh_keeps_baseline_for_article_absent_from_evidence():
    project=Project(pack_multiplicity={'17261':PackMultiplicityRecord(unitka_pack_multiple=50)})
    evidence=(PackMultiplicityEvidence('39439',8,2,'x / 8',()),)

    updated=sync_unitka_baseline(project,evidence).pack_multiplicity

    assert updated['17261'].unitka_pack_multiple == 50
    assert updated['39439'].unitka_pack_multiple == 8

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
