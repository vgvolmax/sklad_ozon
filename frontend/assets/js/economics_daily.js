(function(root){'use strict';
const S=root.SkladOzon=root.SkladOzon||{}, e=S.escapeHtml;
const number=v=>v==null||v===''||!Number.isFinite(Number(v))?null:Number(v);
const format=new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2});
const percent=v=>number(v)==null?'n/a':`${format.format(Number(v)*100)} %`;
const date=v=>String(v||'').split('-').reverse().join('.');
const LEFT=64, WIDTH=920;
let snapshotId=null, container=null, apiFetch=null;
let selectionKey='',selection={granularity:'day'},generation=0;
let refreshTimer=null;
const cache=new Map(), expanded=new Set();

function geometry(days, large=false){
  const lineTop=large?18:8, lineBottom=large?86:30;
  const buyerTop=large?116:42, buyerBottom=large?184:64;
  const barTop=large?218:78, barBottom=large?282:100;
  const step=WIDTH/Math.max(1,days.length);
  function line(field,top,bottom){
    const values=days.map(d=>number(d[field])).filter(v=>v!==null);
    const minimum=values.length?Math.min(...values):null, maximum=values.length?Math.max(...values):null;
    const points=[],segments=[];
    let segment='';
    days.forEach((d,index)=>{
      const x=LEFT+step*(index+.5), value=number(d[field]);
      const y=value===null?null:minimum===maximum?(top+bottom)/2:
        bottom-(value-minimum)/(maximum-minimum)*(bottom-top);
      points.push({x,y});
      if(y===null){if(segment)segments.push(segment);segment='';}
      else segment+=`${segment?' L':'M'}${x.toFixed(2)},${y.toFixed(2)}`;
    });
    if(segment)segments.push(segment);
    return {minimum,maximum,points,segments};
  }
  const spp=line('spp',lineTop,lineBottom), buyer=line('buyer_price_mean',buyerTop,buyerBottom);
  const maxOrders=Math.max(1,...days.map(d=>number(d.orders)||0));
  const bars=[];
  days.forEach((d,index)=>{
    const orders=number(d.orders);
    if(orders!==null)bars.push({x:LEFT+step*(index+.5),height:orders/maxOrders*(barBottom-barTop),width:Math.max(.5,step*.65)});
  });
  return {...spp,bars,lineTop,lineBottom,barTop,barBottom,maxOrders,height:large?310:110,
    buyerMinimum:buyer.minimum,buyerMaximum:buyer.maximum,buyerPoints:buyer.points,
    buyerSegments:buyer.segments,buyerTop,buyerBottom};
}

const money=v=>number(v)==null?'n/a':`${format.format(Number(v))} ₽`;
function chart(series, large){
  const days=series.days||[], g=geometry(days,large);
  function axis(min,max,top,bottom,formatter,label){
    if(min===null)return `<text x="4" y="${top+12}">${label} n/a</text>`;
    if(min===max)return `<text x="4" y="${(top+bottom)/2+4}">${e(formatter(min))}</text>`;
    return `<text x="4" y="${top+4}">${e(formatter(max))}</text><text x="4" y="${bottom+4}">${e(formatter(min))}</text>`;
  }
  function paths(segments,points,kind=''){
    return segments.map(path=>`<path class="econ-daily-line ${kind}" d="${path}"/>`).join('')+
      points.filter(p=>p.y!==null).map(p=>`<circle class="econ-daily-dot ${kind?'econ-daily-buyer-dot':''}" cx="${p.x}" cy="${p.y}" r="${large?2:1.5}"/>`).join('');
  }
  const dates=large&&days.length?`<text x="${LEFT}" y="306">${e(date(days[0].day))}</text><text x="984" y="306" text-anchor="end">${e(date(days.at(-1).to||days.at(-1).day))}</text>`:'';
  return `<svg class="econ-daily-svg" viewBox="0 0 1000 ${g.height}" role="img" aria-label="Средняя СПП, средняя цена покупателя и заказанное количество на общей шкале дат" preserveAspectRatio="none">${axis(g.minimum,g.maximum,g.lineTop,g.lineBottom,percent,'СПП')}${axis(g.buyerMinimum,g.buyerMaximum,g.buyerTop,g.buyerBottom,money,'Цена')}<text x="4" y="${g.barTop+12}">${g.maxOrders} шт.</text><line class="econ-daily-baseline" x1="64" x2="984" y1="${g.barBottom}" y2="${g.barBottom}"/>${g.bars.map(b=>`<rect class="econ-daily-bar" x="${b.x-b.width/2}" y="${g.barBottom-b.height}" width="${b.width}" height="${b.height}"/>`).join('')}${paths(g.segments,g.points)}${paths(g.buyerSegments,g.buyerPoints,'econ-daily-buyer-line')}${dates}<line data-daily-cursor hidden class="econ-daily-cursor" x1="0" x2="0" y1="${g.lineTop}" y2="${g.barBottom}"/></svg>`;
}

