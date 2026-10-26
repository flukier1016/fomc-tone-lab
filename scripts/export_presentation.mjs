/** Editable editorial presentation from the read-only Story JSON and rendered exhibits.
 * Usage: RUNTIME_NODE_MODULES=/path/to/node_modules node scripts/export_presentation.mjs WORK
 * WORK/build contains story.json, manifest.json and reference.json. No model or data pipeline is called.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const work=path.resolve(process.argv[2]||(()=>{throw new Error('Give the work folder that render_presentation.py prepared.')})()),dir=path.join(work,'build');
const require=createRequire(import.meta.url);
const runtime=process.env.RUNTIME_NODE_MODULES;
const modulePath=require.resolve('@oai/artifact-tool',runtime?{paths:[runtime]}:undefined);
const {Presentation,PresentationFile}=await import(pathToFileURL(modulePath).href);
const story=JSON.parse(await fs.readFile(path.join(dir,'story.json'),'utf8'));
const manifest=JSON.parse(await fs.readFile(path.join(dir,'manifest.json'),'utf8'));
const ref=JSON.parse(await fs.readFile(path.join(dir,'reference.json'),'utf8'));
const width=ref.cx/9525,height=ref.cy/9525,sx=width/1600,sy=height/900;
// Two typefaces and one accent, from scripts/deck_theme.json (or the file DECK_THEME names, to compare candidates).
const theme=JSON.parse(await fs.readFile(process.env.DECK_THEME||new URL('./deck_theme.json',import.meta.url),'utf8'));
const palette=theme.palette,F=theme.fonts;
const ppt=Presentation.create({slideSize:{width,height}});
const sections=story.slides.find(s=>s.id==='agenda')?.visual.rows||[];
// Summary slides sit on the warm paper with cards; every other slide keeps the white page.
const WARM=new Set(['cover','answers','takeaways','limits','closing']);
function rect(slide,x,y,w,h,fill=palette.rule){return slide.shapes.add({geometry:'rect',position:{left:x*sx,top:y*sy,width:w*sx,height:h*sy},fill,line:{fill:'none',width:0}});}
function text(slide,x,y,w,h,value,size=24,{bold=false,color=palette.body,font=F.text,align='left',nowrap=false,title=false,valign='middle'}={}){
 const shape=slide.shapes.add({geometry:'textbox',position:{left:x*sx,top:y*sy,width:w*sx,height:h*sy},fill:'none',line:{fill:'none',width:0},...(title?{placeholderType:'title'}:{})});
 shape.text=String(value??'');shape.text.insets=0;
 shape.text.style={typeface:font,fontSize:size*sx,color,bold,alignment:align,verticalAlignment:valign,autoFit:'shrinkText',wrap:nowrap?'none':'square'};
 return shape;
}
async function image(slide,file,x,y,w,h,alt){const b=await fs.readFile(file);slide.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt,fit:'contain',position:{left:x*sx,top:y*sy,width:w*sx,height:h*sy}});}
function bodyFrame(s){
 const frame=manifest.frames[s.n];
 if(!frame)throw new Error('No exhibit frame for slide '+s.n);
 return frame;
}
function chrome(slide,s,i){
 slide.background.fill=WARM.has(s.id)?palette.warm:palette.paper;
 const chapter=Number.isInteger(s.part)?sections[s.part]:null;
 const start=chapter&&story.slides[i-1]?.part!==s.part;
 if(chapter){text(slide,80,36,44,28,String(s.part+1).padStart(2,'0'),17,{bold:true,color:palette.accent});text(slide,138,36,1130,28,chapter[0].toUpperCase(),16,{bold:true,color:palette.label});}
 else text(slide,80,36,1220,28,s.kicker.toUpperCase(),16,{bold:true,color:palette.label});
 text(slide,1350,36,170,28,`${s.n} / ${story.slides.length}`,16,{align:'right',color:palette.label});
 rect(slide,80,73,1440,start?3:1,start?palette.ink:palette.rule);
 text(slide,80,98,1440,66,s.title,55,{bold:F.displayBold,color:palette.ink,font:F.display,nowrap:true,title:true});
 text(slide,80,177,1440,48,s.subtitle,24);
 if(s.desk){rect(slide,80,778,3,38,palette.accent);text(slide,101,777,140,38,s.desk_label||'For the desk',15,{bold:true,color:palette.ink});text(slide,256,776,1264,42,s.desk,21);}
 if(s.source){rect(slide,80,835,1440,1);text(slide,80,844,1440,36,'Source: '+s.source,16,{color:palette.label});}
 if(chapter)for(let j=0;j<5;j++)rect(slide,j*320,895,317,5,j===s.part?palette.accent:palette.rule);
}
function lead(slide,s){
 const chips=(s.chips||[]).filter(Boolean);
 if(s.layout==='wide')return;
 if(s.layout==='banner'){
  text(slide,80,252,228,87,s.number,66,{bold:true,color:palette.ink,nowrap:true});
  text(slide,330,253,280,86,s.number_label,20);
  const n=Math.min(4,chips.length),w=(886-22*(n-1))/Math.max(1,n);
  chips.slice(0,n).forEach((c,j)=>{const x=634+j*(w+22);rect(slide,x,263,1,70);text(slide,x+18,252,w-18,86,c,19);});
  rect(slide,80,351,1440,1);return;
 }
 const x=s.layout==='mirror'?1160:80;
 if(s.layout==='compare'){
  let y=260;
  for(const [j,[number,label]] of (s.compare||[]).entries()){
   if(j){text(slide,x,y,360,20,(s.compare_word||'against').toUpperCase(),13,{bold:true,color:palette.label});y+=38;}
   text(slide,x,y,360,88,number,76,{bold:true,color:palette.ink,nowrap:true});
   text(slide,x,y+93,360,74,label,22);y+=192;
  }
  const said=(s.compare||[]).map(([n])=>n);
  const extra=chips.find(c=>!said.some(n=>c.includes(n.replace(/^r = /,''))));
  if(extra&&y<730){rect(slide,x,y,360,1);text(slide,x,y+12,360,Math.max(40,752-y),extra,20);}
  return;
 }
 text(slide,x,258,360,94,s.number,76,{bold:true,color:palette.ink,nowrap:true});
 text(slide,x,365,360,90,s.number_label,22);
 const y0=478,remaining=(s.desk?752:810)-y0,h=remaining/Math.max(1,Math.min(chips.length,4));
 chips.slice(0,4).forEach((c,j)=>{const y=y0+j*h;rect(slide,x,y,360,1);text(slide,x,y+10,360,h-17,c,20);});
}
function colsFor(v,w,id){
 if(id==='course-links')return [600,840].map(x=>x*w/1440);
 if(id==='brief-audit')return [350,580,510].map(x=>x*w/1440);
 if(id==='tech-tests')return [.25,.08,.67].map(x=>x*w);
 if(id==='tech-validity')return [275,125,125,140,200,195,190,190].map(x=>x*w/1440);
 const lengths=v.columns.map((h,i)=>Math.max(String(h).length,...v.rows.map(r=>String(r[i]??'').length)));
 const weights=lengths.map(n=>Math.max(14,Math.min(62,n)));  // the first words of a column stay whole
 const total=weights.reduce((a,b)=>a+b,0);return weights.map(n=>w*n/total);
}
function contents(slide,s,f){
 const rows=s.visual.rows,h=f.h/rows.length;
 rows.forEach(([name,about,range],i)=>{
  const y=f.y+i*h;rect(slide,f.x,y,f.w,i?1:2,i?palette.rule:palette.ink);
  text(slide,f.x,y,80,h,String(i+1).padStart(2,'0'),34,{bold:true,color:palette.accent});
  text(slide,f.x+100,y,520,h,name,34,{font:F.display,bold:F.displayBold,color:palette.ink});
  text(slide,f.x+640,y,620,h,about,24);
  text(slide,f.x+1270,y,170,h,range.replace('-','–'),24,{align:'right',color:palette.label});
 });
 rect(slide,f.x,f.y+f.h,f.w,1);
}
function table(slide,s,f){
 const v=s.visual;
 const values=[v.columns,...v.rows],noteH=v.note?40:0,H=f.h-noteH;
 const font=v.rows.length<=7?24:v.rows.length<=10?21:20;
 const head=62,rest=(H-head)/v.rows.length;
 const t=slide.tables.add({rows:values.length,columns:v.columns.length,left:f.x*sx,top:f.y*sy,width:f.w*sx,height:H*sy,columnWidths:colsFor(v,f.w,s.id).map(n=>n*sx),values});
 t.borders.assign({fill:'none',width:0});
 for(let r=0;r<values.length;r++){
  t.rows[r].height=(r?rest:head)*sy;
  for(let c=0;c<v.columns.length;c++){
   const cell=t.getCell(r,c);cell.fill=r===0?palette.soft:r-1===v.highlight?palette.highlight:palette.paper;
   cell.text.style={typeface:F.text,fontSize:(r?font:18)*sx,bold:r===0||c===0,color:r===0?palette.ink:palette.body,verticalAlignment:'middle',alignment:v.align?.[c]==='r'?'right':'left'};
  }
  const y=f.y+(r?head+r*rest:head);rect(slide,f.x,y,f.w,r===0?1.5:.7,r===0?palette.ink:palette.rule);
 }
 if(v.note)text(slide,f.x,f.y+H+8,f.w,noteH-8,v.note,17,{color:palette.label});
}
function blocks(slide,items,f,{columns=2,large=false,numbered=true,compact=false,card=false}={}){
 const rows=Math.ceil(items.length/columns),gapX=card?28:40,gapY=28,w0=(f.w-gapX*(columns-1))/columns,h=(f.h-gapY*(rows-1))/rows;
 items.forEach(([heading,description],i)=>{
  const x0=f.x+(i%columns)*(w0+gapX),y0=f.y+Math.floor(i/columns)*(h+gapY);
  const ch=card?Math.min(h,400):h;  // cards hug their text instead of stretching to the frame
  if(card){rect(slide,x0,y0,w0,ch,palette.card);rect(slide,x0,y0,w0,3,palette.ink);}
  const pad=card?26:0,x=x0+pad,y=y0+(card?6:0),w=w0-2*pad;
  if(!card)rect(slide,x,y,w,1.5,large?palette.ink:palette.rule);
  if(compact){text(slide,x,y+15,34,28,String(i+1).padStart(2,'0'),19,{bold:true,color:palette.accent});text(slide,x+48,y+10,w-48,40,heading,25,{bold:true,color:palette.ink});text(slide,x+48,y+58,w-48,h-68,description,20);return;}
  if(numbered)text(slide,x,y+18,w,30,String(i+1).padStart(2,'0'),22,{bold:true,color:palette.accent});
  if(card){
   text(slide,x,y+62,w,84,heading,28,{font:F.display,bold:F.displayBold,color:palette.ink,valign:'top'});
   text(slide,x,y+156,w,y0+ch-y-176,description,23,{valign:'top'});return;
  }
  const top=y+(numbered?62:22),metric=large&&/^(?:[+−-]?\d|r\s*=)/.test(heading);
  text(slide,x,top,w,large?70:52,heading,metric?44:large?30:28,{bold:true,color:palette.ink});
  text(slide,x,top+(large?88:65),w,Math.max(48,y0+h-top-(large?98:76)-(card?20:0)),description,items.length>=8?21:24);
 });
}
// Code and formula panels keep their aligned columns without a monospace face: each run of text that starts a column
// in the source lines becomes its own box, placed after the widest run before it (Arial advance widths, 1/1000 em).
const ADVANCE={' ':278,'"':355,"'":191,'#':556,'(':333,')':333,'+':584,',':278,'-':333,'.':278,'/':278,':':278,';':278,
 '=':584,'[':278,']':278,'{':334,'}':334,'|':260,'_':556,'…':1000,'·':278,'−':584,'≥':549,'×':584,'→':1000,'√':549,'²':333,
 'Σ':713,'Δ':668,'Φ':800,'θ':556,'α':578,'β':575,'γ':500,'ε':444,'±':584};
const advance=ch=>ADVANCE[ch]??(/[A-Z]/.test(ch)?690:/[0-9]/.test(ch)?556:/[fijlrt]/.test(ch)?270:/[mw]/.test(ch)?790:540);
const measure=(s,size)=>[...s].reduce((u,ch)=>u+advance(ch),0)/1000*size;
function formula(slide,lines,f){
 rect(slide,f.x,f.y,f.w,f.h,palette.soft);rect(slide,f.x,f.y,3,f.h,palette.ink);
 const runs=lines.map(line=>[...line.matchAll(/[^ ](?:[^ ]| (?! ))*/g)].map(m=>({at:m.index,text:m[0]})));
 // columns within four characters of each other past the indentation are one column (the source aligns them loosely)
 const starts=[...new Set(runs.flat().map(r=>r.at))].sort((a,b)=>a-b),column=new Map();let k=-1,last=-99;
 for(const a of starts){if(!(a>10&&a-last<=4))k++;column.set(a,k);last=a;}
 const left=f.x+30,right=f.x+f.w-30,gap=30;
 const place=size=>{
  const x=[left],cw=0.55*size;
  for(let c=1;c<=k;c++){
   const first=Math.min(...starts.filter(a=>column.get(a)===c)),prev=Math.min(...starts.filter(a=>column.get(a)===c-1));
   let at=x[c-1]+(first-prev)*cw;
   for(const line of runs)line.forEach((r,j)=>{const n=line[j+1];if(n&&column.get(n.at)===c&&column.get(r.at)<c)at=Math.max(at,x[column.get(r.at)]+measure(r.text,size)+gap);});
   x.push(at);
  }
  return {x,widest:Math.max(...runs.map(line=>line.length?x[column.get(line.at(-1).at)]+measure(line.at(-1).text,size):left))};
 };
 let size=20,spot=place(size);
 while(spot.widest>right&&size>14){size-=0.5;spot=place(size);}
 const lh=Math.min(size*1.9,(f.h-44)/lines.length),top=f.y+(f.h-lh*lines.length)/2;
 runs.forEach((line,i)=>line.forEach((r,j)=>{
  const x=spot.x[column.get(r.at)],w=j<line.length-1?spot.x[column.get(line[j+1].at)]-x:right-x;
  text(slide,x,top+i*lh,Math.max(w,measure(r.text,size)+4),lh,r.text,size,{color:r.text.startsWith('#')?palette.label:palette.ink,nowrap:true});
 }));
}
async function cover(slide,s){
 slide.background.fill=palette.warm;
 await image(slide,manifest.logo,80,56,64,64,'FOMC Tone Lab');
 text(slide,170,68,1350,40,s.kicker,17,{bold:true,color:palette.label});rect(slide,80,143,1440,1);
 text(slide,80,s.layout==='closing'?250:274,1440,148,s.title,124,{font:F.display,bold:F.displayBold,color:palette.ink,nowrap:true,title:true});
 text(slide,80,s.layout==='closing'?418:444,1380,84,s.subtitle,32);
 if(s.layout==='cover'){
  const nodes=[['Read','Fed language'],['Measure','Policy tone'],['Test','Treasury yields'],['Size','Portfolio duration']];
  nodes.forEach(([a,b],i)=>{const x=80+i*368;rect(slide,x,570,336,2,palette.ink);text(slide,x,590,336,25,`0${i+1} / ${a.toUpperCase()}`,16,{bold:true,color:palette.accent});text(slide,x,629,336,44,b,30,{font:F.display,bold:F.displayBold,color:palette.ink});});
  (s.links||[]).forEach(([a,b],i)=>{const x=80+i*736;text(slide,x,700,700,24,a.toUpperCase(),16,{bold:true,color:palette.label});text(slide,x,728,700,36,b,26,{color:palette.ink,nowrap:true});});
 }else{
  text(slide,80,548,1440,60,s.url,34,{color:palette.ink});
  if(s.repo)text(slide,80,610,1440,60,s.repo,34,{color:palette.ink});
 }
 rect(slide,80,782,1440,1);let x=80;
 for(const name of s.team||[]){text(slide,x,805,330,40,name,22,{color:palette.ink});x+=360;}
}
const flow=[['Document','Cleaned text, the Fed’s words only; no date or title shown'],['Rubric v1','Six policy dimensions, stance and confidence; cached system prompt'],['Claude Opus 5.5','Adaptive thinking, structured JSON output, Message Batches'],['Verify','Checks every quote; stores matched spans and unmatched exceptions'],['Record','JSON keyed by a hash of prompt, schema and text, with IDs and tokens'],['Store','Scores, evidence and costs in SQLite; the dashboard reads them']];
for(const [i,s] of story.slides.entries()){
 const slide=ppt.slides.add();slide.speakerNotes.text=(s.notes||'')+(s.source?'\nSource: '+s.source:'');
 if(['cover','closing'].includes(s.layout)){await cover(slide,s);continue;}
 chrome(slide,s,i);lead(slide,s);const f=bodyFrame(s),v=s.visual;
 if(s.id==='agenda')contents(slide,s,f);
 else if(v?.kind==='table')table(slide,s,f);
 else if(v?.kind==='steps')blocks(slide,v.steps,f,{columns:v.steps.length===4?2:3});
 else if(v?.kind==='cards')blocks(slide,v.cards,f,{columns:v.cards.length===4?4:3,card:WARM.has(s.id)});
 else if(v?.kind==='tiles')blocks(slide,v.tiles,f,{columns:v.tiles.length===4?2:v.tiles.length===8?4:3,numbered:false,large:true});
 else if(v?.kind==='flow')blocks(slide,flow,f,{columns:2,compact:true});
 else if(v?.kind==='code')formula(slide,v.lines,f);
else if(v?.kind==='answers'){
  // One card per hypothesis; the verdict is a word on a tinted label, so color never carries it alone.
  const w=(f.w-84)/4,pad=26;v.cards.forEach(([h,claim,verdict,metric],j)=>{
   const x=f.x+j*(w+28),no=verdict==='Not supported',ok=verdict.startsWith('Supported');
   const [ink,soft]=ok?[palette.ok,palette.okSoft]:no?[palette.no,palette.noSoft]:[palette.mixed,palette.mixedSoft];
   const ch=Math.min(f.h,470);rect(slide,x,f.y,w,ch,palette.card);rect(slide,x,f.y,w,4,no?palette.accent:palette.ink);
   text(slide,x+pad,f.y+26,w-2*pad,28,h.toUpperCase(),16,{bold:true,color:palette.label});
   text(slide,x+pad,f.y+70,w-2*pad,150,claim,27,{font:F.display,bold:F.displayBold,color:palette.ink,valign:'top'});
   rect(slide,x+pad,f.y+240,w-2*pad,72,soft);text(slide,x+pad+14,f.y+240,w-2*pad-28,72,verdict,21,{bold:true,color:ink});
   text(slide,x+pad,f.y+336,w-2*pad,ch-356,metric,22,{valign:'top'});
  });
 }else if(v?.kind==='brief'){
  text(slide,f.x+64,f.y,f.w/2-110,35,'THE BRIEF ASKS FOR',15,{bold:true,color:palette.label});text(slide,f.x+f.w/2+40,f.y,f.w/2-40,35,'WHAT WE BUILT',15,{bold:true,color:palette.label});
  const h=(f.h-55)/v.rows.length;v.rows.forEach(([ask,did],j)=>{const y=f.y+55+j*h;rect(slide,f.x,y,f.w,1);text(slide,f.x,y+14,42,h-24,String(j+1).padStart(2,'0'),21,{bold:true,color:palette.accent});text(slide,f.x+64,y+14,f.w/2-118,h-24,ask,22,{color:palette.ink});text(slide,f.x+f.w/2+40,y+14,f.w/2-40,h-24,did,22);});
 }else if(manifest.visuals[s.n])await image(slide,manifest.visuals[s.n],f.x,f.y,f.w,f.h,s.title+' exhibit');
}
const candidate=path.join(dir,'candidate-editable.pptx');await(await PresentationFile.exportPptx(ppt)).save(candidate);
for(const n of [1,2,14,25,30]){const png=await ppt.export({slide:ppt.slides.items[n-1],format:'png',scale:1});await fs.writeFile(path.join(dir,`native-preview-${n}.png`),new Uint8Array(await png.arrayBuffer()));}
console.log('Authored',ppt.slides.items.length,'editorial slides with native text, tables and methods.');
