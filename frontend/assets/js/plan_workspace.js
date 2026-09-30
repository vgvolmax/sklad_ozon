(function(root){'use strict';
const S=root.SkladOzon, P=S.PlanWorkspace={}, esc=value=>S.escapeHtml(value);
const known=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
P.rowKey=row=>`${row.sku}|||${row.destination_cluster_id}`;
P.stats=function(rows){
  const lines=rows.map(row=>row.working),decided=lines.filter(line=>known(line?.working_qty));
  return {qty:decided.reduce((sum,line)=>sum+Number(line.working_qty),0),unknown:lines.length-decided.length,
    volume:decided.every(line=>known(line.total_volume_l))?decided.reduce((sum,line)=>sum+Number(line.total_volume_l),0):null,
    attention:lines.filter(line=>!line||line.status!=='READY').length,
    ready:lines.filter(line=>line?.status==='READY').length,manual:lines.filter(line=>line?.is_overridden).length,
    positive:lines.filter(line=>known(line?.working_qty)&&Number(line.working_qty)>0).length,rows:rows.length};
};
P.filterRows=(rows,filter)=>rows.filter(row=>filter==='attention'?(!row.working||row.working.status!=='READY'):
  filter==='overridden'?Boolean(row.working?.is_overridden):filter==='positive'?known(row.working?.working_qty)&&Number(row.working.working_qty)>0:true);
P.buildModel=function(snapshot,workingPlan,view={}){
  const mode=view.perspective==='cluster'?'cluster':'product',cluster=mode==='cluster';
  const all=(cluster?S.buildClusterPlanItems(snapshot,workingPlan):S.buildArticlePlanItems(snapshot,workingPlan)).map(item=>{
    const rows=cluster?item.productRows:item.clusterRows;return {...item,id:String(cluster?item.clusterId:item.sku),rows,stats:P.stats(rows)};
  });
  const selectedId=cluster?view.selectedClusterId:view.selectedSku,selected=all.find(item=>item.id===selectedId)||all[0]||null;
  const query=cluster?view.clusterQuery:view.articleQuery,matched=cluster?S.filterClusterPlanItems(all,query||''):S.filterArticlePlanItems(all,query||'');
  const visible=matched.filter(item=>view.selectorFilter==='attention'?item.stats.attention>0:view.selectorFilter==='manual'?item.stats.manual>0:true);
  return {mode,all,visible,selected,rows:selected?.rows||[]};
};
P.selectContext=function(state,id){
  const model=P.buildModel(state.snapshot,state.workingPlan.plan,state.planView),item=model.all.find(item=>item.id===id);
  if(!item)return state;const cluster=model.mode==='cluster',view={...state.planView,[cluster?'selectedClusterId':'selectedSku']:id,expandedWorkingKey:null};
  if(!model.visible.some(item=>item.id===id)){view[cluster?'clusterQuery':'articleQuery']='';view.selectorFilter='all';}
  return {...state,planView:view,workingPlan:{...state.workingPlan,statusFilter:'all'}};
};
P.nextAttention=function(model){const index=model.all.findIndex(item=>item.id===model.selected?.id);for(let offset=1;offset<=model.all.length;offset++){const item=model.all[(index+offset)%model.all.length];if(item.stats.attention)return item.id;}return null;};
P.cardMarkup=function(item,selectedId,mode,index,picker=false){
  const selected=item.id===selectedId,cluster=mode==='cluster',s=item.stats,label=cluster?item.id:item.article||'Нет артикула';
  return `<button type="button" class="plan-context-card" id="${picker?'plan-picker-card':'plan-context-card'}-${index}" data-plan-entity-id="${esc(item.id)}" aria-pressed="${selected}" ${picker?'':`tabindex="${selected?'0':'-1'}"`}>
    <span class="plan-card-title">${esc(label)}${selected?'<span aria-hidden="true">✓</span>':''}</span>
    ${cluster?'':`<span class="plan-card-name" title="${esc(item.name||'Без названия')}">${esc(item.name||'Без названия')}</span>`}
    <span class="plan-card-quantity">${s.unknown?'Принято':'К поставке'} <strong>${S.presentNumber(s.qty)} шт.</strong><small> · ${s.rows} ${cluster?'SKU':'кластеров'}</small></span>
    <span class="plan-card-status ${s.attention?'warning':'success'}">${s.attention?`${s.attention} требуют внимания`:'Все решения приняты'}</span>
    ${!cluster&&item.duplicateArticle?`<small class="plan-card-sku">SKU ${esc(item.sku)} · общий артикул</small>`:''}
  </button>`;
};
P.selectorMarkup=function(model,view){
  const cluster=model.mode==='cluster',selectedId=model.selected?.id,cards=model.visible.slice(0,120);
  const selectedVisible=model.visible.find(item=>item.id===selectedId);if(selectedVisible&&!cards.includes(selectedVisible))cards.push(selectedVisible);
  return `<section class="panel plan-selector-panel" aria-label="Выбор ${cluster?'кластера':'товара'}">
    <div class="plan-selector-tools"><div class="plan-perspective" role="group" aria-label="Смотреть план"><button type="button" data-perspective="product" aria-pressed="${!cluster}">По товарам</button><button type="button" data-perspective="cluster" aria-pressed="${cluster}">По кластерам</button></div>
    <div id="${cluster?'cluster-search':'article-search'}" class="plan-context-search"></div>
    <div class="plan-context-filters" role="group" aria-label="Фильтр карточек">${[['all','Все'],['attention','Требуют внимания'],['manual','Вручную']].map(([key,label])=>`<button type="button" id="plan-context-filter-${key}" data-context-filter="${key}" aria-pressed="${(view.selectorFilter||'all')===key}">${label}${key==='all'?'':` <small>${model.all.filter(item=>key==='attention'?item.stats.attention:item.stats.manual).length}</small>`}</button>`).join('')}</div>
    <button type="button" id="plan-open-picker">Все ${cluster?'кластеры':'товары'}</button></div>
    <div class="plan-strip-caption"><span>${cluster?'Кластеры назначения':'Товары'} · найдено ${model.visible.length} из ${model.all.length}${cards.length<model.visible.length?' · остальные доступны в полном списке':''}</span><div><button type="button" id="plan-strip-prev" aria-label="Предыдущие карточки">←</button><button type="button" id="plan-strip-next" aria-label="Следующие карточки">→</button></div></div>
    <div class="plan-context-strip" id="plan-context-strip" aria-label="Карточки ${cluster?'кластеров':'товаров'}">${cards.map((item,index)=>P.cardMarkup(item,selectedId,model.mode,index)).join('')||'<p class="plan-strip-empty">Ничего не найдено. Измените поиск или фильтр. Открытый контекст сохранён.</p>'}</div>
  </section>`;
};
P.bindSelector=function(container,model,view,callbacks){
  const cluster=model.mode==='cluster',searchId=cluster?'cluster-search':'article-search',query=cluster?view.clusterQuery:view.articleQuery;
  S.SearchField.render(container.querySelector('#'+searchId),{value:query||'',label:cluster?'Найти кластер':'Найти товар',placeholder:cluster?'Название кластера':'Артикул, название или SKU',onChange:callbacks.search,onClear:()=>callbacks.search('')});
  container.querySelectorAll('[data-perspective]').forEach(button=>button.onclick=()=>callbacks.mode(button.dataset.perspective));
  container.querySelectorAll('[data-context-filter]').forEach(button=>button.onclick=()=>callbacks.filter(button.dataset.contextFilter));
  container.querySelectorAll('[data-plan-entity-id]').forEach(button=>button.onclick=()=>callbacks.select(button.dataset.planEntityId));
  const strip=container.querySelector('#plan-context-strip'),previous=container.querySelector('#plan-strip-prev'),next=container.querySelector('#plan-strip-next');
  const update=()=>{previous.disabled=strip.scrollLeft<=2;next.disabled=strip.scrollLeft+strip.clientWidth>=strip.scrollWidth-2;};
  previous.onclick=()=>strip.scrollBy({left:-Math.max(220,strip.clientWidth*.7),behavior:'auto'});next.onclick=()=>strip.scrollBy({left:Math.max(220,strip.clientWidth*.7),behavior:'auto'});
  strip.addEventListener('scroll',update,{passive:true});root.requestAnimationFrame?.(update);
  const cards=[...strip.querySelectorAll('button')];if(cards.length&&!cards.some(card=>card.tabIndex===0))cards[0].tabIndex=0;
  strip.addEventListener('keydown',event=>{const index=cards.indexOf(event.target);if(index<0||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const nextIndex=event.key==='Home'?0:event.key==='End'?cards.length-1:Math.max(0,Math.min(cards.length-1,index+(event.key==='ArrowRight'?1:-1)));cards.forEach((card,i)=>card.tabIndex=i===nextIndex?0:-1);cards[nextIndex].focus({preventScroll:true});cards[nextIndex].scrollIntoView({block:'nearest',inline:'nearest'});});
  container.querySelector('#plan-open-picker').onclick=()=>P.openPicker(model,callbacks.select);
};
P.openPicker=function(model,onSelect){
  const cluster=model.mode==='cluster',origin=document.activeElement;
  const dialog=S.AppDialog.open({title:`Все ${cluster?'кластеры':'товары'}`,className:'plan-context-picker',body:'<div id="plan-picker-search"></div><p id="plan-picker-count" class="muted"></p><div id="plan-picker-grid" class="plan-picker-grid"></div><div id="plan-picker-pages" class="pagination"></div>'});
  let query='',page=1;const draw=()=>{const matching=cluster?S.filterClusterPlanItems(model.all,query):S.filterArticlePlanItems(model.all,query),size=100,pages=Math.max(1,Math.ceil(matching.length/size));page=Math.max(1,Math.min(page,pages));
    dialog.querySelector('#plan-picker-count').textContent=`Найдено ${matching.length} из ${model.all.length}. Выбор открывает контекст и не меняет состав отгрузки.`;
    dialog.querySelector('#plan-picker-grid').innerHTML=matching.slice((page-1)*size,page*size).map((item,index)=>P.cardMarkup(item,model.selected?.id,model.mode,index,true)).join('')||'<p>Ничего не найдено. Очистите поиск или измените запрос.</p>';
    dialog.querySelector('#plan-picker-pages').innerHTML=pages>1?`<button type="button" data-picker-page="${page-1}" ${page===1?'disabled':''}>Назад</button><span>${page} из ${pages}</span><button type="button" data-picker-page="${page+1}" ${page===pages?'disabled':''}>Вперёд</button>`:'';
    dialog.querySelectorAll('[data-plan-entity-id]').forEach(button=>button.onclick=()=>{dialog.close();onSelect(button.dataset.planEntityId);});dialog.querySelectorAll('[data-picker-page]').forEach(button=>button.onclick=()=>{page=Number(button.dataset.pickerPage);draw();dialog.querySelector('#plan-picker-grid button')?.focus();});
  };
  const drawSearch=()=>{S.SearchField.render(dialog.querySelector('#plan-picker-search'),{value:query,label:cluster?'Найти кластер':'Найти товар',onChange:value=>{query=value;page=1;draw();const field=dialog.querySelector('#plan-picker-search input');const active=document.activeElement===field,selection=field.selectionStart;drawSearch();if(active){const updated=dialog.querySelector('#plan-picker-search input');updated.focus();updated.setSelectionRange(selection,selection);}},onClear:()=>{query='';page=1;draw();drawSearch();dialog.querySelector('#plan-picker-search input').focus();}});};
  drawSearch();draw();dialog.querySelector('#plan-picker-search input').focus();dialog.addEventListener('close',()=>{if(origin?.isConnected)origin.focus();},{once:true});
};
P.shortStatus=function(row){const line=row.working;if(!line)return ['warning','План недоступен'];if(line.status==='BLOCKED')return ['danger','Блокирует отгрузку'];if(line.working_qty==null)return ['warning','Нет решения'];if(line.status!=='READY')return ['warning','Требует проверки'];return line.working_qty===0?['neutral','Не поставлять']:['success','К поставке'];};
P.capture=function(container){
  if(!container)return null;const table=container.querySelector('.plan-compact-scroll'),strip=container.querySelector('#plan-context-strip'),active=document.activeElement,inPlan=container.contains(active),row=inPlan?active.closest('[data-working-row]'):null;
  const selector=row?(active.matches('[data-working-input]')?'[data-working-input]':active.matches('[data-working-step]')?`[data-working-step="${active.dataset.workingStep}"]`:['data-working-reset','data-working-source','data-working-line-zero','data-plan-expand','data-plan-close-row'].find(attr=>active.hasAttribute(attr))):null;
  return {tableTop:table?.scrollTop||0,tableLeft:table?.scrollLeft||0,stripLeft:strip?.scrollLeft||0,focusId:inPlan?active.id:null,workingKey:row?.dataset.workingRow,workingSelector:selector?.startsWith('data-')?`[${selector}]`:selector,selectionStart:active?.selectionStart,selectionEnd:active?.selectionEnd};
};
P.restore=function(container,saved){
  if(!container||!saved)return;const table=container.querySelector('.plan-compact-scroll'),strip=container.querySelector('#plan-context-strip');if(table){table.scrollTop=saved.tableTop;table.scrollLeft=saved.tableLeft;}if(strip)strip.scrollLeft=saved.stripLeft;
  let control;
  if(saved.workingKey){const row=[...container.querySelectorAll('[data-working-row]')].find(row=>row.dataset.workingRow===saved.workingKey);control=row?.querySelector(saved.workingSelector||'[data-plan-expand]');if(!control||control.disabled)control=row?.querySelector('[data-plan-expand]');if(!control)control=container.querySelector('#plan-row-filter-all')||container.querySelector('#plan-tab-products');}
  else if(saved.focusId)control=document.getElementById(saved.focusId);
  if(control&&container.contains(control)&&!control.disabled){control.focus({preventScroll:true});if(saved.selectionStart!=null&&control.matches('[data-working-input]'))control.setSelectionRange(saved.selectionStart,saved.selectionEnd);}
};
})(globalThis);