function contents(sku){
  const item=cache.get(sku), large=expanded.has(sku), id='econ-daily-'+encodeURIComponent(sku);
  const header=`<div class="econ-daily-head"><strong>СПП, цена покупателя и заказы</strong><span class="econ-daily-legend"><i class="spp"></i> СПП <i class="buyer"></i> Цена покупателя <i class="orders"></i> Заказано, шт.</span><button type="button" data-daily-toggle aria-expanded="${large}" aria-controls="${id}">${large?'Свернуть':'Раскрыть'}</button></div>`;
  if(!item||item.loading)return header+`<p id="${id}" class="econ-daily-status" role="status">Загружаем историю…</p>`;
  if(item.error)return header+`<p id="${id}" class="field-error" role="status">${e(item.error)} <button type="button" data-daily-retry>Повторить</button></p>`;
  const series=item.series, days=series.days||[];
  if(!days.length)return header+`<p id="${id}" class="econ-daily-status">${e(series.reason||'История заказов отсутствует.')}</p>`;
  return header+`<div id="${id}" class="econ-daily-body ${large?'is-expanded':''}"><div class="econ-daily-period">${series.granularity==='week'?'По неделям':'По дням'} · ${e(date(series.period.from))}–${e(date(series.period.to))} · ${series.complete?'Заказано':'Известно заказов'} ${format.format(series.ordered_qty)} шт. · СПП ${series.spp_min==null?'n/a':series.spp_min===series.spp_max?percent(series.spp_min):percent(series.spp_min)+'–'+percent(series.spp_max)}</div><div class="econ-daily-plot" ${large?'tabindex="0" role="group" aria-label="СПП, цена покупателя и заказы. Стрелки выбирают период; Escape скрывает подсказку."':''}>${chart(series,large)}<div class="econ-daily-tooltip" hidden></div><span class="sr-only" data-daily-live aria-live="polite"></span></div>${series.reason?`<p class="econ-daily-note">${e(series.reason)}</p>`:''}${large?`<p class="econ-daily-note">Средние за ${series.granularity==='week'?'неделю':'день'} по единицам товара. ${series.granularity==='week'?'Недели с понедельника по воскресенье; крайние ограничены выбранными датами.':''} СПП каждого заказа = (цена продавца − цена покупателя) / цена продавца. У СПП и цены покупателя отдельные шкалы от минимума до максимума за период. Наведите на период или используйте ← →.</p>`:''}</div>`;
}

function markup(sku){return `<section class="econ-daily-panel" data-daily-sku="${e(sku)}" aria-label="История СПП и заказов SKU ${e(sku)}">${contents(sku)}</section>`;}

function bind(panel){
  const sku=panel.dataset.dailySku;
  panel.querySelector('[data-daily-toggle]').onclick=()=>{
    if(expanded.has(sku))expanded.delete(sku);else expanded.add(sku);
    panel.innerHTML=contents(sku);bind(panel);
    panel.querySelector('[data-daily-toggle]').focus({preventScroll:true});
  };
  panel.querySelector('[data-daily-retry]')?.addEventListener('click',()=>{cache.delete(sku);mount(container,snapshotId,apiFetch,{period:cachePeriod(),granularity:selection.granularity});});
  const plot=panel.querySelector('.is-expanded .econ-daily-plot'), days=cache.get(sku)?.series?.days;
  if(!plot||!days?.length)return;
  const tooltip=plot.querySelector('.econ-daily-tooltip'), cursor=plot.querySelector('[data-daily-cursor]');
  const live=plot.querySelector('[data-daily-live]');
  let selected=0;
  function show(index,announce=false){
    selected=Math.max(0,Math.min(days.length-1,index));
    const day=days[selected], x=LEFT+WIDTH*(selected+.5)/days.length;
    const label=date(day.day)+(day.to&&day.to!==day.day?'–'+date(day.to):'');
    tooltip.innerHTML=`<strong>${e(label)}</strong><span>СПП ${percent(day.spp)}</span><span>Цена покупателя ${money(day.buyer_price_mean)}</span><span>Заказы ${day.orders==null?'n/a':format.format(day.orders)+' шт.'}</span>`;
    const coverage=day.orders>0&&(day.spp_priced_qty<day.orders||day.buyer_priced_qty<day.orders)?`Цены: СПП ${day.spp_priced_qty} / ${day.orders} шт.; покупатель ${day.buyer_priced_qty} / ${day.orders} шт.`:'';
    if(coverage)tooltip.innerHTML+=`<span class="econ-daily-coverage">${e(coverage)}</span>`;
    tooltip.hidden=false;cursor.hidden=false;cursor.removeAttribute('hidden');
    cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);
    const width=plot.clientWidth;
    const rect=plot.getBoundingClientRect(), viewport=plot.closest('.econ-table-scroll')?.getBoundingClientRect();
    const left=viewport?Math.max(0,viewport.left-rect.left):0;
    const right=viewport?Math.min(width,viewport.right-rect.left):width;
    tooltip.style.left=Math.max(left,Math.min(right-tooltip.offsetWidth,x/1000*width+8))+'px';
    if(announce)live.textContent=`${label}. СПП ${percent(day.spp)}. Цена покупателя ${money(day.buyer_price_mean)}. Заказы ${day.orders==null?'n/a':day.orders+' шт.'}${coverage?'. '+coverage:''}`;
  }
  function hide(){tooltip.hidden=true;cursor.setAttribute('hidden','');live.textContent='';}
  const pick=event=>{
    const rect=plot.getBoundingClientRect();
    show(Math.floor(((event.clientX-rect.left)/rect.width*1000-LEFT)/WIDTH*days.length));
  };
  plot.onpointermove=pick;plot.onpointerdown=pick;
  plot.onpointerleave=()=>{if(root.document.activeElement!==plot)hide();};
  plot.onfocus=()=>show(selected,true);plot.onblur=hide;
  plot.onkeydown=event=>{
    if(event.key==='Escape'){hide();return;}
    const next=event.key==='ArrowLeft'?selected-1:event.key==='ArrowRight'?selected+1:
      event.key==='Home'?0:event.key==='End'?days.length-1:null;
    if(next!==null){event.preventDefault();show(next,true);}
  };
}

