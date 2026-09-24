"""Exact, backend-owned Ozon import workbook rendering."""
from dataclasses import dataclass
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import hashlib, re
from openpyxl import Workbook

OZON_TEMPLATE_HEADERS=("артикул","имя (необязательно)","количество")
XLSX_MEDIA="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

class ShipmentExportError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)

@dataclass(frozen=True,slots=True)
class ExportArtifact:
    content: bytes
    media_type: str
    filename: str

def _rows(assignments):
    grouped={}
    for row in assignments:
        article=row.article.strip() if isinstance(row.article,str) else ""
        if not article: raise ShipmentExportError("EXPORT_ARTICLE_REQUIRED")
        if (isinstance(row.quantity,bool) or not isinstance(row.quantity,int) or row.quantity<=0 or
            isinstance(row.pack_multiple,bool) or not isinstance(row.pack_multiple,int) or row.pack_multiple<=0 or
            row.quantity%row.pack_multiple): raise ShipmentExportError("EXPORT_PACK_VIOLATION")
        key=(row.destination_cluster_id,article); identity=(row.sku,row.pack_multiple)
        if not isinstance(row.destination_cluster_id,str) or not row.destination_cluster_id.strip(): raise ShipmentExportError("EXPORT_IDENTITY_CONFLICT")
        if key in grouped and grouped[key][:2]!=identity: raise ShipmentExportError("EXPORT_IDENTITY_CONFLICT")
        grouped[key]=(*identity,grouped.get(key,(None,None,0))[2]+row.quantity)
    return grouped

def _workbook(rows):
    wb=Workbook();ws=wb.active;ws.append(OZON_TEMPLATE_HEADERS)
    for article,sku,qty in sorted(rows,key=lambda x:(x[0],x[1])):ws.append((article,None,qty))
    stream=BytesIO();wb.save(stream);return stream.getvalue()

def render_export(option,shipment_plan_id):
    accepted=option.outcome.validation.accepted_assignments
    if not accepted: raise ShipmentExportError("EXPORT_EMPTY")
    grouped=_rows(accepted); clusters=sorted({key[0] for key in grouped})
    short_plan=shipment_plan_id.removeprefix("sp_")[:8];short_option=option.option_id.removeprefix("cs_")[:8]
    outer=f"ozon_supply_{short_plan}_{short_option}"
    def cluster_rows(cluster): return [(article,sku,data[2]) for (c,article),data in grouped.items() if c==cluster for sku in (data[0],)]
    if len(clusters)==1:return ExportArtifact(_workbook(cluster_rows(clusters[0])),XLSX_MEDIA,outer+".xlsx")
    stream=BytesIO()
    with ZipFile(stream,"w",ZIP_DEFLATED) as archive:
        for index,cluster in enumerate(clusters,1):
            safe=re.sub(r'[\\/\x00-\x1f:]+','_',cluster).replace('..','_').strip(' ._') or 'cluster'
            safe=safe[:80]; suffix=hashlib.sha256(cluster.encode()).hexdigest()[:8]
            archive.writestr(f"{index:02d}_{safe}_{suffix}.xlsx",_workbook(cluster_rows(cluster)))
    return ExportArtifact(stream.getvalue(),"application/zip",outer+".zip")


def render_source_statement(option, working_plan, shipment_plan_id):
    """Manager-only provenance worksheet; never an Ozon import template."""
    if working_plan is None or not option.outcome.validation.accepted_assignments:
        raise ShipmentExportError("EXPORT_EMPTY")
    indexed={(row.sku,row.destination_cluster_id):row for row in working_plan.lines}
    assignments=option.outcome.validation.accepted_assignments
    workbook=Workbook()
    sheet=workbook.active
    sheet.title="Источники количеств"
    sheet.append(("SKU","Кластер","Источник","Запрошено, шт.",
                  "Принято Ozon, шт.","Рабочий план","Проверенный план"))
    for row in sorted(assignments,key=lambda item:(item.sku,item.destination_cluster_id)):
        line=indexed.get((row.sku,row.destination_cluster_id))
        if line is None or line.working_qty is None or row.quantity>line.working_qty:
            raise ShipmentExportError("EXPORT_IDENTITY_CONFLICT")
        sheet.append((row.sku,row.destination_cluster_id,line.selected_source,
                      line.requested_qty,row.quantity,working_plan.working_plan_id,
                      shipment_plan_id))
    stream=BytesIO()
    workbook.save(stream)
    return ExportArtifact(stream.getvalue(),XLSX_MEDIA,
                          f"ozon_source_statement_{shipment_plan_id[:12]}.xlsx")
