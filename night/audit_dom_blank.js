#!/usr/bin/env node
/**
 * night/audit_dom_blank.js — dom空欄が堀指数に与えている「下駄」を数える（2026-08-04新設）
 *
 * なぜ作ったか: 2026-08-04の実測で **dom空欄の再正規化は、数学的に
 *   「domは残り4本の加重幾何平均に等しい」と仮定するのと同一**だと判明した
 *   （ADBE: 他4本の加重幾何平均70.8 ≒ dom空欄時の堀指数71.2）。
 *   v9.9.39は「空欄は既定値70に化けない」と書いたが、**数値としては≒70**になる。
 *   これは判定圏の半数近くに効いており、一度きりの計測で終わらせると
 *   台帳が変わったときに誰も気づけない。だから道具にした。
 *
 * 使い方: node night/audit_dom_blank.js [--all]
 *   （既定は判定圏Ω72+のみ。--all で全件）
 *
 * 読み方: 「下駄」= dom空欄時の堀指数 − dom=50と確定した場合の堀指数。
 *   domが他4本より低いはずの社では下駄、高いはずの社では損になる。
 *   **この道具は診断であって有罪判決ではない**——空欄が正しい社が実在する
 *   （v9.9.41(1)の「事業別に刻みが散る」＝IRMD/CW/ISRG/3923、
 *    および掘り尽くして測れないと確定した社＝ADBE/NVDA/MSFT/RMD/6146/6861）。
 *
 * 初回実測(2026-08-04): 判定圏48社中22社が空欄・平均の下駄 +7.5pt・
 *   **投下可10社のうち7社**が空欄のまま関門70を通過。
 *   これを受けて「関門を75へ」「空欄を50扱いに」の2案を測ったが、
 *   総合リターンが 13.34% → 10.95% / 12.25% と**いずれも下がる**ため
 *   2026-08-04時点では**現状維持**を選んだ（CLAUDE.mdの判断記録を見よ）。
 */
'use strict';
const fs=require('fs'), path=require('path');
const ROOT=path.dirname(__dirname);
const {scorePack}=require('./score_all.js');
const all=process.argv.includes('--all');
const rows=JSON.parse(fs.readFileSync(path.join(ROOT,'out/score_all.json'),'utf8'));
const pk=t=>{const f=path.join(ROOT,'out',t+'_gate_pack.json');return fs.existsSync(f)?JSON.parse(fs.readFileSync(f,'utf8')):null;};
const moatOf=(b,dom)=>{const d=JSON.parse(JSON.stringify(b));d.dom=dom;let r;try{r=scorePack(d);}catch(e){return null;}
  return r.moatNA?null:(r.moat||r.moatIdx);};

const target=rows.filter(x=>all?true:((x.s||0)>=72));
const out=[]; let blanks=0;
for(const x of target){
  const b=pk(x.t); if(!b||b.dom!=null) continue;
  blanks++;
  const a=moatOf(b,null), c=moatOf(b,50), e=moatOf(b,70);
  if(a==null||c==null) continue;
  out.push({t:x.t,buy:!!x.buy,s:x.s,blank:a,d50:c,d70:e,gain:+(a-c).toFixed(1),
    passBlank:a>=70, passD50:c>=70});
}
out.sort((p,q)=>q.gain-p.gain);
console.log(`対象 ${target.length}社${all?'（全件）':'（判定圏Ω72+）'} / うち dom空欄 ${blanks}社\n`);
console.log('銘柄     投下可    Ω    空欄   dom=50  dom=70   下駄   関門70');
for(const r of out)
  console.log(`${r.t.padEnd(8)}${(r.buy?'🟢':'  ').padEnd(6)}${String(r.s).padStart(5)}`
    +`${String(r.blank).padStart(7)}${String(r.d50).padStart(8)}${String(r.d70).padStart(8)}`
    +`${('+'+r.gain).padStart(7)}   ${r.passBlank?'通過':'不足'}${r.passBlank&&!r.passD50?' ← 空欄に依存':''}`);
const g=out.map(r=>r.gain), avg=g.reduce((a,b)=>a+b,0)/g.length;
const dep=out.filter(r=>r.passBlank&&!r.passD50);
console.log(`\n平均の下駄 +${avg.toFixed(1)}pt（dom=50と確定した場合との差）`);
console.log(`関門70の通過が空欄に依存している社: ${dep.length}社  ${dep.map(r=>r.t+(r.buy?'🟢':'')).join(' ')||'なし'}`);
console.log(`うち現在の投下可: ${dep.filter(r=>r.buy).length}社`);
