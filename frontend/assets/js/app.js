globalThis.SkladOzon = globalThis.SkladOzon || {};
SkladOzon.createNdjsonParser = function (onEvent) {
  let buffer='';
  return {push(chunk, final=false) {buffer+=chunk;const lines=buffer.split('\n');buffer=lines.pop();for(const line of lines)if(line.trim())onEvent(JSON.parse(line));if(final&&buffer.trim()){onEvent(JSON.parse(buffer));buffer='';}}};
};
SkladOzon.boot = function () {
  const form=document.querySelector('#analysis-form'), button=form.querySelector('button'), panel=document.querySelector('#loading'), error=document.querySelector('#server-error');
  const bar=document.querySelector('#analysis-progress'), message=document.querySelector('#progress-message'), stage=document.querySelector('#progress-stage'), detail=document.querySelector('#progress-detail'), count=document.querySelector('#progress-count'), time=document.querySelector('#progress-time');
  const reportLabels={availability:'Доступность товаров',restrictions:'Ограничения складов',orders:'История заказов',unitka:'Юнитка Ozon',economics:'Тарифы и экономика'};
  form.querySelector('[name=as_of]').value=new Date().toISOString().slice(0,10);
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); button.disabled=true; panel.hidden=false; panel.classList.remove('error'); error.textContent='';bar.value=0;
    const started=performance.now(), timer=setInterval(()=>time.textContent=`Прошло: ${clock((performance.now()-started)/1000)}`,250);
    form.querySelectorAll('input[type=file]').forEach(i=>i.parentElement.querySelector('.status').textContent=i.files.length?'Выбран':'Файл не выбран');
    try {
      const response=await fetch('/api/analysis/stream',{method:'POST',body:new FormData(form)});
      if(!response.ok){const data=await response.json();throw new Error(data.error?.message||'Ошибка сервера');}
      if(!response.body)throw new Error('Сервер не поддерживает потоковый ответ');
      const reader=response.body.getReader(), decoder=new TextDecoder();let gotResult=false;
      const parser=SkladOzon.createNdjsonParser(handle);
      while(true){const {value,done}=await reader.read();parser.push(decoder.decode(value||new Uint8Array(),{stream:!done}),done);if(done)break;}
      if(!gotResult)throw new Error('Поток завершён без результата');
      function handle(item){
        if(!item||!['progress','result','error'].includes(item.type))throw new Error('Некорректное событие протокола');
        if(item.type==='progress'){message.textContent=item.message;stage.textContent=`Этап ${item.stage_index} из ${item.stage_count}`;detail.textContent=reportLabels[item.detail]||'';count.textContent=item.total?`${item.current} / ${item.total}`:'';bar.value=((item.stage_index-1)+(item.total?item.current/item.total:0))/item.stage_count*100;}
        else if(item.type==='result'){gotResult=true;bar.value=100;message.textContent=`Готово за ${(item.elapsed_ms/1000).toFixed(1)} с`;stage.textContent='Этап 9 из 9';count.textContent='';render(item.data);}
        else {panel.classList.add('error');message.textContent=`Ошибка на этапе «${message.textContent}»`;throw new Error(item.error?.message||'Ошибка анализа');}
      }
    } catch(e) { panel.classList.add('error');error.textContent=e.message; } finally { clearInterval(timer);button.disabled=false; }
  });
};
function clock(seconds){const value=Math.floor(seconds);return `${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}`;}
function render(data){
 const results=document.querySelector('#results'); results.hidden=false;
 document.querySelectorAll('#analysis-form input[type=file]').forEach(input=>{
   const status=data.input_statuses[input.name];
   input.parentElement.querySelector('.status').textContent=status.ok?`Проверено · ${status.record_count} записей`:`Есть ошибки · ${status.record_count} записей`;
 });
 const allocations=new Map(data.allocations.flatMap(x=>x.decisions.map(d=>[d.sku+'\0'+d.cluster_id,d])));
 const logistics=new Map(data.logistics.map(x=>[x.sku+'\0'+x.origin_cluster_id,x]));
 document.querySelector('#summary').textContent=`SKU проанализировано: ${data.summary.sku_count}; кандидатов размещения: ${data.summary.placement_count}; рекомендовано Ozon, шт.: ${data.summary.ozon_recommended_qty}; распределено optimizer, шт.: ${data.summary.allocated_qty}; ожидаемая прибыль плана: ${data.summary.objective_profit}`;
 document.querySelector('tbody').innerHTML=data.placements.map(p=>{const a=allocations.get(p.sku+'\0'+p.cluster_id),l=logistics.get(p.sku+'\0'+p.cluster_id),e=p.economics;return `<tr><td>${esc(p.sku)}</td><td>${esc(p.cluster_id)}</td><td>${p.ozon_recommended_qty}</td><td>${p.feasibility.allowed?'Да':'Нет'}</td><td>${esc(l?.coverage_status||'—')}</td><td>${e.profit_per_unit??'—'}</td><td>${e.margin_rate??'—'}</td><td>${e.roi??'—'}</td><td>${a?.allocation_qty||0}</td><td>${esc([...p.status_codes,...(a?.reason_codes||[])].join(', '))}</td></tr>`}).join('');
 document.querySelector('#signals').textContent=JSON.stringify({stockout:data.stockout_signals,distortion:data.distortion_signals},null,2);
 document.querySelector('#diagnostics').innerHTML=data.diagnostics.map(d=>`<li>${esc(d.code)} — ${esc(d.message)}</li>`).join('');
}
function esc(value){const e=document.createElement('span');e.textContent=String(value);return e.innerHTML;}
