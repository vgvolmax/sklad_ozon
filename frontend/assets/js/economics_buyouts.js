(function(root){'use strict';
const S=root.SkladOzon=root.SkladOzon||{},e=S.escapeHtml;
const money=value=>S.EconomicsWorkspace.formatMoney(value);
let container,snapshot,apiFetch,options,active=false,analysisId=null,financeId=null,report=null;
let dates=null,search='',filter='all',limit=12,busy=false,exporting=false,error='',periodError='',progress=null;
let run=0,controller=null,searchTimer=null,reportSelection=null,pendingFinanceId=null,reportError=false;
const selectionKey=()=>JSON.stringify([search,filter]);
function deactivate(){active=false;run++;controller?.abort();root.clearTimeout(searchTimer);busy=exporting=false;}
function body(){return {analysis_snapshot_id:snapshot.snapshot_id,finance_snapshot_id:financeId,search,filter};}
function defaultDates(asOf){const day=String(asOf||new Date().toISOString().slice(0,10));const [y,m]=day.split('-').map(Number);const last=new Date(Date.UTC(y,m-1,0));return {from:`${last.getUTCFullYear()}-${String(last.getUTCMonth()+1).padStart(2,'0')}-01`,to:last.toISOString().slice(0,10)};}
function periodText(period){return `${S.presentIsoDate(period.from)} — ${S.presentIsoDate(period.to)}`;}
function draw(){
  if(!active||!container)return;
  const focused=root.document.activeElement,focusId=container.contains(focused)?focused.id:null,selection=focused?.selectionStart;
  const oldScroll=container.querySelector('.buyout-table-scroll')?.scrollLeft||0;
  const total=report?.totals,selected=report?.selected_totals,selectionStale=reportSelection!==selectionKey();
  container.innerHTML=`<div class="econ-page buyout-page" aria-busy="${busy}">${options.selector}
    <div class="workspace-intro"><p class="eyebrow">ЭКОНОМИКА · ВЫКУПЛЕННЫЕ ТОВАРЫ</p><h2>Прибыль за период</h2><p>Выкупы и возвраты по дате начисления Ozon. Себестоимость — из вашей текущей загрузки.</p></div>
    ${options.stale?'<div class="notice notice-warning" role="status">Исходные данные изменились. Загрузите актуальную себестоимость и пересчитайте план.</div>':''}
    <section class="panel econ-period-controls"><form id="buyout-period" novalidate><div><h3>Период начислений</h3><p>Даты включительно · до 366 дней</p></div>
      <label>С <input id="buyout-from" name="from" type="date" min="2022-01-01" value="${e(dates.from)}" required aria-describedby="buyout-period-error" ${periodError?'aria-invalid="true"':''} ${busy||exporting?'disabled':''}></label>
      <label>По <input id="buyout-to" name="to" type="date" min="2022-01-01" value="${e(dates.to)}" required aria-describedby="buyout-period-error" ${periodError?'aria-invalid="true"':''} ${busy||exporting?'disabled':''}></label>
      <button id="buyout-load" type="submit" class="primary" ${busy||exporting?'disabled':''}>Загрузить начисления</button>
      ${busy?'<button id="buyout-cancel" type="button">Отменить</button>':''}</form>
      <p id="buyout-period-error" class="field-error" role="alert" ${periodError?'':'hidden'}>${e(periodError)}</p>
      <p id="buyout-progress" role="status">${busy?(progress?`Загружаем начисления: ${progress.current} из ${progress.total} дней`:'Загружаем расчёт…'):report?`Загружен период: ${periodText(report.period)}`:'Загрузите начисления Ozon за нужный период. Доступ к Ozon должен быть разблокирован на экране Данные.'}</p>
      ${busy&&progress?`<progress value="${Number(progress.current)}" max="${Number(progress.total)}" aria-label="Загрузка начислений"></progress>`:''}
      <p id="buyout-error" class="field-error" role="alert" ${error?'':'hidden'}>${e(error)}</p>${reportError&&(pendingFinanceId||financeId)?`<button id="buyout-retry" type="button" ${busy?'disabled':''}>Повторить расчёт выборки</button>`:''}</section>
    ${report?`<section class="panel buyout-summary" aria-label="Итог всего магазина"><h3>Весь магазин · ${periodText(report.period)}</h3>
      ${total.partial?`<div class="notice notice-warning" role="status">Частичный расчёт: прибыль рассчитана для ${total.covered_sku_count} из ${total.sku_count} SKU. Проверьте товары без себестоимости или количества.</div>`:''}
      <div class="buyout-totals"><div><span>Прибыль по товарам</span><strong>${money(total.profit_before_common)}</strong><small>После расходов Ozon по SKU и себестоимости</small></div>
      <div><span>Общие расходы</span><strong>${money(total.common_expenses)}</strong><small>Расходы без SKU за этот же период</small></div>
      <div class="buyout-final"><span>${total.partial?'Известная часть прибыли':'Прибыль после известных расходов'}</span><strong data-buyout-final>${money(total.profit_after_known_expenses)}</strong><small>${total.partial?'Неполный итог магазина':'Все загруженные выкупы и возвраты'}</small></div></div>
      <p>Реклама за период: <strong data-buyout-ads>${money(total.advertising_spend)}</strong> · уже учтена в расходах. Рекламные файлы модели по заказам здесь повторно не вычитаются.</p></section>
      <section class="panel buyout-products"><div class="econ-main-head"><div><h3>Выкупленные товары</h3><p>${report.products.length} из ${report.catalog_product_count} SKU · прибыль в фильтре: <strong data-buyout-selected>${money(selected.profit)}</strong>${selected.partial?' · частичный расчёт':''}</p></div>
      <button id="buyout-export" type="button" ${busy||exporting||selectionStale||(!report.products.length&&report.catalog_product_count)?'disabled':''}>Скачать отчёт XLSX</button></div>
      <div class="buyout-filters"><label>Поиск <input id="buyout-search" type="search" maxlength="200" value="${e(search)}" placeholder="Артикул, SKU или товар" ${progress||exporting?'disabled':''}></label><button id="buyout-clear" type="button" ${!search||progress||exporting?'disabled':''}>Очистить поиск</button>
      <div class="econ-segmented" role="group" aria-label="Фильтр выкупов">${[['all','Все'],['loss','С убытком'],['incomplete','Неполные']].map(([key,label])=>`<button type="button" data-buyout-filter="${key}" aria-pressed="${filter===key}" ${progress||exporting?'disabled':''}>${label}</button>`).join('')}</div></div>
      ${selectionStale?'<p role="status">Показана предыдущая выборка.</p>':''}
      <p id="buyout-export-status" role="status">${exporting?'Готовим отчёт…':'Excel: товары в фильтре; итог и расходы — за весь магазин.'}</p>
      ${report.products.length?`<div class="buyout-table-scroll" tabindex="0" role="region" aria-label="Выкупы по товарам"><table class="buyout-table"><thead><tr><th>Товар / SKU</th><th>Выкуплено</th><th>Возвращено</th><th>Выручка продавца</th><th>Расходы Ozon по SKU</th><th>Себестоимость / шт.</th><th>Себестоимость всего</th><th>Прибыль по товару</th></tr></thead><tbody>${report.products.slice(0,limit).map(p=>`<tr data-buyout-row="${e(p.sku)}"><td><strong>${e(p.article||'Нет артикула')} · ${e(p.name)}</strong><div class="econ-sku-meta"><small>SKU ${e(p.sku)}</small><button type="button" class="econ-copy" data-econ-copy="${e(p.sku)}" aria-label="Копировать SKU ${e(p.sku)}"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="5" y="5" width="8" height="8" rx="1"/><path d="M3 10H2V2h8v1"/></svg></button></div>${p.partial?`<small class="field-error">${!p.quantity_known?'Нет точного количества в начислении':'Нет себестоимости в текущей загрузке'}</small>`:''}</td><td>${p.purchased_qty}${!p.quantity_known?'<small>Известная часть</small>':''}</td><td>${p.returned_qty}</td><td>${money(p.revenue)}</td><td>${money(p.known_expenses)}</td><td>${money(p.cost)}</td><td>${money(p.cost_total)}</td><td><strong>${money(p.profit)}</strong></td></tr>`).join('')}</tbody></table></div>`:`<p role="status">${report.catalog_product_count?'В этом фильтре нет товаров.':'За период нет начислений по товарам. Общие расходы показаны выше.'}</p>`}
      ${report.products.length>limit?'<button id="buyout-more" type="button">Показать ещё 12</button>':''}</section>
      <details class="panel buyout-expenses"><summary>Расходы магазина за период</summary><p>Расходы по SKU уже включены в прибыль товара. Из общего итога вычитается только столбец «Общие». Отрицательное значение — возврат расхода или корректировка в вашу пользу.</p>
      <div class="buyout-table-scroll" tabindex="0" role="region" aria-label="Расходы магазина"><table><thead><tr><th>Категория</th><th>Всего</th><th>Уже в товарах</th><th>Общие</th></tr></thead><tbody>${report.expenses.map(item=>`<tr><td>${e(item.label)}</td><td>${money(item.amount)}</td><td>${money(item.product_amount)}</td><td>${money(item.common_amount)}</td></tr>`).join('')||'<tr><td colspan="4">Нет известных расходов</td></tr>'}</tbody></table></div></details>
      <details class="panel econ-method"><summary>Как рассчитана прибыль</summary><p>Начисления за выкупленные товары минус себестоимость выкупов с учётом возвратов, затем минус общие расходы за выбранные даты. Комиссия, логистика и реклама, уже включённые в начисления по SKU, учитываются один раз. Неизвестные категории сохраняются как другие начисления и корректировки.</p><p>Это управленческий расчёт по известным расходам. Налоги и расходы вне Ozon не учтены. Месяц с начислениями может отличаться от месяца заказа.</p></details>`:''}</div>`;
  options.bindSelector();
  container.querySelector('#buyout-period').onsubmit=event=>{event.preventDefault();dates={from:event.target.elements.from.value,to:event.target.elements.to.value};sync();};
  for(const key of ['from','to'])container.querySelector('#buyout-'+key).oninput=event=>{dates[key]=event.target.value;};
  container.querySelector('#buyout-cancel')?.addEventListener('click',()=>{run++;controller?.abort();busy=false;progress=null;error='Загрузка отменена. Можно повторить.';draw();container.querySelector('#buyout-load')?.focus({preventScroll:true});});
  container.querySelector('#buyout-export')?.addEventListener('click',download);
  container.querySelector('#buyout-retry')?.addEventListener('click',refresh);
  container.querySelector('#buyout-more')?.addEventListener('click',()=>{limit+=12;draw();});
  container.querySelectorAll('[data-econ-copy]').forEach(button=>button.onclick=()=>S.EconomicsWorkspace.copySku(button));
  container.querySelectorAll('[data-buyout-filter]').forEach(button=>button.onclick=()=>{filter=button.dataset.buyoutFilter;limit=12;refresh();});
  container.querySelector('#buyout-clear')?.addEventListener('click',()=>{search='';limit=12;refresh();container.querySelector('#buyout-search')?.focus({preventScroll:true});});
  const field=container.querySelector('#buyout-search');if(field){let composing=false;const apply=()=>{search=field.value;limit=12;run++;controller?.abort();root.clearTimeout(searchTimer);busy=true;draw();searchTimer=root.setTimeout(refresh,300);};field.oncompositionstart=()=>{composing=true;run++;controller?.abort();root.clearTimeout(searchTimer);};field.oncompositionend=()=>{composing=false;apply();};field.oninput=event=>{if(!composing&&!event.isComposing)apply();};field.onkeydown=event=>{if(event.key==='Enter'&&!composing&&!event.isComposing){event.preventDefault();search=field.value;limit=12;refresh();}};}
  const scroller=container.querySelector('.buyout-table-scroll');if(scroller)scroller.scrollLeft=oldScroll;
  const next=focusId?container.querySelector('#'+focusId):null;next?.focus({preventScroll:true});if(next?.type==='search'&&selection!=null)next.setSelectionRange(selection,selection);
}
async function refresh(){
  root.clearTimeout(searchTimer);controller?.abort();controller=new AbortController();const abort=controller,request=++run,selected={...body(),finance_snapshot_id:pendingFinanceId||financeId};busy=true;progress=null;error='';reportError=false;draw();
  const timeout=root.setTimeout(()=>abort.abort(),60000);
  try{const response=await apiFetch('/api/economics/buyouts/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected),signal:controller.signal});const data=await response.json();if(request!==run||!active)return;if(!response.ok){if(response.status===409||response.status===423){report=null;financeId=pendingFinanceId=null;}throw Error(data.error?.message||'Не удалось рассчитать прибыль.');}report=data.workspace;financeId=selected.finance_snapshot_id;if(pendingFinanceId===financeId)pendingFinanceId=null;reportSelection=JSON.stringify([selected.search,selected.filter]);
  }catch(exc){if(request===run&&active){reportError=true;error=exc.name==='AbortError'?'Расчёт прерван. Повторите загрузку.':exc.message;}}
  finally{root.clearTimeout(timeout);if(request===run&&active){busy=false;draw();}}
}
async function sync(){
  if(busy||exporting)return;periodError='';error='';reportError=false;
  const from=new Date(dates.from+'T00:00:00Z'),to=new Date(dates.to+'T00:00:00Z');
  if(!dates.from||!dates.to||!Number.isFinite(+from)||!Number.isFinite(+to)||dates.from<'2022-01-01'||from>to||(+to-+from)/86400000>=366){periodError='Выберите обе даты по порядку: до 366 дней начиная с 01.01.2022.';draw();container.querySelector('#buyout-from').focus({preventScroll:true});return;}
  controller?.abort();controller=new AbortController();const request=++run,abort=controller;busy=true;progress=null;draw();let result=null,timer=null;
  const touch=()=>{root.clearTimeout(timer);timer=root.setTimeout(()=>abort.abort(),90000);};touch();
  try{const response=await apiFetch('/api/economics/buyouts/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({period_from:dates.from,period_to:dates.to}),signal:abort.signal});
    if(!response.ok){const data=await response.json();if(request!==run)return;if(response.status===409||response.status===423){report=null;financeId=pendingFinanceId=null;}throw Error(data.error?.message||'Не удалось загрузить начисления.');}
    if(!response.body)throw Error('Не удалось получить ответ Ozon. Повторите загрузку.');
    const reader=response.body.getReader(),decoder=new TextDecoder(),parser=S.createNdjsonParser(item=>{if(request!==run||!active)return;touch();if(item.type==='progress'){progress=item;draw();}else if(item.type==='result')result=item.data;else if(item.type==='error'){if(['OZON_CREDENTIAL_CONTEXT_CHANGED','OZON_VAULT_LOCKED'].includes(item.error?.code)){report=null;financeId=pendingFinanceId=null;}throw Error(item.error?.message||'Не удалось загрузить начисления.');}});
    try{while(true){const {value,done}=await reader.read();if(request!==run||!active)return;parser.push(decoder.decode(value||new Uint8Array(),{stream:!done}),done);if(done)break;}}finally{await reader.cancel().catch(()=>{});}
    if(request!==run||!active)return;if(!result)throw Error('Загрузка не завершена. Повторите.');pendingFinanceId=result.finance_snapshot_id;progress=null;busy=false;await refresh();
  }catch(exc){if(request===run&&active)error=exc.name==='AbortError'?'Загрузка прервана. Повторите загрузку.':exc.message;}
  finally{root.clearTimeout(timer);if(request===run&&active){busy=false;progress=null;draw();}}
}
async function download(){
  if(busy||exporting||reportSelection!==selectionKey())return;const request=run,selected=body();exporting=true;error='';draw();
  try{const response=await apiFetch('/api/economics/buyouts/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected)});if(!response.ok){const data=await response.json();if(request!==run||!active)return;if(response.status===409||response.status===423){report=null;financeId=pendingFinanceId=null;}throw Error(data.error?.message||'Не удалось скачать отчёт.');}const blob=await response.blob();if(request!==run||!active)return;const url=root.URL.createObjectURL(blob),a=root.document.createElement('a');a.href=url;a.download='Выкупы.xlsx';root.document.body.append(a);a.click();root.setTimeout(()=>{a.remove();root.URL.revokeObjectURL(url);},1000);
  }catch(exc){if(request===run&&active)error=exc.message;}
  finally{if(request===run&&active){exporting=false;draw();}}
}
function render(element,analysis,fetch,settings){
  container=element;snapshot=analysis;apiFetch=fetch;options=settings;active=true;
  if(!dates)dates=defaultDates(analysis.analysis_as_of);
  // An outer render can signal navigation/account changes even with the same FILES analysis.
  // Supersede pending operations and hide all cached finance until revalidation finishes.
  analysisId=analysis.snapshot_id;run++;controller?.abort();root.clearTimeout(searchTimer);
  report=null;pendingFinanceId=null;busy=exporting=false;progress=null;
  if(financeId){refresh();return;}
  draw();
}
S.EconomicsBuyouts={render,deactivate};
})(globalThis);
