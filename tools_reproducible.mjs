// 再現性テスト: 同じ台帳から2回採点して、全銘柄のスコアが完全に一致することを確認する。
// 一致しなければ、スコアは審査者の気分で動いている＝門として使えない。
import { chromium } from 'playwright-core';
import { readFileSync } from 'fs';
const file=process.argv[2]||'out/v5/v5_all_pack.json';
const json=readFileSync(file,'utf8');
const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
async function run(){
  const pg=await b.newPage();
  await pg.goto('file:///home/user/ccf-gate/index.html',{waitUntil:'domcontentloaded'});
  await pg.waitForTimeout(400);
  const r=await pg.evaluate(async(j)=>{
    await processBatch(j); await new Promise(x=>setTimeout(x,700));
    const o={};
    for(let i=0;i<localStorage.length;i++){const k=localStorage.key(i);
      if(k&&k.startsWith('g7:')){const x=JSON.parse(localStorage.getItem(k)); o[x.data.nm]=x.r.evalScore;}}
    return o;
  },json);
  await pg.close(); return r;
}
const a=await run(), c=await run();
const keys=[...new Set([...Object.keys(a),...Object.keys(c)])].sort();
const diff=keys.filter(k=>a[k]!==c[k]);
for(const k of keys) console.log(`  ${k.padEnd(26)} ${a[k]}`);
console.log(diff.length===0
  ? `✓ 再現した: ${keys.length}社すべてが2回とも同じスコア`
  : `✗ 再現しない: ${diff.map(k=>`${k} ${a[k]}→${c[k]}`).join(', ')}`);
await b.close();
process.exit(diff.length?1:0);
