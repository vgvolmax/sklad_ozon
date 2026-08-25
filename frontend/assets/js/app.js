globalThis.SkladOzon = globalThis.SkladOzon || {};
SkladOzon.boot = function () {
  const form=document.querySelector('#analysis-form'), button=form.querySelector('button'), loading=document.querySelector('#loading'), error=document.querySelector('#server-error');
  form.querySelector('[name=as_of]').value=new Date().toISOString().slice(0,10);
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); button.disabled=true; loading.hidden=false; error.textContent='';
    form.querySelectorAll('input[type=file]').forEach(i=>i.parentElement.querySelector('.status').textContent=i.files.length?'Выбран':'Файл не выбран');
    try {
      const response=await fetch('/api/analysis',{method:'POST',body:new FormData(form)}); const data=await response.json();
      if(!response.ok) throw new Error(data.error?.message||'Ошибка сервера'); render(data);
    } catch(e) { error.textContent=e.message; } finally { button.disabled=false; loading.hidden=true; }
  });
};
function render(data){
 const results=document.querySelector('#results'); results.hidden=false;
 const allocations=new Map(data.allocations.flatMap(x=>x.decisions.map(d=>[d.sku+'\0'+d.cluster_id,d])));
 const logistics=new Map(data.logistics.map(x=>[x.sku+'\0'+x.origin_cluster_id,x]));
 document.querySelector('#summary').textContent=`SKU проанализировано: ${new Set(data.placements.map(x=>x.sku)).size}; кандидатов размещения: ${data.placements.length}; рекомендовано Ozon, шт.: ${data.placements.reduce((s,x)=>s+x.ozon_recommended_qty,0)}; распределено optimizer, шт.: ${data.allocations.reduce((s,x)=>s+x.allocated_qty,0)}; ожидаемая прибыль плана: ${data.allocations.map(x=>x.objective_profit).join(', ')||'0'}`;
 document.querySelector('tbody').innerHTML=data.placements.map(p=>{const a=allocations.get(p.sku+'\0'+p.cluster_id),l=logistics.get(p.sku+'\0'+p.cluster_id),e=p.economics;return `<tr><td>${esc(p.sku)}</td><td>${esc(p.cluster_id)}</td><td>${p.ozon_recommended_qty}</td><td>${p.feasibility.allowed?'Да':'Нет'}</td><td>${esc(l?.coverage_status||'—')}</td><td>${e.profit_per_unit??'—'}</td><td>${e.margin_rate??'—'}</td><td>${e.roi??'—'}</td><td>${a?.allocation_qty||0}</td><td>${esc([...p.status_codes,...(a?.reason_codes||[])].join(', '))}</td></tr>`}).join('');
 document.querySelector('#signals').textContent=JSON.stringify({stockout:data.stockout_signals,distortion:data.distortion_signals},null,2);
 document.querySelector('#diagnostics').innerHTML=data.diagnostics.map(d=>`<li>${esc(d.code)} — ${esc(d.message)}</li>`).join('');
}
function esc(value){const e=document.createElement('span');e.textContent=String(value);return e.innerHTML;}
