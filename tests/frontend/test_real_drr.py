import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def run_node(script):
    script = (f"require({json.dumps(str(ROOT / 'frontend/assets/js/components.js'))});"
              f"require({json.dumps(str(ROOT / 'frontend/assets/js/economics_workspace.js'))});" + script)
    result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_real_drr_is_read_only_and_unknown_never_uses_old_local_preferences():
    run_node("""
    const assert=require('node:assert/strict'),E=SkladOzon.EconomicsWorkspace;
    const body=E.validateTargets();
    assert.equal(body.modeled_drr,undefined);
    const product={sku:'100',article:'A',name:'Кран',qty:0,groups:{},real_drr_rate:null,
      advertising:{reason:'Нет отчёта',periods:[]}};
    const unknown=E.productRows([product]);
    assert.ok(unknown.includes('Реальный n/a'));
    assert.ok(unknown.includes('Нет отчёта'));
    const known=E.productRows([{...product,real_drr_rate:'1.5',advertising:{periods:[],spend:'300',order_revenue:'200'}}]);
    assert.ok(known.includes('Реальный 150 %'));
    assert.ok(known.includes('Расход 300 ₽'));
    """)
