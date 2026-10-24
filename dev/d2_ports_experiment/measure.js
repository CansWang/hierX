// Read geometry only. The single DOM mutation adds identity attributes for
// browser locators; no positions, routes, styles or links are changed here.
async () => {
  await document.fonts.ready;
  const svg = document.querySelector('svg.d2-svg') || document.querySelector('svg');
  if (!svg) throw new Error('No SVG document');
  const inverse = svg.getScreenCTM().inverse();
  function point(el, x, y) {
    return new DOMPoint(x, y).matrixTransform(el.getScreenCTM()).matrixTransform(inverse);
  }
  function box(el) {
    const b = el.getBBox();
    const points = [point(el,b.x,b.y), point(el,b.x+b.width,b.y),
                    point(el,b.x,b.y+b.height), point(el,b.x+b.width,b.y+b.height)];
    const xs=points.map(p=>p.x), ys=points.map(p=>p.y);
    return {x:Math.min(...xs), y:Math.min(...ys),
      width:Math.max(...xs)-Math.min(...xs), height:Math.max(...ys)-Math.min(...ys)};
  }
  function identity(g) {
    const first=g.classList[0];
    const raw=atob(first.replace(/-/g,'+').replace(/_/g,'/'));
    const decoded=new TextDecoder().decode(Uint8Array.from(raw,c=>c.charCodeAt(0)));
    const text=document.createElementNS('http://www.w3.org/1999/xhtml','textarea'); text.innerHTML=decoded;
    return text.value;
  }
  function visibleEnd(path, points, attr, end) {
    const markerRef=path.getAttribute(attr);
    if (!markerRef) return end ? points[points.length-1] : points[0];
    const match=markerRef.match(/#([^)'\"]+)/);
    const marker=match && document.getElementById(match[1]);
    if (!marker || marker.getAttribute('markerUnits')!=='userSpaceOnUse')
      throw new Error('Unmeasurable arrowhead units');
    const polygon=marker.querySelector('polygon');
    if (!polygon) throw new Error('Unmeasurable arrowhead primitive');
    const vertices=polygon.getAttribute('points').trim().split(/\s+/).map(v=>v.split(',').map(Number));
    const refX=Number(marker.getAttribute('refX')), refY=Number(marker.getAttribute('refY'));
    const tip=vertices.reduce((a,b)=>b[0]>a[0]?b:a);
    const view=marker.viewBox.baseVal;
    const sx=Number(marker.getAttribute('markerWidth'))/view.width;
    const sy=Number(marker.getAttribute('markerHeight'))/view.height;
    const length=path.getTotalLength();
    const p=path.getPointAtLength(end?length:0);
    const q=path.getPointAtLength(end?Math.max(0,length-0.1):Math.min(length,0.1));
    let angle=Math.atan2(p.y-q.y,p.x-q.x);
    if (!end && marker.getAttribute('orient')==='auto-start-reverse') angle+=Math.PI;
    const u=(tip[0]-refX)*sx, v=(tip[1]-refY)*sy;
    const result=point(path,p.x+u*Math.cos(angle)-v*Math.sin(angle),p.y+u*Math.sin(angle)+v*Math.cos(angle));
    return {x:result.x,y:result.y};
  }
  const objects=[], errors=[];
  for (const g of document.querySelectorAll('g.hx-block,g.hx-input,g.hx-output,g.hx-wire,g.hx-exposure')) {
    let id;
    try {
      id=identity(g); g.dataset.hxId=id;
      const role=['block','input','output','wire','exposure'].find(r=>g.classList.contains('hx-'+r));
      const labels=[...g.querySelectorAll('text')].map(el=>({text:el.textContent.trim(),box:box(el)}));
      // Stock D2 wraps the role group in <a>; synthetic oracle SVGs put
      // anchors inside it. Inspect both without borrowing a parent's link.
      const anchors=[...g.querySelectorAll('a')];
      if (g.parentElement?.localName==='a') anchors.push(g.parentElement);
      const hrefs=anchors.map(el=>el.getAttribute('href')||el.getAttributeNS('http://www.w3.org/1999/xlink','href')).filter(Boolean);
      if (role==='wire' || role==='exposure') {
        const path=g.querySelector('path.connection') || g.querySelector('path');
        if (!path) throw new Error('Connection has no path');
        const len=path.getTotalLength(), count=Math.min(10000,Math.max(2,Math.ceil(len/2)));
        const points=Array.from({length:count+1},(_,i)=>{const p=path.getPointAtLength(len*i/count);const q=point(path,p.x,p.y);return {x:q.x,y:q.y};});
        objects.push({id,role,labels,hrefs,points,start:visibleEnd(path,points,'marker-start',false),end:visibleEnd(path,points,'marker-end',true)});
      } else {
        const body=g.querySelector('rect,ellipse,circle,path');
        if (!body) throw new Error('Object has no outline primitive');
        objects.push({id,role,labels,hrefs,box:box(body),primitive:body.tagName.toLowerCase()});
      }
    } catch (e) { errors.push({id:id||null,message:String(e)}); }
  }
  const view=svg.viewBox.baseVal;
  return {objects,errors,view_box:{x:view.x,y:view.y,width:view.width,height:view.height}};
}
