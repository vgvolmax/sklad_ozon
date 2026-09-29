(function(root){'use strict';
const S=root.SkladOzon=root.SkladOzon||{};
const KEY='sklad_ozon.economics_workspace_v1';
const defaults={targetMargin:'20',targetRoi:'40',plannedDrr:'5',goal:'margin',overrides:{}};
let preferences=defaults;
try{
  const stored=JSON.parse(root.localStorage?.getItem(KEY)||'null');
  if(stored&&typeof stored==='object')preferences={...defaults,...stored,overrides:stored.overrides&&typeof stored.overrides==='object'?stored.overrides:{}};
}catch(_){/* Invalid local preferences cannot prevent opening the screen. */}
let state={search:'',filter:'all',mode:'products',limit:12,openSku:null,openGroup:null,groupMode:{},report:null,key:null,busy:false,error:'',runId:0};
let currentRoot=null,currentSnapshot=null,currentFetch=null;
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
  return {target_margin:result.targetMargin,target_roi:result.targetRoi,planned_drr:result.plannedDrr,goal:preferences.goal,per_sku_drr:overrides};
}
function persist(){try{root.localStorage?.setItem(KEY,JSON.stringify(preferences));}catch(_){/* Work remains usable without local preference storage. */}}
function requestKey(snapshot){return JSON.stringify([snapshot.snapshot_id,preferences]);}
async function load(){
  const snap=currentSnapshot,run=++state.runId;
  state={...state,key:requestKey(snap),busy:true,error:'',report:null};draw();
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
function productRows(products,report=state.report){return products.map((p,index)=>{
  const open=state.openSku===p.sku;
  return `<tr class="econ-sku-row ${open?'is-open':''} ${p.below_margin||p.below_roi?'is-below':''}"><td><button type="button" class="econ-sku-button" data-econ-sku="${e(p.sku)}" aria-expanded="${open}" aria-controls="econ-detail-${index}"><strong>${open?'▾':'▸'} ${e(p.article||'Нет артикула')} · ${e(p.name||'Без названия')}</strong><small>SKU ${e(p.sku)}</small></button>${p.no_observations?'<span class="econ-pill">Нет доставленных заказов</span>':p.partial?'<span class="econ-pill">Неполный расчёт</span>':''}</td><td>${qty(p.qty)}${p.partial?`<small>рассчитано ${p.covered_qty}</small>`:''}</td><td>${money(p.price)}</td><td>${pct(p.commission_rate)}</td><td><small>В модели ${pct(p.assumed_drr_rate)}</small><label class="econ-drr-cell">План <input type="number" min="0" max="90" step="0.5" inputmode="decimal" data-econ-drr="${e(p.sku)}" value="${e(preferences.overrides[p.sku]??preferences.plannedDrr)}" aria-label="Плановый ДРР для артикула ${e(p.article||p.sku)}" aria-describedby="econ-drr-error-${index}"> %</label><small id="econ-drr-error-${index}" class="field-error econ-drr-error" hidden></small></td><td>${money(p.profit_per_unit)}<small>за шт.</small></td><td class="${p.below_margin?'econ-below':''}">${pct(p.margin)}<small>цель ${pct(report?.target_margin)}</small></td><td class="${p.below_roi?'econ-below':''}">${pct(p.roi)}<small>цель ${pct(report?.target_roi)}</small></td><td class="${n(p.modeled_shortfall)>0?'econ-below':''}">${money(p.modeled_shortfall)}${p.partial?'<small>только известное</small>':''}</td><td>${p.target_price_all_routes==null?'Не рассчитано':money(p.target_price_all_routes)}<small>для всех известных маршрутов</small></td></tr>${open?`<tr class="econ-sku-detail" id="econ-detail-${index}"><td colspan="10">${clusterMarkup(p,index)}</td></tr>`:''}`;
}).join('');}
function renderProducts(report){const filtered=productsForView(report),shown=filtered.slice(0,state.limit);return `<section class="panel econ-main"><div class="econ-main-head"><div><h2>Товары и кластеры</h2><p>Средние по рассчитанным маршрутам взвешены по доставленным штукам.</p></div><div class="econ-segmented" role="group" aria-label="Представление экономики"><button type="button" data-econ-mode="products" aria-pressed="${state.mode==='products'}">По товарам</button><button type="button" data-econ-mode="routes" aria-pressed="${state.mode==='routes'}">Маршруты</button></div></div><div class="econ-tools"><label class="econ-search">Поиск <input type="search" id="econ-search" value="${e(state.search)}" placeholder="Артикул, SKU или кластер"></label><div class="econ-filters" role="group" aria-label="Фильтр экономики">${[['all','Все'],['below','Ниже цели'],['margin','Маржа ниже'],['roi','ROI ниже'],['cluster','Проблемный кластер'],['incomplete','Неполные']].map(([key,label])=>`<button type="button" data-econ-filter="${key}" aria-pressed="${state.filter===key}">${label}</button>`).join('')}</div></div><p class="econ-counter">Показано ${shown.length} из ${filtered.length} товаров · ${report.products.length} всего</p><div class="econ-table-scroll"><table class="econ-table"><thead><tr><th>Артикул / товар</th><th>Доставлено</th><th>Цена</th><th>Комиссия Ozon</th><th>ДРР</th><th>Прибыль / шт.</th><th>Маржа</th><th>ROI</th><th>Модельный недобор</th><th>Цена до цели</th></tr></thead><tbody>${shown.length?productRows(shown):'<tr><td colspan="10" class="econ-empty">Товаров по выбранным условиям нет.</td></tr>'}</tbody></table></div>${filtered.length>shown.length?`<div class="econ-more"><button type="button" data-econ-more>Показать ещё · осталось ${filtered.length-shown.length}</button></div>`:''}</section>`;}
function renderRoutes(report){
  const rows=productsForView(report).flatMap(p=>p.groups.destination.flatMap(g=>g.routes.map(r=>({p,r}))));
  const shown=rows.slice(0,state.limit);
  return `<section class="panel econ-main"><div class="econ-main-head"><div><h2>Точные маршруты</h2><p>Источник исполнения и кластер спроса указаны отдельно.</p></div><div class="econ-segmented" role="group" aria-label="Представление экономики"><button type="button" data-econ-mode="products" aria-pressed="false">По товарам</button><button type="button" data-econ-mode="routes" aria-pressed="true">Маршруты</button></div></div><p class="econ-counter">Показано ${shown.length} из ${rows.length} маршрутов</p><div class="econ-table-scroll"><table class="econ-route-table econ-route-list"><thead><tr><th>Артикул / товар</th><th>Источник отгрузки</th><th>Кластер спроса</th><th>Доставлено</th><th>Логистика / шт.</th><th>Маржа</th><th>ROI</th><th>Недобор</th></tr></thead><tbody>${shown.length?shown.map(({p,r})=>`<tr><td><strong>${e(p.article||'Нет артикула')}</strong> · ${e(p.name||'Без названия')}<small>SKU ${e(p.sku)}</small></td><td>${e(r.origin)}</td><td>${e(r.destination)}</td><td>${qty(r.qty)}</td><td>${money(r.logistics)}</td><td class="${n(r.margin)!=null&&n(r.margin)<n(report.target_margin)?'econ-below':''}">${pct(r.margin)}</td><td class="${n(r.roi)!=null&&n(r.roi)<n(report.target_roi)?'econ-below':''}">${pct(r.roi)}</td><td>${money(r.gap)}</td></tr>`).join(''):'<tr><td colspan="8" class="econ-empty">Маршрутов по выбранным условиям нет.</td></tr>'}</tbody></table></div>${rows.length>shown.length?`<div class="econ-more"><button type="button" data-econ-more>Показать ещё · осталось ${rows.length-shown.length}</button></div>`:''}</section>`;
}
function periodText(period){return period?`${e(period.from)}–${e(period.to)}`:'период наблюдения неизвестен';}
function draw(){
  if(!currentRoot)return;
  const oldScroll=currentRoot.querySelector('.econ-table-scroll')?.scrollLeft||0,report=state.report;
  currentRoot.innerHTML=`<div class="econ-page">${state.stale?'<div class="notice notice-warning" role="status">Входные данные изменились. Пересчитайте план, чтобы обновить экономику.</div>':''}<div class="workspace-intro"><p class="eyebrow">ЭКОНОМИКА · МОДЕЛЬ ПО ДАННЫМ СНИМКА</p><h2>Товары ниже цели</h2><p>Настройте цель и плановый ДРР, затем проверьте, какой кластер влияет на товар как источник отгрузки и как место заказа.</p></div><section class="panel econ-targets"><form id="econ-target-form"><div><h3>Целевые показатели</h3><p>Сценарий цены не изменяет исторический расчёт.</p></div><label>Маржа, % <input name="margin" type="number" min="0" max="95" step="0.5" value="${e(preferences.targetMargin)}" required></label><label>ROI, % <input name="roi" type="number" min="0" max="1000" step="1" value="${e(preferences.targetRoi)}" required></label><label>Плановый ДРР, % <input name="drr" type="number" min="0" max="90" step="0.5" value="${e(preferences.plannedDrr)}" required></label><fieldset><legend>Цену рассчитать до</legend><label><input type="radio" name="goal" value="margin" ${preferences.goal==='margin'?'checked':''}> Маржи</label><label><input type="radio" name="goal" value="roi" ${preferences.goal==='roi'?'checked':''}> ROI</label></fieldset><button type="submit" class="primary" ${state.busy?'disabled':''}>Применить цель</button></form><p id="econ-error" class="field-error" role="alert" ${state.error?'':'hidden'}>${e(state.error)}</p></section>${report?`<div class="econ-summary"><div><span>Модельный недобор до ${report.goal==='margin'?'маржи':'ROI'}</span><strong>${money(report.modeled_shortfall)}</strong><small>По рассчитанным доставленным маршрутам</small></div><div><span>SKU ниже выбранной цели</span><strong>${report.products.filter(p=>p.below_goal).length}</strong><small>Из ${report.products.length} с маршрутами</small></div><div><span>Неполные SKU</span><strong>${report.incomplete_sku_count}</strong><small>Нет маршрутов или часть без расчёта</small></div><div><span>Период наблюдения</span><strong>${periodText(report.period)}</strong><small>Завершённые недели, доставленные заказы</small></div></div>${state.mode==='products'?renderProducts(report):renderRoutes(report)}<details class="panel econ-method"><summary>Как рассчитаны показатели</summary><p>Недобор — положительная разница между целевой и модельной прибылью на единицу, умноженная на доставленное количество каждого известного маршрута. Это не фактический убыток по выкупам или выплатам Ozon. Текущая неделя не входит в маршрутное наблюдение.</p><p>Цена до цели рассчитана при неизменной логистике, комиссии, налоговом режиме и плановом ДРР. Изменение тарифа или спроса при новой цене не моделируется. Неполные маршруты блокируют единую цену по всем маршрутам.</p></details>`:'<section class="panel econ-loading">'+(state.busy?'Рассчитываем экономику…':state.error?'Исправьте параметры или пересчитайте план.':'Загрузить расчёт экономики.')+'</section>'}</div>`;
  const sc=currentRoot.querySelector('.econ-table-scroll');if(sc)sc.scrollLeft=oldScroll;
  bind();
}
function bind(){
  const c=currentRoot,form=c.querySelector('#econ-target-form');
  form.onsubmit=event=>{event.preventDefault();preferences={...preferences,targetMargin:form.elements.margin.value,targetRoi:form.elements.roi.value,plannedDrr:form.elements.drr.value,goal:form.elements.goal.value};try{validated();}catch(error){state={...state,error:error.message};draw();return;}persist();state={...state,filter:'all',limit:12,openGroup:null};load();};
  c.querySelectorAll('[data-econ-filter]').forEach(b=>b.onclick=()=>{state={...state,filter:b.dataset.econFilter,limit:12};draw();c.querySelectorAll('[data-econ-filter]').find(x=>x.dataset.econFilter===b.dataset.econFilter)?.focus({preventScroll:true});});
  const search=c.querySelector('#econ-search');if(search)search.oninput=()=>{const q=search.value;state={...state,search:q,limit:12};draw();const next=c.querySelector('#econ-search');next?.focus({preventScroll:true});next?.setSelectionRange(q.length,q.length);};
  c.querySelectorAll('[data-econ-mode]').forEach(b=>b.onclick=()=>{state={...state,mode:b.dataset.econMode,limit:12};draw();c.querySelectorAll('[data-econ-mode]').find(x=>x.dataset.econMode===b.dataset.econMode)?.focus({preventScroll:true});});
  c.querySelector('[data-econ-more]')?.addEventListener('click',()=>{state={...state,limit:state.limit+12};draw();});
  c.querySelectorAll('[data-econ-sku]').forEach(b=>b.onclick=()=>{state={...state,openSku:state.openSku===b.dataset.econSku?null:b.dataset.econSku,openGroup:null};draw();c.querySelectorAll('[data-econ-sku]').find(x=>x.dataset.econSku===b.dataset.econSku)?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-group-mode]').forEach(b=>b.onclick=()=>{state.groupMode[b.dataset.sku]=b.dataset.econGroupMode;state.openGroup=null;draw();c.querySelectorAll('[data-econ-group-mode]').find(x=>x.dataset.sku===b.dataset.sku&&x.dataset.econGroupMode===b.dataset.econGroupMode)?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-group]').forEach(b=>b.onclick=()=>{state.openGroup=state.openGroup===b.dataset.econGroup?null:b.dataset.econGroup;draw();c.querySelectorAll('[data-econ-group]').find(x=>x.dataset.econGroup===b.dataset.econGroup)?.focus({preventScroll:true});});
  c.querySelectorAll('[data-econ-drr]').forEach(input=>input.onchange=()=>{const value=input.value.replace(',','.'),number=Number(value);if(!value.trim()||!Number.isFinite(number)||number<0||number>90){input.setAttribute('aria-invalid','true');const error=c.querySelector('#'+input.getAttribute('aria-describedby'));if(error){error.hidden=false;error.textContent='Введите ДРР от 0 до 90 %.';}input.focus();return;}preferences.overrides[input.dataset.econDrr]=value;persist();load();});
}
function render(rootElement,snapshot,apiFetch,{stale=false}={}){
  currentRoot=rootElement;currentSnapshot=snapshot;currentFetch=apiFetch;state.stale=stale;
  const key=requestKey(snapshot);
  if(state.key!==key)load();else draw();
}
S.EconomicsWorkspace={render,productsForView,productRows,validateTargets:validated};
})(globalThis);
