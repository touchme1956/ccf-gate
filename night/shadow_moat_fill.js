#!/usr/bin/env node
/**
 * night/shadow_moat_fill.js — 「堀を確定させたら判定は動くか」の影の計測（2026-08-04新設）
 *
 * なぜ作ったか: ユーザーの問い「これらの銘柄の堀を確定させることはできないの？」に対し、
 *   原本を読みに行く前に**読んで意味があるかを測る**ため（kill_impact.py と同じ思想）。
 *   堀が測定不能(moatNA)の社の dom/irr を仮に埋めてΩと堀指数がどう動くかを、門の compute() そのもので出す。
 *
 * 使い方: node night/shadow_moat_fill.js
 * 注意: **正本の採点は一切変えない**（パックを読んでメモリ上で埋めるだけ・書き戻さない）。
 *   埋める値は仮定であって審査ではない——実際に立てるには v9.9.41 の原本根拠が要る。
 *
 * 初回実測(2026-08-04・全14社): **最も強気の仮定(dom85/irr85)でも投下可になる社はゼロ。**
 *   読む価値があるのは ROIC柱が既に通っている6社(HOYA/TEL/中外/サイボウズ/ZOZO/FINDEX)だけで、
 *   Ωが0→55〜75へ動く。残り8社は roic 6〜13% で**ROIC柱が別要因で落ちている**ため、
 *   堀を確定させても二本柱の崖から出られない(SUMCO/アリアケはキルでΩ0のまま)。
 */
'use strict';
const fs=require('fs'),path=require('path');
const ROOT='/home/user/ccf-gate';
const {scorePack}=require(path.join(ROOT,'night/score_all.js'));
const TARGETS=['6861','6954','6981','7741','8035','3436','4519','2802','4776','3092','7730','2815','6565','3649'];
const NAME={'6861':'キーエンス','6954':'ファナック','6981':'村田製作所','7741':'HOYA','8035':'東京エレクトロン','3436':'SUMCO','4519':'中外製薬','2802':'味の素','4776':'サイボウズ','3092':'ZOZO','7730':'マニー','2815':'アリアケ','6565':'ABホテル','3649':'FINDEX'};
// 埋める組合せ: 控えめ(dom50/irr50) / 中位(dom70/irr70) / 強気(dom85/irr85)
const CASES=[['現状',null,null],['控えめ dom50/irr50',50,50],['中位 dom70/irr70',70,70],['強気 dom85/irr85',85,85]];
console.log('銘柄'.padEnd(20)+CASES.map(c=>c[0].padStart(19)).join('')+'   Ω75到達に必要なもの');
for(const t of TARGETS){
  const f=path.join(ROOT,'out',t+'_gate_pack.json');
  if(!fs.existsSync(f))continue;
  const base=JSON.parse(fs.readFileSync(f,'utf8'));
  const out=[];
  for(const [,dom,irr] of CASES){
    const d=JSON.parse(JSON.stringify(base));
    if(dom!==null){ if(d.dom==null)d.dom=dom; if(d.irr==null)d.irr=irr;
      if(d.dur==null)d.dur=55; if(d.moatW==null)d.moatW=50; if(d.rep==null)d.rep=35; }
    let r; try{r=scorePack(d);}catch(e){out.push('  err');continue;}
    const s=parseFloat(r.evalScore)||0;
    out.push(`Ω${s.toFixed(1)}/堀${r.moatNA?'NA':(r.moatIdx||r.moat||'?')}`);
  }
  const roic=base.roic;
  console.log(`${t} ${NAME[t]}`.padEnd(20)+out.map(x=>x.padStart(19)).join('')+`   roic=${roic}`);
}
