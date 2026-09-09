from backend.ozon.endpoints import FBS_STOCK_PATH,HANDOFF_SEARCH_PATH
from backend.ozon.sync import capability_matrix
from tests.ozon.test_source_store import snap
def test_registry_and_capability_matrix_excludes_handoff():
 assert FBS_STOCK_PATH.startswith('/v2/')
 matrix=capability_matrix(snap('x')); assert 'handoff' not in matrix and matrix['ozon_comparison']['complete'] is False
