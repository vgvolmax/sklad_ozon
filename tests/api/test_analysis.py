"""Task 17 transport-boundary regression tests not requiring TestClient/httpx2."""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from backend.api import wire, MAX_UPLOAD_BYTES

class Example(Enum): VALUE='value'
@dataclass(frozen=True)
class Payload:
    amount: Decimal
    state: Example
    values: tuple[int, ...]

def test_wire_serializer_preserves_decimal_and_contract_types():
    assert wire(Payload(Decimal('10.250'), Example.VALUE, (1,2))) == {'amount':'10.25','state':'value','values':[1,2]}

def test_upload_limit_and_thin_frontend_contract():
    assert MAX_UPLOAD_BYTES == 64 * 1024 * 1024
    source=Path('frontend/assets/js/app.js').read_text(encoding='utf-8')
    assert 'fetch(' in source and 'FormData' in source and '/api/' in source
    forbidden=('calculate_unit_economics','expected_logistics','SheetJS','FileReader','ArrayBuffer','JSZip')
    assert not any(token in source for token in forbidden)