function update(skus){
  container?.querySelectorAll('[data-daily-sku]').forEach(panel=>{
    if(!skus.includes(panel.dataset.dailySku))return;
    const active=root.document?.activeElement;
    const focus=active&&panel.contains(active)?active.matches('.econ-daily-plot')?'.econ-daily-plot':'[data-daily-toggle]':null;
    panel.innerHTML=contents(panel.dataset.dailySku);bind(panel);
    if(focus)panel.querySelector(focus)?.focus({preventScroll:true});
  });
}

async function load(skus,id,fetch,options,run){
  if(snapshotId!==id||run!==generation)return;
  for(let start=0;start<skus.length;start+=100){
    const batch=skus.slice(start,start+100);
    try{
      const response=await fetch('/api/economics/daily-series',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({analysis_snapshot_id:id,skus:batch,...options})});
      const payload=await response.json();
      if(snapshotId!==id||run!==generation)return;
      if(!response.ok)throw Error(payload.error?.message||'Не удалось загрузить историю.');
      if(payload.snapshot_id!==id||batch.some(sku=>!payload.series?.[sku]))throw Error('Не удалось подтвердить историю заказов.');
      batch.forEach(sku=>cache.set(sku,{series:payload.series[sku]}));
    }catch(error){if(snapshotId!==id||run!==generation)return;batch.forEach(sku=>cache.set(sku,{error:error.message||'Не удалось загрузить историю.'}));}
    update(batch);
  }
  scheduleRefresh();
}

function scheduleRefresh(){
  if(refreshTimer||!container)return;
  const visible=[...container.querySelectorAll('[data-daily-sku]')].map(panel=>panel.dataset.dailySku);
  if(!visible.some(sku=>cache.get(sku)?.series?.price_pending))return;
  const id=snapshotId,run=generation,fetch=apiFetch,options={...selection};
  refreshTimer=root.setTimeout(()=>{
    refreshTimer=null;
    if(id!==snapshotId||run!==generation||container.closest('[data-section]')?.hidden)return;
    const skus=[...container.querySelectorAll('[data-daily-sku]')].map(panel=>panel.dataset.dailySku);
    load(skus,id,fetch,options,run);
  },5000);
}

function cachePeriod(){return selection.period_from?{from:selection.period_from,to:selection.period_to}:null;}
function mount(element,id,fetch,{period=null,granularity='day'}={}){
  const next={granularity,...(period?{period_from:period.from,period_to:period.to}:{})},key=JSON.stringify(next);
  if(snapshotId!==id||selectionKey!==key){
    if(refreshTimer){root.clearTimeout(refreshTimer);refreshTimer=null;}
    if(snapshotId!==id)expanded.clear();
    snapshotId=id;selectionKey=key;selection=next;generation++;cache.clear();
  }
  container=element;apiFetch=fetch;
  const missing=[];
  container.querySelectorAll('[data-daily-sku]').forEach(panel=>{
    const sku=panel.dataset.dailySku;
    if(!cache.has(sku)){cache.set(sku,{loading:true});missing.push(sku);}
    bind(panel);
  });
  if(missing.length){update(missing);load(missing,id,fetch,{...selection},generation);}
  else scheduleRefresh();
}
S.EconomicsDaily={geometry,markup,mount};
})(globalThis);
