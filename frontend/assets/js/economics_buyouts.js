(function(root){'use strict';
const S=root.SkladOzon=root.SkladOzon||{},e=S.escapeHtml;
const money=value=>S.EconomicsWorkspace.formatMoney(value);
const roles={advertising:'Общая реклама · вычтена',additional_period_expense:'Общий расход · вычтен',already_in_unit_model:'Уже учтён в юнитке',unclassified:'Не классифицирован · не вычтен'};
let container,snapshot,apiFetch,options,active=false,analysisId=null,financeId=null,report=null;
let mode='orders',limit=12,busy=false,exporting=false,error='',progress=null,operation='';
let run=0,controller=null,scenarioKey=null,reportKey=null,pendingFinanceId=null,loadedPeriod=null;
let elapsedSeconds=0,expensesOpen=false,productsOpen=false;
function deactivate(){active=false;run++;controller?.abort();busy=exporting=false;operation='';}
function body(){return {...options.scenario,analysis_snapshot_id:snapshot.snapshot_id,mode,...(financeId?{finance_snapshot_id:financeId}:{})};}
const selectionKey=()=>JSON.stringify([scenarioKey,mode]);
function periodText(period){return period?`${S.presentIsoDate(period.from)} — ${S.presentIsoDate(period.to)}`:'Период не выбран';}
function progressDetail(){
  if(!busy||!progress)return '';
  const phase=progress.stage==='types'?'Ожидаем ответ Ozon: справочник начислений':progress.stage==='posting'?'Ожидаем ответ Ozon: уточняем количество товаров':progress.stage==='day'?'Ожидаем ответ Ozon: начисления за день':progress.stage==='complete'?'Начисления загружены':'Обрабатываем начисления';
  const day=progress.stage==='types'?'':` · ${S.presentIsoDate(progress.day)} · страница ${progress.page}`;
  return `${phase}${day} · обработано начислений: ${progress.processed||0}${elapsedSeconds?` · Прошло: ${elapsedSeconds} с`:''}`;
}
function draw(){
  if(!active||!container?.isConnected)return;
  const focused=root.document.activeElement,focusId=container.contains(focused)?focused.id:null;
  const externalTop=focused&&focused!==root.document.body&&!container.contains(focused)?focused.getBoundingClientRect().top:null;
  const previousHeight=container.offsetHeight||0,keepHeight=externalTop!=null&&previousHeight>0;
  if(container.style&&!keepHeight)container.style.minHeight='';
  const y=root.scrollY;
  const valid=reportKey===selectionKey(),total=report?.totals;
  const dates={from:options.scenario.period_from,to:options.scenario.period_to};
  const displayedMode=report?.mode||mode,displayedDates=report?.period||dates;
  container.innerHTML=`<div class="econ-profit-head"><div><h3>Прибыль за период · весь магазин</h3><p>${periodText(displayedDates)} · ${report&&!valid?'модель показанного расчёта':'модель по текущей юнитке'}</p></div>
    <div class="econ-segmented" role="group" aria-label="Количество для итога периода">${[['orders','По заказам'],['buyouts','По выкупам']].map(([key,label])=>`<button type="button" data-econ-calculation="${key}" aria-pressed="${mode===key}" ${exporting?'disabled':''}>${label}</button>`).join('')}</div></div>
    <p>${mode==='orders'?'Заказы в работе и доставленные, без отменённых · по дате принятия':'Выкупы минус возвраты · по дате начисления Ozon'}. Карточки товаров используют одну юнитку в обоих режимах.</p>
    <div class="econ-profit-actions"><button id="buyout-load" type="button" ${busy||exporting||!options.ready?'disabled':''}>Загрузить расходы и выкупы</button>${busy?'<button id="buyout-cancel" type="button">Отменить</button>':''}<button id="buyout-export" type="button" ${busy||exporting||!total||!valid||!options.ready||options.blocked?.()?'disabled':''}>Скачать итог XLSX</button></div>
    <p id="buyout-progress" role="status">${busy?(operation==='sync'?`Загружаем начисления${progress?`: ${progress.current} из ${progress.total} дней`:''}`:`Считаем итог…${report&&!valid?' Показана предыдущая версия расчёта.':''}`):loadedPeriod?`Начисления загружены: ${periodText(loadedPeriod)}${!valid&&report?' · показан предыдущий расчёт':''}`:'Расходы и выкупы доступны после загрузки начислений. Разблокируйте Ozon на экране Данные.'}</p>
    <p id="buyout-progress-detail" ${busy&&progress?'':'hidden'}>${e(progressDetail())}</p>
    ${busy&&progress?`<progress value="${Number(progress.current)}" max="${Number(progress.total)}" aria-label="Загрузка начислений"></progress>`:''}
    <p id="buyout-error" class="field-error" role="alert" ${error?'':'hidden'}>${e(error)}</p>${error?'<button id="buyout-retry" type="button">Повторить расчёт</button>':''}
    ${report?`<p class="notice ${valid?'':'notice-warning'}" role="status" ${valid?'':'data-econ-profit-stale'}>Показан ${valid?'актуальный':'предыдущий'} расчёт: ${displayedMode==='orders'?'По заказам':'По выкупам'} · ${periodText(displayedDates)}.</p>`:''}
    ${total?`${total.partial?`<p class="notice notice-warning" role="status">Частичный итог. База рассчитана для ${total.covered_sku_count} из ${total.sku_count} SKU · ${total.covered_qty} шт.${!report.quantity_complete?' Количество неполное.':''}${!report.expenses_complete?' Расходы не загружены.':''}${total.uncovered_skus.length?` Без полной юнитки: ${e(total.uncovered_skus.join(', '))}.`:''}${report.expenses.some(x=>x.role==='unclassified')?' Есть не классифицированные расходы.':''}</p>`:''}
      <dl><div><dt>Количество · ${displayedMode==='orders'?'заказы':'выкупы минус возвраты'}</dt><dd>${total.qty==null?'Не рассчитано':total.qty+' шт.'}</dd></div><div><dt>Прибыль до общих расходов</dt><dd ${valid?'data-econ-profit-before':''}>${money(total.profit_before_common)}</dd></div>
      <div><dt>Реклама за тот же период · весь магазин</dt><dd ${valid?'data-buyout-ads':''}>${money(total.advertising_total)}</dd></div><div><dt>Прочие общие расходы</dt><dd>${money(total.other_common_total)}</dd></div>
      <div class="econ-profit-final"><dt>${total.partial?'Известная часть прибыли после расходов':'Прибыль после известных расходов'}</dt><dd ${valid?'data-buyout-final':''}>${money(total.profit_after_common)}</dd></div><div><dt>Маржа по модельной выручке</dt><dd>${total.margin==null?'Не рассчитано':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(Number(total.margin)*100)+' %'}</dd></div></dl>
      <p>Источник расходов: финансовые начисления Ozon${report.loaded_at?` · загружено ${e(report.loaded_at)}`:''}. Рекламные XLSX для ДРР повторно не вычитаются.</p>
      <details class="buyout-products" ${productsOpen?'open':''}><summary>Вклад товаров · ${report.products.length} ${valid?'в текущем фильтре':'в предыдущем расчёте'}</summary><p>Прибыль выбранных SKU до общих расходов: <strong data-buyout-selected>${money(report.selected_profit_before_common)}</strong>. Итог выше и расходы относятся ко всему магазину.</p>
      <div class="buyout-table-scroll" tabindex="0" role="region" aria-label="Вклад товаров в прибыль"><table><thead><tr><th>Артикул / SKU</th><th>Прибыль до рекламы / шт.</th><th>Количество</th><th>Вклад в прибыль</th></tr></thead><tbody>${report.products.slice(0,limit).map(p=>`<tr data-buyout-row="${e(p.sku)}"><td>${e(p.article||p.sku)}<small>SKU ${e(p.sku)}</small>${p.partial?'<small>Нет полной базы или количества</small>':''}</td><td>${money(p.profit_per_unit_before_ads)}</td><td>${p.qty??'Неизвестно'}</td><td>${money(p.profit)}</td></tr>`).join('')||'<tr><td colspan="4">Нет товаров по выбранным условиям</td></tr>'}</tbody></table></div>${report.products.length>limit?'<button id="buyout-more" type="button">Показать ещё 12</button>':''}</details>
      <details class="buyout-expenses" ${expensesOpen?'open':''}><summary>Расходы магазина · расшифровка</summary><p>Комиссия, эквайринг и логистика уже входят в прибыль на штуку. Возврат расхода сохраняет отрицательный знак.</p><div class="buyout-table-scroll" tabindex="0" role="region" aria-label="Расходы магазина"><table><thead><tr><th>Категория</th><th>Сумма</th><th>Учёт</th></tr></thead><tbody>${report.expenses.map(x=>`<tr><td>${e(x.label)}</td><td>${money(x.amount)}</td><td>${roles[x.role]}</td></tr>`).join('')||`<tr><td colspan="3">${report.expenses_complete?'Известные расходы равны нулю':'Расходы не загружены'}</td></tr>`}</tbody></table></div></details>
      <details class="econ-method"><summary>Как рассчитан общий итог</summary><p>Прибыль на штуку без рекламы из текущей юнитки × количество каждого SKU, затем минус вся реклама и прочие известные общие расходы за те же даты. Только количество меняется между заказами и выкупами. Маржа считается по модельной выручке, а не по выплатам Ozon. База уже включает известные комиссии, логистику и модельные налоги; повторно они не вычитаются. Не классифицированные услуги показаны отдельно и делают итог частичным.</p></details>`:''}`;
  container.querySelectorAll('[data-econ-calculation]').forEach(button=>button.onclick=()=>{
    if(exporting||mode===button.dataset.econCalculation)return;
    mode=button.dataset.econCalculation;
    if(operation==='sync'){draw();return;}
    if(!options.ready){draw();return;}
    refresh();
  });
  container.querySelector('#buyout-load').onclick=sync;
  container.querySelector('#buyout-export').onclick=download;
  container.querySelector('#buyout-retry')?.addEventListener('click',refresh);
  container.querySelector('#buyout-cancel')?.addEventListener('click',()=>{run++;controller?.abort();busy=false;operation='';progress=null;error='Загрузка отменена. Можно повторить.';draw();});
  container.querySelector('#buyout-more')?.addEventListener('click',()=>{limit+=12;draw();});
  container.querySelector('.buyout-expenses')?.addEventListener('toggle',event=>{expensesOpen=event.target.open;});
  container.querySelector('.buyout-products')?.addEventListener('toggle',event=>{productsOpen=event.target.open;});
  // Status/notice rows may disappear after a refresh. Keep the panel's space
  // while the user edits outside it, so cards below do not jump upward.
  if(keepHeight&&container.style)container.style.minHeight=Math.max(previousHeight,container.offsetHeight)+'px';
  const next=focusId?container.querySelector('#'+focusId):null;next?.focus({preventScroll:true});
  if(externalTop!=null&&focused.isConnected)root.scrollBy(0,focused.getBoundingClientRect().top-externalTop);else root.scrollTo(root.scrollX,y);
}
function invalidate(response){if(response.status===409||response.status===423){report=null;financeId=pendingFinanceId=null;loadedPeriod=null;}}
async function refresh(){
  if(!active||!options.ready)return;
  controller?.abort();controller=new AbortController();const abort=controller,request=++run;
  const selected={...body(),...(pendingFinanceId?{finance_snapshot_id:pendingFinanceId}:{})},key=selectionKey();
  busy=true;operation='refresh';progress=null;error='';draw();const timeout=root.setTimeout(()=>abort.abort(),60000);
  try{const response=await apiFetch('/api/economics/period/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected),signal:abort.signal});const data=await response.json();if(request!==run||!active)return;if(!response.ok){invalidate(response);throw Error(data.error?.message||'Не удалось рассчитать прибыль.');}report=data.workspace;reportKey=key;financeId=selected.finance_snapshot_id||null;if(pendingFinanceId===financeId)pendingFinanceId=null;
  }catch(exc){if(request===run&&active)error=exc.name==='AbortError'?'Расчёт прерван. Повторите.':exc.message;}
  finally{root.clearTimeout(timeout);if(request===run&&active){busy=false;operation='';draw();}}
}
async function sync(){
  if(busy||exporting||!options.ready)return;
  controller?.abort();controller=new AbortController();const request=++run,abort=controller;
  const dates={from:options.scenario.period_from,to:options.scenario.period_to};busy=true;operation='sync';error='';progress=null;elapsedSeconds=0;draw();let result=null,timer=null;
  const touch=()=>{root.clearTimeout(timer);timer=root.setTimeout(()=>abort.abort(),90000);};touch();
  try{const response=await apiFetch('/api/economics/buyouts/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({period_from:dates.from,period_to:dates.to}),signal:abort.signal});
    if(!response.ok){const data=await response.json();if(request!==run)return;invalidate(response);throw Error(data.error?.message||'Не удалось загрузить начисления.');}
    if(!response.body)throw Error('Не удалось получить ответ Ozon. Повторите.');
    const reader=response.body.getReader(),decoder=new TextDecoder(),parser=S.createNdjsonParser(item=>{if(request!==run||!active)return;touch();if(item.type==='progress'){progress=item;elapsedSeconds=Number(item.elapsed_seconds)||0;draw();}else if(item.type==='heartbeat'){elapsedSeconds=Number(item.elapsed_seconds)||0;const detail=container.querySelector('#buyout-progress-detail');if(detail)detail.textContent=progressDetail();}else if(item.type==='result')result=item.data;else if(item.type==='error'){if(['OZON_CREDENTIAL_CONTEXT_CHANGED','OZON_VAULT_LOCKED'].includes(item.error?.code)){report=null;financeId=pendingFinanceId=null;loadedPeriod=null;}throw Error(item.error?.message||'Не удалось загрузить начисления.');}});
    try{while(true){const {value,done}=await reader.read();if(request!==run||!active)return;parser.push(decoder.decode(value||new Uint8Array(),{stream:!done}),done);if(done)break;}}finally{await reader.cancel().catch(()=>{});}
    if(request!==run||!active)return;if(!result)throw Error('Загрузка не завершена. Повторите.');pendingFinanceId=result.finance_snapshot_id;loadedPeriod=dates;progress=null;busy=false;operation='';await refresh();
  }catch(exc){if(request===run&&active)error=exc.name==='AbortError'?'Загрузка прервана. Повторите.':exc.message;}
  finally{root.clearTimeout(timer);if(request===run&&active){busy=false;operation='';progress=null;draw();}}
}
async function download(){
  if(busy||exporting||reportKey!==selectionKey()||options.blocked?.())return;
  const selected=body(),key=selectionKey(),request=run;exporting=true;error='';draw();
  try{const response=await apiFetch('/api/economics/period/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selected)});if(!response.ok){const data=await response.json();if(request!==run||!active)return;invalidate(response);throw Error(data.error?.message||'Не удалось скачать отчёт.');}const blob=await response.blob();if(request!==run||!active||key!==selectionKey())return;const url=root.URL.createObjectURL(blob),a=root.document.createElement('a');a.href=url;a.download='Прибыль-периода.xlsx';root.document.body.append(a);a.click();root.setTimeout(()=>{a.remove();root.URL.revokeObjectURL(url);},1000);
  }catch(exc){if(request===run&&active)error=exc.message;}
  finally{if(request===run&&active){exporting=false;draw();}}
}
function render(element,analysis,fetch,settings){
  container=element;snapshot=analysis;apiFetch=fetch;options=settings;active=true;
  const key=JSON.stringify(settings.scenario),changed=key!==scenarioKey;
  if(analysisId!==analysis.snapshot_id){deactivate();active=true;analysisId=analysis.snapshot_id;financeId=pendingFinanceId=null;report=null;loadedPeriod=null;scenarioKey=null;error='';}
  if(changed||settings.revalidate){
    run++;controller?.abort();busy=exporting=false;operation='';progress=null;if(settings.revalidate)report=null;reportKey=null;scenarioKey=key;error='';
    if(loadedPeriod&&(settings.scenario.period_from<loadedPeriod.from||settings.scenario.period_to>loadedPeriod.to)){financeId=pendingFinanceId=null;loadedPeriod=null;}
    if(settings.ready){refresh();return;}
  }
  if(settings.ready&&reportKey!==selectionKey()&&!busy&&!error){refresh();return;}
  draw();
}
S.EconomicsBuyouts={render,deactivate};
})(globalThis);
