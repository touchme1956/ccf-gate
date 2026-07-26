// 門JSON検証器: ①JSON妥当 ②13定性が埋まりドラフト検問通過 ③実際に台帳へ入る ④採点結果 ⑤エラー無し
import { chromium } from 'playwright-core';
import { readFileSync } from 'fs';
const REQ13=['dom','irr','rep','dur','f1','f2','f3','f4','f5','p1','p2','p3','p4'];
const file=process.argv[2];
const raw=readFileSync(file,'utf8').trim();
let arr; try{ arr=JSON.parse(raw); }catch(e){ console.log('✗ JSON構文エラー:',e.message); process.exit(1); }
if(!Array.isArray(arr)) arr=[arr];
let bad=false;
for(const o of arr){
  const miss=REQ13.filter(k=>o[k]===undefined||o[k]===null||o[k]==='');
  if(miss.length){ console.log(`✗ ${o.nm}: 定性欠落 ${miss.join(',')} → 審査待ちへ隔離される`); bad=true; }
  if(!o.nm){ console.log('✗ nm がない'); bad=true; }
}
if(/[\u201c\u201d\u2018\u2019\uff02\uff07]/.test(raw)){ console.log('NG: smart-quotes found'); bad=true; }
if(bad) process.exit(1);
const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
const pg=await b.newPage(); const errs=[]; pg.on('pageerror',e=>errs.push(String(e)));
await pg.goto('file:///home/user/ccf-gate/index.html',{waitUntil:'domcontentloaded'}); await pg.waitForTimeout(400);
const res=await pg.evaluate(async(json)=>{
  const names=JSON.parse(json).map(o=>o.nm);
  for(let i=localStorage.length-1;i>=0;i--){const k=localStorage.key(i);if(k&&names.some(n=>k.includes(n.split('(')[0])))localStorage.removeItem(k);}
  const drafts=JSON.parse(json).filter(o=>ccfIsDraftObj(o)).map(o=>o.nm);
  await processBatch(json); await new Promise(r=>setTimeout(r,400));
  const out=[];
  for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);
    if(k&&k.startsWith('g7:')&&names.some(n=>k.includes(n.split('(')[0]))){const x=JSON.parse(localStorage.getItem(k));
      out.push({nm:x.data.nm,score:x.r.evalScore,tier:x.r.tierShort||x.r.grade,act:x.r.act});}}
  return {out,drafts};
}, JSON.stringify(arr));
console.log(`検証: ${file}  (${arr.length}社, ${raw.length}文字)`);
if(res.drafts.length) console.log('✗ ドラフト判定され隔離:',res.drafts.join(','));
for(const r of res.out) console.log(`  ✓ ${r.nm}  評価 ${r.score} (${r.tier})  ${r.act}`);
const got=res.out.length;
console.log(got===arr.length&&errs.length===0 ? `✓ 合格: ${got}/${arr.length}社が台帳入り・エラーなし` : `✗ 不合格: 台帳入り${got}/${arr.length} errors=${errs.length}`);
await b.close();
