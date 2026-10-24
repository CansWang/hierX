() => {
  // Read visible SVG primitives, not ELK's returned layout or interpreted model.
  const svg = document.querySelector("#canvas svg"), errors = [], objects = [];
  if (!svg) return {errors: [{message: "SVG unavailable"}], objects, view_box: {x: 0,y: 0,width: 0,height: 0}};
  const box = e => { const b = e.getBBox(); return {x:b.x,y:b.y,width:b.width,height:b.height}; };
  for (const g of svg.querySelectorAll("g[data-hx-id]")) {
    const id = g.dataset.hxId, role = g.dataset.hxRole;
    const labels = [...g.querySelectorAll("text")];
    const peer = [...svg.querySelectorAll("g[data-hx-label-for]")].find(n=>n.dataset.hxLabelFor===id);
    if (peer) labels.push(...peer.querySelectorAll("text"));
    const row = {id,role,labels: labels.map(t=>({text:t.textContent,box:box(t)})),hrefs:[...g.querySelectorAll("a")].map(a=>a.getAttribute("href"))};
    if (["block","input","output"].includes(role)) {
      const primitive = g.querySelector("rect,circle,ellipse");
      if (!primitive) { errors.push({id,message:"Unmeasurable object primitive"}); continue; }
      row.primitive=primitive.tagName;row.box=box(primitive);
    } else if (["wire","exposure"].includes(role)) {
      const paths=[...g.querySelectorAll("path")];row.points=[];
      for(const p of paths){
        if(p.getAttribute("marker-end")!=="url(#hx-arrow)" || svg.querySelector("#hx-arrow path")?.getAttribute("d")!=="M0,0 L8,4 L0,8 Z") errors.push({id,message:"Unmeasurable arrow marker"});
        const n=p.getTotalLength(),count=Math.min(10000,Math.max(1,Math.ceil(n/2)));
        for(let i=0;i<=count;i++){const q=p.getPointAtLength(n*i/count);row.points.push({x:q.x,y:q.y});}
      }
      row.start=row.points[0];row.end=row.points[row.points.length-1];
      if(!row.start)errors.push({id,message:"Missing route"});
    } else errors.push({id,message:"Unknown object role"});
    objects.push(row);
  }
  const v=svg.viewBox.baseVal;
  return {errors,objects,view_box:{x:v.x,y:v.y,width:v.width,height:v.height}};
}
