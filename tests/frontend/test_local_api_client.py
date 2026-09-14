import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "frontend/assets/js/core.js"
APP = ROOT / "frontend/assets/js/app.js"


def node_async(body):
    script = f"""
require({json.dumps(str(CORE))});
(async () => {{
{body}
}})().then(value => console.log(JSON.stringify(value)));
"""
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


def test_get_does_not_bootstrap_session_and_posts_cache_token():
    result = node_async("""
const calls=[];
const fetchImpl=async (url,init={})=>{
  calls.push({url,method:init.method||'GET',session:new Headers(init.headers).get('X-Sklad-Ozon-Session')});
  if(url==='/api/local-session') return new Response(JSON.stringify({api_version:1,session_token:'token-a'}),{status:200,headers:{'Content-Type':'application/json'}});
  return new Response('{}',{status:200,headers:{'Content-Type':'application/json'}});
};
const apiFetch=SkladOzon.createLocalApiClient(fetchImpl);
await apiFetch('/api/health');
await apiFetch('/api/one',{method:'POST'});
await apiFetch('/api/two',{method:'POST'});
return calls;
""")

    assert [call["url"] for call in result] == [
        "/api/health", "/api/local-session", "/api/one", "/api/two"
    ]
    assert result[2]["session"] == result[3]["session"] == "token-a"


def test_invalid_session_refreshes_once_and_retries_once():
    result = node_async("""
const calls=[];let bootstraps=0,posts=0;
const fetchImpl=async (url,init={})=>{
  calls.push(url);
  if(url==='/api/local-session') return new Response(JSON.stringify({session_token:`token-${++bootstraps}`}),{status:200,headers:{'Content-Type':'application/json'}});
  posts+=1;
  if(posts===2) return new Response(JSON.stringify({error:{code:'LOCAL_SESSION_INVALID'}}),{status:403,headers:{'Content-Type':'application/json'}});
  return new Response('{}',{status:200,headers:{'Content-Type':'application/json'}});
};
const apiFetch=SkladOzon.createLocalApiClient(fetchImpl);
await apiFetch('/api/first',{method:'POST'});
await apiFetch('/api/restarted',{method:'POST'});
return {calls,bootstraps,posts};
""")

    assert result == {
        "calls": [
            "/api/local-session", "/api/first", "/api/restarted",
            "/api/local-session", "/api/restarted",
        ],
        "bootstraps": 2,
        "posts": 3,
    }


def test_arbitrary_403_and_network_failure_do_not_retry_mutation():
    result = node_async("""
let bootstraps=0,foreignPosts=0,networkPosts=0;
const session=()=>new Response(JSON.stringify({session_token:`token-${++bootstraps}`}),{status:200,headers:{'Content-Type':'application/json'}});
const foreign=SkladOzon.createLocalApiClient(async (url)=>{
  if(url==='/api/local-session')return session();foreignPosts+=1;
  return new Response(JSON.stringify({error:{code:'CROSS_ORIGIN_REQUEST_BLOCKED'}}),{status:403,headers:{'Content-Type':'application/json'}});
});
await foreign('/api/mutate',{method:'POST'});
const network=SkladOzon.createLocalApiClient(async (url)=>{
  if(url==='/api/local-session')return session();networkPosts+=1;throw new TypeError('Failed to fetch');
});
try{await network('/api/mutate',{method:'POST'});}catch(_){}
return {bootstraps,foreignPosts,networkPosts};
""")

    assert result == {"bootstraps": 2, "foreignPosts": 1, "networkPosts": 1}


def test_form_data_gets_only_session_header_from_wrapper():
    result = node_async("""
let captured;
const apiFetch=SkladOzon.createLocalApiClient(async (url,init={})=>{
  if(url==='/api/local-session')return new Response(JSON.stringify({session_token:'token'}),{status:200,headers:{'Content-Type':'application/json'}});
  captured=Object.fromEntries(new Headers(init.headers).entries());return new Response('{}');
});
await apiFetch('/api/analysis',{method:'POST',body:new FormData()});
return captured;
""")

    assert result == {"x-sklad-ozon-session": "token"}


def test_app_uses_single_api_fetch_boundary_for_all_requests():
    source = APP.read_text()

    assert "createLocalApiClient" in source
    assert "fetch(" not in source
    assert "apiFetch(" in source


def test_session_token_is_not_persisted_or_logged():
    source = CORE.read_text()

    assert "localStorage" not in source[source.index("S.createLocalApiClient"):source.index("S.createInitialState")]
    assert "sessionStorage" not in source
    assert "console.log" not in source
