import subprocess
from pathlib import Path


def test_ndjson_parser_handles_split_and_multiple_lines():
    script = Path('frontend/assets/js/app.js').resolve()
    javascript = f'''const fs=require("fs"),vm=require("vm");
const context={{globalThis:{{}}}};context.globalThis.globalThis=context.globalThis;
vm.runInNewContext(fs.readFileSync({str(script)!r},"utf8"),context.globalThis);
const events=[],parser=context.globalThis.SkladOzon.createNdjsonParser(event=>events.push(event));
parser.push('{{"type":"pro');parser.push('gress"}}\\n{{"type":"result"}}\\n',true);
if(events.length!==2||events[0].type!=="progress"||events[1].type!=="result")process.exit(1);'''
    subprocess.run(['node', '-e', javascript], check=True)
