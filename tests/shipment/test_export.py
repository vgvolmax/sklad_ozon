from io import BytesIO
from dataclasses import replace
from decimal import Decimal
from zipfile import ZipFile
from openpyxl import load_workbook
from backend.shipment.export import OZON_TEMPLATE_HEADERS,XLSX_MEDIA,render_export
from backend.ozon.draft_contracts import ValidationState
from backend.shipment.ranking import rank_outcomes
from .test_ranking import outcome,scenario

def test_exact_single_cluster_workbook():
    ranked,_=rank_outcomes((outcome("cs_a",ValidationState.ACCEPTED),),scenario())
    artifact=render_export(ranked[0],"sp_123456789")
    assert artifact.media_type==XLSX_MEDIA
    ws=load_workbook(BytesIO(artifact.content)).active
    assert tuple(ws.cell(1,x).value for x in range(1,4))==OZON_TEMPLATE_HEADERS
    assert ws.max_column==3
    assert ws["D1"].value is None and ws["B2"].value is None and ws["C2"].value==6

def test_zip_workbooks_contain_only_their_destination_cluster_rows():
    original=outcome("cs_a",ValidationState.ACCEPTED)
    m=replace(original.candidate.assignments[0],article="40750")
    k=replace(original.candidate.assignments[0],sku="sku-k",article="40751",
              destination_cluster_id="K",quantity=12,total_volume_l=Decimal("12"))
    candidate=replace(original.candidate,cluster_ids=("M","K"),assignments=(m,k),
        total_qty=18,total_volume_l=Decimal("18"))
    validation=replace(original.validation,accepted_assignments=(m,k))
    ranked,_=rank_outcomes((replace(original,candidate=candidate,validation=validation),),scenario())
    artifact=render_export(ranked[0],"sp_123456789")
    with ZipFile(BytesIO(artifact.content)) as archive:
        names=archive.namelist()
        assert len(names)==2
        assert all(name.endswith(".xlsx") and not name.endswith("/") and "/" not in name
                   for name in names)
        workbook_rows={
            tuple(load_workbook(BytesIO(archive.read(name))).active.iter_rows(
                min_row=2,values_only=True))
            for name in names
        }
        assert workbook_rows=={(("40750",None,6),),(("40751",None,12),)}
        for name in names:
            sheet=load_workbook(BytesIO(archive.read(name))).active
            assert sheet.max_column==3
