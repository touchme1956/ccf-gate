import { chromium } from 'playwright-core';
import { readFileSync, writeFileSync } from 'fs';
const arr=JSON.parse(readFileSync('/tmp/all_packs.json','utf8'));
const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
async function run(file){
  const pg=await b.newPage(); pg.setDefaultTimeout(600000);
  await pg.goto('file://'+file,{waitUntil:'domcontentloaded'}); await pg.waitForTimeout(400);
  const out={};
  for(let i=0;i<arr.length;i+=40){
    const chunk=arr.slice(i,i+40);
    const r=await pg.evaluate(async(j)=>{
      const a=JSON.parse(j), o={};
      for(const one of a){
        try{ applyFields(one); const rr=compute();
          o[one.nm]={s:parseFloat(rr.evalScore), t:rr.tierShort||rr.grade, pf:rr.pfail||0, k:rr.kills||0,
            pm:parseFloat(document.getElementById('pmV').textContent),
            pr:parseFloat(document.getElementById('prV').textContent),
            pt:parseFloat(document.getElementById('ptV').textContent)};
        }catch(e){ o[one.nm]={err:String(e).slice(0,60)}; }
      }
      return o;
    }, JSON.stringify(chunk));
    Object.assign(out,r);
  }
  await pg.close(); return out;
}
const before=await run('/tmp/index_v5only.html');
const after =await run('/home/user/ccf-gate/index.html');
writeFileSync('/tmp/rerun.json',JSON.stringify({before,after},null,1));
const nms=Object.keys(after);
const errs=nms.filter(n=>after[n].err);
console.log(`採点 ${nms.length}社 / エラー ${errs.length}`);
if(errs.length) console.log(errs.slice(0,5).map(n=>n+': '+after[n].err).join('\n'));
await b.close();
