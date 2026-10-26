/** Validate and render an editorial draft with the bundled Artifact Tool. See docs/PRESENTATION_DESIGN.md. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const runtime=process.env.RUNTIME_NODE_MODULES;
const library=require.resolve('@oai/artifact-tool',runtime?{paths:[runtime]}:undefined);
const {FileBlob,Presentation,PresentationFile}=await import(pathToFileURL(library).href);
const work=path.resolve(process.argv[2]||(()=>{throw new Error('Give the work folder that render_presentation.py prepared.')})()),dir=path.join(work,'build'),out=path.join(work,'final');
await fs.mkdir(out,{recursive:true});
const story=JSON.parse(await fs.readFile(path.join(dir,'story.json'),'utf8'));
const ref=JSON.parse(await fs.readFile(path.join(dir,'reference.json'),'utf8'));
const theme=JSON.parse(await fs.readFile(process.env.DECK_THEME||new URL('./deck_theme.json',import.meta.url),'utf8'));
const SKILL=process.env.PRESENTATION_SKILL_DIR;
if(!SKILL)throw new Error('Set PRESENTATION_SKILL_DIR to the bundled presentation skill directory.');
const {finalizePresentation}=await import(path.join(SKILL,'container_tools/artifact_tool_utils.mjs'));
const common={workspaceDir:work,pythonExecutable:process.env.RUNTIME_PYTHON||path.resolve('.venv/bin/python'),integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu',`${ref.cx},${ref.cy}`,'--validate-heading-fit'],explicitTotalSlideCount:story.slides.length,verifyArtifactToolImport:true};
const tableOwners=story.slides.filter(s=>s.visual?.kind==='table'&&s.id!=='agenda').map(s=>s.n);  // the contents page is a list
const editable=path.join(out,'FOMC-Tone-Lab-editable.pptx');
await finalizePresentation({...common,candidatePath:path.join(dir,'candidate-editable.pptx'),finalPath:editable,requiredNativeTableOwnerSlides:tableOwners,layoutArgs:[...common.layoutArgs,...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],fontPolicy:{basis:'design',families:[...new Set([theme.fonts.display,theme.fonts.text])]},receiptPath:path.join(dir,'editable-validation.json')});
console.log('Editable finalization passed.');
const ppt=await PresentationFile.importPptx(await FileBlob.load(editable));
const images=Presentation.create({slideSize:{width:ref.cx/9525,height:ref.cy/9525}});
const renders=path.join(work,'rendered');await fs.mkdir(renders,{recursive:true});
const files={};
for(let i=0;i<ppt.slides.items.length;i++){
 const png=await ppt.export({slide:ppt.slides.items[i],format:'png',scale:1.5});
 const raw=new Uint8Array(await png.arrayBuffer()),file=path.join(renders,`slide-${String(i+1).padStart(2,'0')}.png`);
 await fs.writeFile(file,raw);files[i+1]=file;
 const flat=images.slides.add();flat.images.add({blob:raw.buffer.slice(raw.byteOffset,raw.byteOffset+raw.byteLength),contentType:'image/png',alt:story.slides[i].title,fit:'contain',position:{left:0,top:0,width:ref.cx/9525,height:ref.cy/9525}});
 flat.speakerNotes.text=(story.slides[i].notes||'')+'\nSource: '+(story.slides[i].source||'');
 if([1,2,5,14].includes(i+1)||(i+1)%10===0)console.log('Rendered',i+1);
}
await fs.writeFile(path.join(dir,'render-manifest.json'),JSON.stringify(files,null,2));
const candidate=path.join(dir,'candidate-images.pptx');await(await PresentationFile.exportPptx(images)).save(candidate);
await finalizePresentation({...common,candidatePath:candidate,finalPath:path.join(out,'FOMC-Tone-Lab.pptx'),receiptPath:path.join(dir,'image-validation.json')});
console.log('Both finalized:',story.slides.length,'slides,',tableOwners.length,'native editable tables.');
