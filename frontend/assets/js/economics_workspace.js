(function(root){'use strict';
const S=root.SkladOzon=root.SkladOzon||{};
const KEY='sklad_ozon.economics_workspace_v1';
const defaults={targetMargin:'20',targetRoi:'40',plannedDrr:'5',goal:'margin',overrides:{}};
let preferences=defaults;
try{
  const stored=JSON.parse(root.localStorage?.getItem(KEY)||'null');
  if(stored&&typeof stored==='object')preferences={...defaults,...stored,overrides:stored.overrides&&typeof stored.overrides==='object'?stored.overrides:{}};
  delete preferences.modeledDrr;
}catch(_){/* Invalid local preferences cannot prevent opening the screen. */}
let state={search:'',filter:'all',mode:'products',limit:12,openSku:null,openGroup:null,groupMode:{},report:null,key:null,busy:false,error:'',runId:0};
let currentRoot=null,currentSnapshot=null,currentFetch=null;
let drawing=false;
let periodFrom=null,periodTo=null,periodDraft=null,granularity='day';
let onCostsChanged=null,costGeneration=0;
const costDrafts={},costErrors={},costSaving={};
let advertisingQueue=[],advertisingBusy=false,advertisingError='';
const editingBusy=()=>advertisingBusy||state.exporting||Object.values(costSaving).some(Boolean);
const e=S.escapeHtml;
const n=value=>value==null||value===''||!Number.isFinite(Number(value))?null:Number(value);
const money=value=>n(value)==null?'Не рассчитано':`${new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n(value))} ₽`;
const pct=value=>n(value)==null?'—':`${new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(n(value)*100)} %`;
const qty=value=>`${new Intl.NumberFormat('ru-RU').format(Number(value)||0)} шт.`;
function validated(){
  const fields=[['targetMargin',0,95],['targetRoi',0,1000],['plannedDrr',0,90]];
  const result={};
  for(const [field,min,max] of fields){
    const value=Number(String(preferences[field]).trim().replace(',','.'));
    if(!Number.isFinite(value)||value<min||value>max||String(preferences[field]).trim()==='')throw Error(`Проверьте ${field==='targetMargin'?'целевую маржу':field==='targetRoi'?'целевой ROI':'плановый ДРР'}. Допустимо ${min}–${max} %.`);
    result[field]=String(value/100);
  }
  const overrides={};
  for(const [sku,raw] of Object.entries(preferences.overrides)){
    const v=Number(String(raw).replace(',','.'));
    if(!Number.isFinite(v)||v<0||v>90)throw Error(`Проверьте плановый ДРР для SKU ${sku}.`);
    overrides[sku]=String(v/100);
  }
  return {target_margin:result.targetMargin,target_roi:result.targetRoi,planned_drr:result.plannedDrr,goal:preferences.goal,per_sku_drr:overrides,...(periodFrom?{period_from:periodFrom,period_to:periodTo}:{})};
}
function persist(){try{root.localStorage?.setItem(KEY,JSON.stringify(preferences));}catch(_){/* Work remains usable without local preference storage. */}}
function requestKey(snapshot){return JSON.stringify([snapshot.snapshot_id,preferences,periodFrom,periodTo]);}
async function load(){
  const snap=currentSnapshot,run=++state.runId;
  state={...state,key:requestKey(snap),busy:true,error:''};draw();
  let body;
  try{body=validated();}catch(error){state={...state,busy:false,error:error.message};draw();return;}
  try{
    const response=await currentFetch('/api/economics/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_snapshot_id:snap.snapshot_id,...body})});
    const payload=await response.json();
    if(run!==state.runId||currentSnapshot?.snapshot_id!==snap.snapshot_id)return;
    if(!response.ok)throw Error(payload.error?.message||'Экономика недоступна.');
    if(payload.snapshot_id!==snap.snapshot_id)throw Error('Снимок изменился. Обновите расчёт.');
    state={...state,report:payload.workspace,busy:false,error:''};draw();
  }catch(error){if(run!==state.runId)return;state={...state,busy:false,error:error.message||'Экономика недоступна.'};draw();}
}
function costCell(p,index){
  const error=costErrors[p.sku]||'',busy=costSaving[p.sku];
  const source=p.cost_source==='manual'?'Ручная':p.cost_source==='import'?'Из юнитки':'Из расчёта';
  return `<label class="econ-cost-cell"><input type="number" min="0" max="1000000000000" step="0.01" inputmode="decimal" data-econ-cost="${e(p.sku)}" data-article="${e(p.article||'')}" value="${e(costDrafts[p.sku]??p.cost??'')}" aria-label="Себестоимость артикула ${e(p.article||p.sku)}, рубли" aria-describedby="econ-cost-error-${index}" ${error?'aria-invalid="true"':''} ${busy||state.exporting||advertisingBusy||!p.article?'disabled':''}> ₽</label><small class="econ-cost-status" role="status">${busy?'Сохраняем…':p.cost==null?'Укажите себестоимость':source}</small><small id="econ-cost-error-${index}" class="field-error" ${error?'':'hidden'}>${e(error)}</small>${error?`<button type="button" data-econ-cost-retry="${e(p.sku)}">Повторить сохранение</button>`:''}`;
}
async function saveCost(input){
  const sku=input.dataset.econCost,article=input.dataset.article,value=input.value.trim().replace(',','.'),number=Number(value);
  if(costSaving[sku]||state.exporting||advertisingBusy)return;
  costDrafts[sku]=value;
  if(!value||!Number.isFinite(number)||number<0||number>1e12){costErrors[sku]='Введите себестоимость от 0 до 1 000 000 000 000 ₽.';draw();[...currentRoot.querySelectorAll('[data-econ-cost]')].find(x=>x.dataset.econCost===sku)?.focus();return;}
  const snap=currentSnapshot,generation=costGeneration;
  costSaving[sku]=true;delete costErrors[sku];draw();
  try{
    const response=await currentFetch('/api/project/cost-prices/'+encodeURIComponent(article),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({cost:value})});
    const data=await response.json();
    if(!response.ok)throw Error(data.error?.message||'Не удалось сохранить себестоимость.');
    if(generation!==costGeneration){if(data.changed)onCostsChanged?.();return;}
    delete costDrafts[sku];delete costErrors[sku];
    if(data.changed){onCostsChanged?.();state.stale=true;state.costChanged=true;}
    costSaving[sku]=false;
    if(currentSnapshot?.snapshot_id===snap.snapshot_id)await load();
  }catch(error){if(generation===costGeneration)costErrors[sku]=error.message||'Не удалось сохранить. Повторите.';}
  finally{if(generation===costGeneration){costSaving[sku]=false;draw();const field=[...currentRoot.querySelectorAll('[data-econ-cost]')].find(x=>x.dataset.econCost===sku);if(root.document?.activeElement===root.document?.body)field?.focus({preventScroll:true});}}
}
async function downloadReport(){
  if(state.busy||advertisingBusy||state.exporting||Object.keys(costDrafts).length||Object.values(costSaving).some(Boolean))return;
  const snap=currentSnapshot,key=state.key;
  state.exporting=true;state.error='';draw();
  try{
    const response=await currentFetch('/api/economics/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_snapshot_id:snap.snapshot_id,...validated()})});
    if(!response.ok){const data=await response.json();throw Error(data.error?.message||'Отчёт не удалось скачать.');}
    const blob=await response.blob();
    if(currentSnapshot?.snapshot_id!==snap.snapshot_id||state.key!==key)throw Error('Параметры изменились. Скачайте отчёт повторно.');
    const url=root.URL.createObjectURL(blob),a=root.document.createElement('a');
    a.href=url;a.download='Экономика.xlsx';root.document.body.append(a);a.click();a.remove();root.URL.revokeObjectURL(url);
  }catch(error){state.error=error.message||'Отчёт не удалось скачать.';}
  finally{state.exporting=false;draw();}
}
function productsForView(report){
  const query=state.search.trim().toLocaleLowerCase('ru');
  return (report.products||[]).filter(p=>{
    if(query&&![p.article,p.sku,p.name,...p.groups.destination.map(g=>g.key),...p.groups.origin.map(g=>g.key)].some(v=>String(v||'').toLocaleLowerCase('ru').includes(query)))return false;
    if(state.filter==='below'&&!p.below_goal)return false;
    if(state.filter==='margin'&&!p.below_margin)return false;
    if(state.filter==='roi'&&!p.below_roi)return false;
    if(state.filter==='cluster'&&![...p.groups.destination,...p.groups.origin].some(g=>g.below_margin||g.below_roi))return false;
    if(state.filter==='incomplete'&&!p.partial&&!p.no_observations)return false;
    return true;
  }).sort((a,b)=>Number(b.modeled_shortfall)-Number(a.modeled_shortfall)||String(a.article).localeCompare(String(b.article),'ru'));
}
function routeTable(routes){return `<div class="econ-route-scroll"><table class="econ-route-table"><thead><tr><th>Источник отгрузки</th><th>Кластер спроса</th><th>Доставлено</th><th>Логистика / шт.</th><th>Маржа</th><th>ROI</th><th>Недобор</th></tr></thead><tbody>${routes.map(r=>`<tr><td>${e(r.origin)}</td><td>${e(r.destination)}</td><td>${qty(r.qty)}</td><td>${money(r.logistics)}</td><td class="${n(r.margin)!=null&&n(r.margin)<n(state.report.target_margin)?'econ-below':''}">${pct(r.margin)}</td><td class="${n(r.roi)!=null&&n(r.roi)<n(state.report.target_roi)?'econ-below':''}">${pct(r.roi)}</td><td>${money(r.gap)}</td></tr>`).join('')}</tbody></table></div>`;}
function clusterMarkup(p,index){
  const mode=state.groupMode[p.sku]||'destination',groups=p.groups[mode];
  return `<div class="econ-drill"><div class="econ-drill-head"><div><strong>Разбор кластеров · ${e(p.article||p.sku)}</strong><p>Два разреза одних доставленных заказов. Их суммы не складываются.</p></div><div class="econ-segmented" role="group" aria-label="Роль кластера"><button type="button" data-econ-group-mode="destination" data-sku="${e(p.sku)}" aria-pressed="${mode==='destination'}">Где заказали</button><button type="button" data-econ-group-mode="origin" data-sku="${e(p.sku)}" aria-pressed="${mode==='origin'}">Откуда отгрузили</button></div></div><div class="econ-clusters">${groups.map((g,i)=>{
    const key=p.sku+'|'+mode+'|'+g.key,open=state.openGroup===key;
    return `<article class="econ-cluster ${g.below_margin||g.below_roi?'is-below':''} ${open?'is-open':''}"><button type="button" class="econ-cluster-head" data-econ-group="${e(key)}" aria-expanded="${open}" aria-controls="econ-group-${index}-${i}"><span><strong>${open?'▾':'▸'} ${mode==='destination'?'Кластер спроса':'Источник отгрузки'}: ${e(g.key)}</strong><small>${g.partial?'Расчёт неполный':g.below_margin||g.below_roi?'Ниже одной из целей':'В пределах целей'}</small></span><span>${qty(g.qty)}${g.partial?`<small>рассчитано ${g.covered_qty}</small>`:''}</span><span>${money(g.profit_per_unit)}<small>прибыль / шт.</small></span><span class="${g.below_margin?'econ-below':''}">${pct(g.margin)}<small>маржа</small></span><span class="${g.below_roi?'econ-below':''}">${pct(g.roi)}<small>ROI</small></span><span class="${n(g.modeled_shortfall)>0?'econ-below':''}">${money(g.modeled_shortfall)}<small>недобор</small></span></button>${open?`<div id="econ-group-${index}-${i}" class="econ-cluster-routes">${routeTable(g.routes)}${g.partial?`<p>${g.qty-g.covered_qty} шт. без расчёта исключены из средних и недобора.</p>`:''}</div>`:''}</article>`;
  }).join('')}</div></div>`;
}
function fact(value){return `<div class="econ-fact"><small class="econ-band-label">Факт</small>${value}</div>`;}
function plan(value,label='План'){return `<div class="econ-plan"><small class="econ-band-label">${label}</small>${value}</div>`;}
function realDrrMarkup(p){
  const known=n(p.real_drr_rate)!=null;
  return `<strong class="econ-real-drr">Реальный ${known?pct(p.real_drr_rate):'n/a'}</strong>${known?'':'<small class="econ-drr-assumption">В расчёте 0 %</small>'}`;
}
function realDrrDetails(p){
  const a=p.advertising||{},known=n(p.real_drr_rate)!=null;
  const periods=(a.periods||[]).map(period=>`${e(period.from)}–${e(period.to)}`).join(', ');
  return `<details class="econ-drr-details"><summary>Расходы и период</summary>${known?`<small>Расход ${money(a.spend)}</small><small>Все заказы ${money(a.order_revenue)}</small>${periods?`<small>${periods}</small>`:''}`:`<small>${e(a.reason||'Нет полного расчёта ДРР.')}</small>`}</details>`;
}

function advertisingMarkup(report){
  const campaigns=report?.advertising_campaigns||[],pending=advertisingQueue.filter(x=>x.status==='pending'||x.status==='error');
  const disabled=state.busy||editingBusy();
  return `<section class="panel econ-advertising" aria-labelledby="econ-ads-title"><div class="econ-advertising-head"><div><h3 id="econ-ads-title">Расходы на рекламу <small>необязательно</small></h3><p>Отчёты Ozon по товарам с группировкой по дням. Сопоставим SKU с артикулами и рассчитаем общий ДРР по всем заказам за тот же период.</p></div><label class="econ-advertising-picker">Выбрать XLSX <input id="econ-ads-files" type="file" accept=".xlsx" multiple aria-label="Выбрать отчёты о расходах на рекламу" ${disabled?'disabled':''}></label></div><p class="econ-advertising-hint">До 20 файлов за раз, до 16 МБ каждый и 64 МБ суммарно. Повторная загрузка не удваивает расходы; пересекающиеся дни той же кампании заменяются. Разные кампании складываются.</p>${advertisingQueue.length?`<ul class="econ-advertising-list" aria-label="Файлы для загрузки">${advertisingQueue.map((item,i)=>`<li><div><strong>${e(item.file.name)}</strong><small ${item.status==='error'?'class="field-error"':''}>${e(item.message||'Готов к загрузке')}${item.unmatched?.length?` Не найдены SKU: ${e(item.unmatched.join(', '))}.`:''}</small>${item.matched?.length?`<details class="econ-ads-matches"><summary>Сопоставлено по SKU: ${item.matched.length}</summary><ul>${item.matched.map(p=>`<li>SKU ${e(p.sku)} · ${e(p.article||'Без артикула')} · ${e(p.name||'Без названия')}</li>`).join('')}</ul></details>`:''}</div><button type="button" data-econ-ads-remove-file="${i}" aria-label="Убрать файл ${e(item.file.name)}" ${advertisingBusy?'disabled':''}>Убрать</button></li>`).join('')}</ul><button type="button" id="econ-ads-upload" ${!pending.length||disabled?'disabled':''}>${advertisingBusy?'Загружаем…':pending.some(x=>x.status==='error')?'Повторить загрузку':'Загрузить отчёты'}${pending.length&&!advertisingBusy?` · ${pending.length}`:''}</button>${advertisingQueue.some(x=>['imported','duplicate','unmatched'].includes(x.status))?` <button type="button" id="econ-ads-clear-completed" ${advertisingBusy?'disabled':''}>Очистить обработанные</button>`:''}`:''}<p class="field-error" role="alert" ${advertisingError?'':'hidden'}>${e(advertisingError)}</p><p role="status">${advertisingBusy?'Сохраняем расходы и обновляем экономику…':campaigns.length?`Сохранено кампаний: ${campaigns.length}`:'Отчётов пока нет. Реальный ДРР — n/a.'}</p>${campaigns.length?`<details class="econ-advertising-campaigns"><summary>Загруженные кампании · ${campaigns.length}</summary><ul class="econ-advertising-list">${campaigns.map(c=>`<li><div><strong>Кампания № ${e(c.campaign_id)} · ${money(c.spend)}</strong><small>${e(c.period_start)}–${e(c.period_end)} · ${c.day_count} дней · ${c.sku_count} SKU</small><small>${e(c.filename)}</small></div><button type="button" data-econ-ads-delete="${e(c.campaign_id)}" ${disabled?'disabled':''}>Удалить</button></li>`).join('')}</ul></details>`:''}</section>`;
}
async function uploadAdvertising(){
  if(state.busy||editingBusy())return;
  const entries=advertisingQueue.filter(x=>x.status==='pending'||x.status==='error');
  if(!entries.length)return;
  if(entries.reduce((sum,x)=>sum+x.file.size,0)>64*1024*1024){advertisingError='Суммарный размер превышает 64 МБ. Уберите часть файлов и загрузите их следующей пачкой.';draw();return;}
  const snap=currentSnapshot,fetch=currentFetch,body=new root.FormData();
  body.append('analysis_snapshot_id',snap.snapshot_id);
  for(const entry of entries)body.append('files',entry.file);
  advertisingBusy=true;advertisingError='';draw();
  try{
    const response=await fetch('/api/economics/advertising/import',{method:'POST',body});
    const data=await response.json();
    if(!response.ok)throw Error(data.error?.message||'Не удалось загрузить расходы. Повторите.');
    if(!Array.isArray(data.files)||data.files.length!==entries.length)throw Error('Не удалось подтвердить загрузку. Повторите.');
    entries.forEach((entry,i)=>{const result=data.files[i];entry.status=result.status;entry.message=result.message;entry.unmatched=result.unmatched_skus;entry.matched=result.matched_products;});
    state.key=null;
    await load();
  }catch(error){advertisingError=error.message||'Не удалось загрузить расходы. Повторите.';entries.forEach(entry=>{entry.status='error';entry.message=advertisingError;});}
  finally{advertisingBusy=false;draw();currentRoot.querySelector('#econ-ads-upload:not(:disabled)')?.focus({preventScroll:true});}
}
async function deleteAdvertising(campaignId){
  if(state.busy||editingBusy())return;
  const snap=currentSnapshot,fetch=currentFetch;
  advertisingBusy=true;advertisingError='';draw();
  try{
    const response=await fetch('/api/economics/advertising/'+encodeURIComponent(campaignId),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_snapshot_id:snap.snapshot_id})});
    const data=await response.json();
    if(!response.ok)throw Error(data.error?.message||'Не удалось удалить кампанию. Повторите.');
    state.key=null;
    await load();
  }catch(error){advertisingError=error.message||'Не удалось удалить кампанию. Повторите.';}
  finally{advertisingBusy=false;draw();currentRoot.querySelector('#econ-ads-files')?.focus({preventScroll:true});}
}
function bindAdvertising(c){
  c.querySelector('#econ-ads-files')?.addEventListener('change',event=>{
    if(state.busy||editingBusy())return;
    const files=[...event.target.files];
    if(files.length+advertisingQueue.length>20){advertisingError='В списке может быть до 20 файлов. Уберите обработанные файлы перед следующей пачкой.';draw();return;}
    advertisingError='';
    for(const file of files){const error=!file.name.toLowerCase().endsWith('.xlsx')?'Нужен файл XLSX.':file.size>16*1024*1024?'Файл превышает 16 МБ.':file.size===0?'Файл пуст.':'';advertisingQueue.push({file,status:error?'invalid':'pending',message:error});}
    draw();c.querySelector('#econ-ads-upload')?.focus({preventScroll:true});
  });
  c.querySelector('#econ-ads-upload')?.addEventListener('click',uploadAdvertising);
  c.querySelector('#econ-ads-clear-completed')?.addEventListener('click',()=>{if(advertisingBusy)return;advertisingQueue=advertisingQueue.filter(x=>!['imported','duplicate','unmatched'].includes(x.status));draw();c.querySelector('#econ-ads-files')?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-ads-remove-file]').forEach(button=>button.onclick=()=>{if(advertisingBusy)return;advertisingQueue.splice(Number(button.dataset.econAdsRemoveFile),1);advertisingError='';draw();c.querySelector('#econ-ads-files')?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-ads-delete]').forEach(button=>button.onclick=()=>{if(state.busy||editingBusy())return;const id=button.dataset.econAdsDelete;S.AppDialog.open({title:`Удалить кампанию № ${id}?`,body:'<p>Расходы этой кампании будут исключены из реального ДРР. Если других отчётов для товара нет, его реальный ДРР станет n/a.</p>',confirmLabel:'Удалить кампанию',onConfirm:()=>deleteAdvertising(id)});});
}
function productRows(products,report=state.report){return products.map((p,index)=>{
  const open=state.openSku===p.sku;
  const drrPlan=`<label class="econ-drr-cell">План <input type="number" min="0" max="90" step="0.5" inputmode="decimal" data-econ-drr="${e(p.sku)}" value="${e(preferences.overrides[p.sku]??preferences.plannedDrr)}" aria-label="Плановый ДРР для артикула ${e(p.article||p.sku)}" aria-describedby="econ-drr-error-${index}" ${editingBusy()?'disabled':''}> %</label><small id="econ-drr-error-${index}" class="field-error econ-drr-error" hidden></small>`;
  return `<tr data-econ-row="${e(p.sku)}" class="econ-sku-row ${open?'is-open':''} ${p.below_margin||p.below_roi?'is-below':''}"><td><button type="button" class="econ-sku-button" data-econ-sku="${e(p.sku)}" aria-expanded="${open}" aria-controls="econ-detail-${index}"><strong>${open?'▾':'▸'} ${e(p.article||'Нет артикула')} · ${e(p.name||'Без названия')}</strong><small>SKU ${e(p.sku)}</small></button>${p.no_observations?'<span class="econ-pill">Нет доставленных заказов</span>':p.partial?'<span class="econ-pill">Неполный расчёт</span>':''}${p.below_goal?'<span class="econ-pill">Ниже цели</span>':''}</td><td>${fact(qty(p.qty)+(p.partial?`<small>рассчитано ${p.covered_qty}</small>`:''))}</td><td>${fact(money(p.price))}${plan(money(p.target_price_all_routes)+'<small>для всех известных маршрутов</small>','План · цена до цели')}</td><td>${fact(costCell(p,index))}</td><td>${fact(pct(p.commission_rate)+`<small>${money(p.commission_per_unit)} / шт.</small>`)}</td><td>${fact(realDrrMarkup(p))}<div class="econ-plan">${drrPlan}</div>${realDrrDetails(p)}</td><td>${fact(money(p.profit_per_unit)+'<small>за шт.</small>')}</td><td>${fact(pct(p.margin))}${plan(pct(report?.target_margin),'План · цель')}</td><td>${fact(pct(p.roi))}${plan(pct(report?.target_roi),'План · цель')}</td><td>${plan(money(p.modeled_shortfall)+(p.partial?'<small>только известное</small>':''),'До плана')}</td></tr>${open?`<tr class="econ-sku-detail" id="econ-detail-${index}"><td colspan="10">${clusterMarkup(p,index)}</td></tr>`:''}${S.EconomicsDaily?`<tr class="econ-daily-row ${open?'is-open':''}"><td colspan="10">${S.EconomicsDaily.markup(p.sku)}</td></tr>`:''}`;
}).join('');}

function renderProducts(report){const filtered=productsForView(report),shown=filtered.slice(0,state.limit);return `<section class="panel econ-main"><div class="econ-main-head"><div><h2>Товары и кластеры</h2><p>Средние по рассчитанным маршрутам взвешены по доставленным штукам.</p></div><div class="econ-segmented" role="group" aria-label="Представление экономики"><button type="button" data-econ-mode="products" aria-pressed="${state.mode==='products'}">По товарам</button><button type="button" data-econ-mode="routes" aria-pressed="${state.mode==='routes'}">Маршруты</button></div></div><div class="econ-tools"><label class="econ-search">Поиск <span class="search-input"><input type="search" id="econ-search" value="${e(state.search)}" placeholder="Артикул, SKU или кластер">${state.search?'<button type="button" id="econ-search-clear" aria-label="Очистить поиск">Очистить</button>':''}</span></label><div class="econ-filters" role="group" aria-label="Фильтр экономики">${[['all','Все'],['below','Ниже цели'],['margin','Маржа ниже'],['roi','ROI ниже'],['cluster','Проблемный кластер'],['incomplete','Неполные']].map(([key,label])=>`<button type="button" data-econ-filter="${key}" aria-pressed="${state.filter===key}">${label}</button>`).join('')}</div></div><p class="econ-value-legend"><span class="econ-fact-key">Факт · по данным снимка · сверху</span><span class="econ-plan-key">План и цель · снизу</span></p><p class="econ-counter">Показано ${shown.length} из ${filtered.length} товаров · ${report.products.length} всего</p><div class="econ-table-scroll"><table class="econ-table"><thead><tr><th>Артикул / товар</th><th>Доставлено</th><th>Цена продавца</th><th>Себестоимость</th><th>Комиссия Ozon</th><th>ДРР</th><th>Прибыль / шт.</th><th>Маржа</th><th>ROI</th><th>Недобор до плана</th></tr></thead><tbody>${shown.length?productRows(shown):'<tr><td colspan="10" class="econ-empty">Товаров по выбранным условиям нет.</td></tr>'}</tbody></table></div>${filtered.length>shown.length?`<div class="econ-more"><button type="button" data-econ-more>Показать ещё · осталось ${filtered.length-shown.length}</button></div>`:''}</section>`;}
function renderRoutes(report){
  const rows=productsForView(report).flatMap(p=>p.groups.destination.flatMap(g=>g.routes.map(r=>({p,r}))));
  const shown=rows.slice(0,state.limit);
  return `<section class="panel econ-main"><div class="econ-main-head"><div><h2>Точные маршруты</h2><p>Источник исполнения и кластер спроса указаны отдельно.</p></div><div class="econ-segmented" role="group" aria-label="Представление экономики"><button type="button" data-econ-mode="products" aria-pressed="false">По товарам</button><button type="button" data-econ-mode="routes" aria-pressed="true">Маршруты</button></div></div><p class="econ-counter">Показано ${shown.length} из ${rows.length} маршрутов</p><div class="econ-table-scroll"><table class="econ-route-table econ-route-list"><thead><tr><th>Артикул / товар</th><th>Источник отгрузки</th><th>Кластер спроса</th><th>Доставлено</th><th>Логистика / шт.</th><th>Маржа</th><th>ROI</th><th>Недобор</th></tr></thead><tbody>${shown.length?shown.map(({p,r})=>`<tr><td><strong>${e(p.article||'Нет артикула')}</strong> · ${e(p.name||'Без названия')}<small>SKU ${e(p.sku)}</small></td><td>${e(r.origin)}</td><td>${e(r.destination)}</td><td>${qty(r.qty)}</td><td>${money(r.logistics)}</td><td class="${n(r.margin)!=null&&n(r.margin)<n(report.target_margin)?'econ-below':''}">${pct(r.margin)}</td><td class="${n(r.roi)!=null&&n(r.roi)<n(report.target_roi)?'econ-below':''}">${pct(r.roi)}</td><td>${money(r.gap)}</td></tr>`).join(''):'<tr><td colspan="8" class="econ-empty">Маршрутов по выбранным условиям нет.</td></tr>'}</tbody></table></div>${rows.length>shown.length?`<div class="econ-more"><button type="button" data-econ-more>Показать ещё · осталось ${rows.length-shown.length}</button></div>`:''}</section>`;
}
function periodText(period){return period?`${e(period.from)}–${e(period.to)}`:'период наблюдения неизвестен';}
function periodMarkup(report){
  const observation=report?.observation_period;
  if(!observation)return '';
  const selected=periodDraft||report.period||observation;
  return `<section class="panel econ-period-controls"><form id="econ-period-form" novalidate><div><h3>Период расчёта</h3><p>История заказов: ${periodText(observation)}. Даты включительно.</p></div><label>С <input type="date" id="econ-period-from" name="from" min="${e(observation.from)}" max="${e(observation.to)}" value="${e(selected.from)}" required></label><label>По <input type="date" id="econ-period-to" name="to" min="${e(observation.from)}" max="${e(observation.to)}" value="${e(selected.to)}" required></label><button type="submit" id="econ-period-apply" ${state.busy||editingBusy()?'disabled':''}>Применить период</button><button type="button" id="econ-period-reset" ${state.busy||editingBusy()?'disabled':''}>Вся история</button></form><div class="econ-segmented" role="group" aria-label="Шаг графиков">${[['day','По дням'],['week','По неделям']].map(([key,label])=>`<button type="button" data-econ-granularity="${key}" aria-pressed="${granularity===key}">${label}</button>`).join('')}</div><p>Период общий для экономики, рекламы, графиков и Excel. В таблице — доставленные единицы; на графиках и в ДРР — все заказы.</p></section>`;
}
function viewPosition(){
  const active=root.document?.activeElement;
  const focused=active&&currentRoot.contains?.(active)?
    ['data-econ-drr','data-econ-cost','id'].map(key=>[key,active.getAttribute(key)]).find(([,value])=>value):null;
  const rows=[...currentRoot.querySelectorAll('[data-econ-row]')];
  const anchor=active?.closest?.('[data-econ-row]')||rows.find(row=>{
    const rect=row.getBoundingClientRect();return rect.bottom>0&&rect.top<(root.innerHeight||0);
  });
  return {focused,sku:anchor?.dataset.econRow,top:anchor?.getBoundingClientRect().top};
}
function restorePosition(position){
  const anchor=[...currentRoot.querySelectorAll('[data-econ-row]')].find(row=>row.dataset.econRow===position.sku);
  if(anchor&&typeof root.scrollBy==='function')root.scrollBy(0,anchor.getBoundingClientRect().top-position.top);
  if(position.focused){
    const [attribute,value]=position.focused;
    const input=[...currentRoot.querySelectorAll(`[${attribute}]`)].find(node=>node.getAttribute(attribute)===value);
    input?.focus({preventScroll:true});
  }
}
function draw(){
  if(!currentRoot)return;
  drawing=true;
  try{
  const position=viewPosition();
  const oldTable=currentRoot.querySelector('.econ-table-scroll');
  const oldScroll=oldTable?.scrollLeft||0,oldScrollTop=oldTable?.scrollTop||0,report=state.report;
  currentRoot.innerHTML=`<div class="econ-page" aria-busy="${state.busy}">${state.stale?`<div class="notice notice-warning" role="status">${state.costChanged?'Себестоимость сохранена и учтена ниже. Пересчитайте план, чтобы обновить распределение поставок.':'Входные данные изменились. Пересчитайте план, чтобы обновить экономику.'}</div>`:''}<div class="workspace-intro"><p class="eyebrow">ЭКОНОМИКА · МОДЕЛЬ ПО ДАННЫМ СНИМКА</p><h2>Товары ниже цели</h2><p>Настройте цель и плановый ДРР, затем проверьте, какой кластер влияет на товар как источник отгрузки и как место заказа.</p></div><section class="panel econ-targets"><form id="econ-target-form" novalidate><div><h3>Целевые показатели</h3><p>Реальный ДРР из отчётов — для маржи и ROI; при n/a используем 0 %. Плановый — для необходимой цены.</p></div><label>Маржа, % <input name="margin" type="number" min="0" max="95" step="0.5" value="${e(preferences.targetMargin)}" required></label><label>ROI, % <input name="roi" type="number" min="0" max="1000" step="1" value="${e(preferences.targetRoi)}" required></label><label>Плановый ДРР, % <input name="drr" type="number" min="0" max="90" step="0.5" value="${e(preferences.plannedDrr)}" required></label><fieldset><legend>Цену рассчитать до</legend><label><input type="radio" name="goal" value="margin" ${preferences.goal==='margin'?'checked':''}> Маржи</label><label><input type="radio" name="goal" value="roi" ${preferences.goal==='roi'?'checked':''}> ROI</label></fieldset><button type="submit" class="primary" ${state.busy||editingBusy()?'disabled':''}>Применить настройки</button></form><div class="econ-exports"><button type="button" id="econ-export" ${!report||state.error||state.busy||advertisingBusy||state.exporting||Object.keys(costDrafts).length||Object.values(costSaving).some(Boolean)?'disabled':''}>Скачать отчёт XLSX</button><a class="button-link" href="/api/project/cost-prices/export" download="Себестоимость.xlsx">Скачать себестоимость</a><span role="status">${state.exporting?'Готовим отчёт…':state.busy?'Пересчитываем…':'Себестоимость сохраняется после ввода'}</span></div><p id="econ-error" class="field-error" role="alert" ${state.error?'':'hidden'}>${e(state.error)}</p></section>${advertisingMarkup(report)}${periodMarkup(report)}${report?`<div class="econ-summary"><div class="econ-plan-key"><span>Модельный недобор до ${report.goal==='margin'?'маржи':'ROI'}</span><strong>${money(report.modeled_shortfall)}</strong><small>По рассчитанным доставленным маршрутам</small></div><div class="econ-plan-key"><span>SKU ниже выбранной цели</span><strong>${report.products.filter(p=>p.below_goal).length}</strong><small>Из ${report.products.length} с маршрутами</small></div><div><span>Неполные SKU</span><strong>${report.incomplete_sku_count}</strong><small>Нет маршрутов или часть без расчёта</small></div><div data-econ-period-summary><span>Период расчёта</span><strong>${periodText(report.period)}</strong><small>Доставленные заказы по дате принятия${report.history_complete===false?' · история неполная':''}</small></div></div>${state.mode==='products'?renderProducts(report):renderRoutes(report)}<details class="panel econ-method"><summary>Как рассчитаны показатели</summary><p>Недобор — положительная разница между целевой и модельной прибылью на единицу, умноженная на доставленное количество каждого известного маршрута. Это не фактический убыток по выкупам или выплатам Ozon. Экономика использует доставленные заказы по дате принятия за выбранный период, включая загруженную часть текущей недели. Прибыль рассчитана по текущим ценам, ставкам и тарифам снимка; это модель экономики за период.</p><p>Реальный ДРР — сумма расходов загруженных кампаний с НДС / стоимость всех заказов FBO и FBS этого SKU за те же дни, включая отменённые, по цене продавца. Учитываются только дни рекламных отчётов внутри выбранного периода расчёта. Даты считаются один раз, расходы разных кампаний складываются. Продажи, приписанные рекламе, и проценты из отчёта не используются. Если расходы, полная история заказов или цены отсутствуют, реальный ДРР — n/a, в расчёте маржи и ROI он принимается равным 0 %. Это допущение показано рядом с ДРР. Маржа и ROI пересчитаны с реальным ДРР и сохранённой себестоимостью. Плановая маржа в Excel — заданная цель. Необходимая цена рассчитана до выбранной цели (маржа или ROI) при неизменной логистике, комиссии, налоговом режиме и плановом ДРР. Изменение тарифа или спроса при новой цене не моделируется. Неполные маршруты блокируют единую цену по всем маршрутам.</p></details>`:'<section class="panel econ-loading">'+(state.busy?'Рассчитываем экономику…':state.error?'Исправьте параметры или пересчитайте план.':'Загрузить расчёт экономики.')+'</section>'}</div>`;
  const sc=currentRoot.querySelector('.econ-table-scroll');if(sc){sc.scrollLeft=oldScroll;sc.scrollTop=oldScrollTop;}
  bind();
  S.EconomicsDaily?.mount(currentRoot,currentSnapshot.snapshot_id,currentFetch,{period:report?.period,granularity});
  restorePosition(position);
  }finally{drawing=false;}
}
function bind(){
  const c=currentRoot,form=c.querySelector('#econ-target-form');
  form.onsubmit=event=>{event.preventDefault();if(state.busy||editingBusy())return;S.FormState.clearErrors(form);let invalid=false;for(const [field,min,max] of [['margin',0,95],['roi',0,1000],['drr',0,90]]){const raw=form.elements[field].value.trim(),value=Number(raw.replace(',','.'));if(!raw||!Number.isFinite(value)||value<min||value>max){S.FormState.setError(form,field,`Введите число от ${min} до ${max} %.`);invalid=true;}}if(invalid){state.error='Исправьте значения в настройках.';const error=c.querySelector('#econ-error');error.hidden=false;error.textContent=state.error;c.querySelector('#econ-export').disabled=true;S.FormState.focusFirst(form);return;}preferences={...preferences,targetMargin:form.elements.margin.value,targetRoi:form.elements.roi.value,plannedDrr:form.elements.drr.value,goal:form.elements.goal.value};try{validated();}catch(error){state={...state,error:error.message};draw();return;}persist();state={...state,filter:'all',limit:12,openGroup:null};load();};
  bindAdvertising(c);
  const periodForm=c.querySelector('#econ-period-form');
  if(periodForm){
    const remember=()=>{periodDraft={from:periodForm.elements.from.value,to:periodForm.elements.to.value};};
    periodForm.oninput=remember;
    periodForm.onsubmit=event=>{
      event.preventDefault();if(state.busy||editingBusy())return;remember();S.FormState.clearErrors(periodForm);
      const {from,to}=periodDraft,observation=state.report.observation_period;
      const field=!from||from<observation.from||from>observation.to?'from':!to||to<from||to>observation.to?'to':null;
      if(field){S.FormState.setError(periodForm,field,'Выберите даты внутри истории; начало не позже конца.');S.FormState.focusFirst(periodForm);return;}
      periodFrom=from;periodTo=to;load();
    };
    c.querySelector('#econ-period-reset').onclick=()=>{if(state.busy||editingBusy())return;periodFrom=periodTo=periodDraft=null;load();};
  }
  c.querySelectorAll('[data-econ-granularity]').forEach(button=>button.onclick=()=>{
    granularity=button.dataset.econGranularity;draw();
    [...c.querySelectorAll('[data-econ-granularity]')].find(node=>node.dataset.econGranularity===granularity)?.focus({preventScroll:true});
  });
  c.querySelector('#econ-export')?.addEventListener('click',downloadReport);
  c.querySelector('#econ-search-clear')?.addEventListener('click',()=>{state.search='';state.limit=12;draw();c.querySelector('#econ-search')?.focus();});
  c.querySelectorAll('[data-econ-cost]').forEach(input=>{input.oninput=()=>{costDrafts[input.dataset.econCost]=input.value;const exportButton=c.querySelector('#econ-export');if(exportButton)exportButton.disabled=true;};input.onchange=()=>{if(!drawing)return saveCost(input);};input.onkeydown=event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();saveCost(input);}};});
  c.querySelectorAll('[data-econ-cost-retry]').forEach(button=>button.onclick=()=>saveCost([...c.querySelectorAll('[data-econ-cost]')].find(x=>x.dataset.econCost===button.dataset.econCostRetry)));
  c.querySelectorAll('[data-econ-filter]').forEach(b=>b.onclick=()=>{state={...state,filter:b.dataset.econFilter,limit:12};draw();[...c.querySelectorAll('[data-econ-filter]')].find(x=>x.dataset.econFilter===b.dataset.econFilter)?.focus({preventScroll:true});});
  const search=c.querySelector('#econ-search');if(search){const applySearch=()=>{const q=search.value;state={...state,search:q,limit:12};draw();const next=c.querySelector('#econ-search');next?.focus({preventScroll:true});next?.setSelectionRange(q.length,q.length);};let composing=false;search.oncompositionstart=()=>{composing=true;};search.oncompositionend=()=>{composing=false;applySearch();};search.oninput=event=>{if(!composing&&!event.isComposing)applySearch();};}
  c.querySelectorAll('[data-econ-mode]').forEach(b=>b.onclick=()=>{state={...state,mode:b.dataset.econMode,limit:12};draw();[...c.querySelectorAll('[data-econ-mode]')].find(x=>x.dataset.econMode===b.dataset.econMode)?.focus({preventScroll:true});});
  c.querySelector('[data-econ-more]')?.addEventListener('click',()=>{state={...state,limit:state.limit+12};draw();});
  c.querySelectorAll('[data-econ-sku]').forEach(b=>b.onclick=()=>{state={...state,openSku:state.openSku===b.dataset.econSku?null:b.dataset.econSku,openGroup:null};draw();[...c.querySelectorAll('[data-econ-sku]')].find(x=>x.dataset.econSku===b.dataset.econSku)?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-group-mode]').forEach(b=>b.onclick=()=>{state.groupMode[b.dataset.sku]=b.dataset.econGroupMode;state.openGroup=null;draw();[...c.querySelectorAll('[data-econ-group-mode]')].find(x=>x.dataset.sku===b.dataset.sku&&x.dataset.econGroupMode===b.dataset.econGroupMode)?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-group]').forEach(b=>b.onclick=()=>{state.openGroup=state.openGroup===b.dataset.econGroup?null:b.dataset.econGroup;draw();[...c.querySelectorAll('[data-econ-group]')].find(x=>x.dataset.econGroup===b.dataset.econGroup)?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-drr]').forEach(input=>input.onchange=()=>{if(drawing||editingBusy())return;const value=input.value.replace(',','.'),number=Number(value);if(!value.trim()||!Number.isFinite(number)||number<0||number>90){input.setAttribute('aria-invalid','true');const error=c.querySelector('#'+input.getAttribute('aria-describedby'));if(error){error.hidden=false;error.textContent='Введите ДРР от 0 до 90 %.';}input.focus();return;}preferences.overrides[input.dataset.econDrr]=value;persist();load();});
}
function render(rootElement,snapshot,apiFetch,{stale=false,onCostChange=null}={}){
  if(currentSnapshot?.snapshot_id!==snapshot.snapshot_id){costGeneration++;state.report=null;periodFrom=periodTo=periodDraft=null;for(const map of [costDrafts,costErrors,costSaving])for(const key of Object.keys(map))delete map[key];state.costChanged=false;}
  onCostsChanged=onCostChange;
  currentRoot=rootElement;currentSnapshot=snapshot;currentFetch=apiFetch;state.stale=stale;
  const key=requestKey(snapshot);
  if(state.key!==key)load();else draw();
}
S.EconomicsWorkspace={render,productsForView,productRows,validateTargets:validated};
})(globalThis);
