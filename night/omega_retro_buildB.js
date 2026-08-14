#!/usr/bin/env node
/**
 * night/omega_retro_buildB.js — 案B: Ω のうち**完全に再構成できる部分だけ**を組む（2026-08-14新設）
 *
 * ■ なぜ B か（A案の Ω̂ が壊れた記録は out/omega_retro_prereg.json の AMENDMENT）
 *   判断項目(p1-p4/f1-f5)を空欄にすると Ω は 30.5、埋めると 76.9＝**46pt の差**。
 *   空欄は中立ではなく**潰し**で、真のΩが46未満の社が全部0へ潰れて同値の塊になる
 *   （2013 は 87/174社が Ω̂<1 ＝上半分/下半分に割る線が塊の中に落ちる）。
 *   だから **Ω 全体ではなく、欠測に汚されていない部分だけ**を検定する。
 *
 * ■ ★Ω_B の定義（新しい定数を一つも作っていない）
 *      Ω_B = gm([sustain, moat], [.30, .13] を .43 で正規化)
 *   ・sustain (.30) = gm([pm, pr], [.475,.525])  — pm は堀から / pr は roic から。**両方とも再構成済み**
 *   ・moat    (.13) = moatIdx                    — 堀5本とも読解済み
 *   重みは**門の .30/.13 をそのまま**使い、合計が1になるよう割るだけ。
 *
 * ■ ★除外した部分と理由（結果を見る前に固定する）
 *   ・Q(.35): 中の `now` が priceConfirm＝**per（価格）**を含み、歴史側に無い
 *   ・F(.22): f2(TAM)/f4(隣接)/f5(disrupt由来) が読解されていない
 *   ＝ Ω_B が覆うのは**Ωの名目重みの43%**。**これは Ω ではない。** 報告で必ずそう書く。
 *
 * ■ 値の取り方（再実装しない・v9.9.65）
 *   moatIdx は compute() の返り値。pm/pr は門が setp() で `pmV`/`prV` へ書き出すのを拾う
 *   （night/explain_score.js と同じ経路）。sustain の合成式だけは門の頭注が正＝そこに従う。
 *
 * 使い方: node night/omega_retro_buildB.js
 * 出力:   out/omega_retro_B_{2013,2015}.json
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const { scorePack } = require('./score_all.js');

const load = f => {
  const d = JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));
  const r = d.items || d.rows || d;
  return Array.isArray(r) ? r : Object.entries(r).map(([k, v]) => ({ ticker: k, ...v }));
};
const K = x => x.ticker || x.t;
const num = v => { const x = parseFloat(v); return isFinite(x) ? x : null; };
const domv = id => { const e = global.$ && global.$(id); return e ? num(e.textContent || e.value) : null; };
/** 門の頭注が正: sustain = gm([pm,pr],[.475,.525]) */
const gm2 = (a, b, wa, wb) => Math.exp(wa * Math.log(Math.max(a, 1)) + wb * Math.log(Math.max(b, 1)));

const V = {
  2013: { pil: 'out/retro_moat_pillars_2013.json',
          irr: ['out/retro_moat_2013.json', 'out/retro_moat_2013q.json'],
          mach: 'out/omega_retro_machine_2013.json' },
  2015: { pil: 'out/retro_moat_pillars_2015.json',
          irr: ['out/retro_moat_2015.json', 'out/retro_moat_2015q.json', 'out/retro_moat_2015qb.json'],
          mach: 'out/omega_retro_machine_2015.json' },
};
const W_SUS = 0.30, W_MOAT = 0.13, SW = W_SUS + W_MOAT;   // 門の重みそのもの

for (const yr of Object.keys(V)) {
  const v = V[yr];
  const P = Object.fromEntries(load(v.pil).map(x => [K(x), x]));
  const irr = {};
  for (const f of v.irr) for (const x of load(f)) if (x.irr != null) irr[K(x)] = x.irr;
  const M = JSON.parse(fs.readFileSync(path.join(ROOT, v.mach), 'utf8')).items || {};

  const out = {}; let nl4 = 0, nNoPill = 0;
  for (const [t, p] of Object.entries(P)) {
    const legs = { dom: p.dom, irr: irr[t], rep: p.rep, dur: p.dur, moatW: p.moatW };
    if (Object.values(legs).filter(x => x != null).length < 4) continue;
    nl4++;
    const m = M[t]; if (!m) continue;
    const d = { nm: t, ...legs, roic: m.roic, roicg: m.roicg, roicEx: m.roicEx, nde: m.nde,
      roiic: m.roiic, roiic5: m.roiic5, gm: m.gm, cagr: m.cagr, accr: m.accr,
      fcf: m.fcf, ni: m.ni, dilNet: m.dilNet, sbc: m.sbc, z: m.z, gpa: m.gpa,
      intcov: m.intcov, eq: m.eq, acc: m.acc };
    const r = scorePack(d);
    const pm = domv('pmV'), pr = domv('prV'), moat = r.moatIdx;
    if (pm == null || pr == null || moat == null || r.moatNA) { nNoPill++; continue; }
    const sustain = gm2(pm, pr, 0.475, 0.525);
    const omegaB = gm2(sustain, moat, W_SUS / SW, W_MOAT / SW);
    out[t] = { omegaB: +omegaB.toFixed(2), sustain: +sustain.toFixed(2),
               moat: +moat.toFixed(2), pm, pr, roic: m.roic, legs };
  }
  const p = path.join(ROOT, 'out', `omega_retro_B_${yr}.json`);
  fs.writeFileSync(p, JSON.stringify({
    generated: new Date().toISOString().slice(0, 10), vintage: +yr,
    definition: 'Ω_B = gm([sustain, moat], [.30,.13]/.43)。門の重みをそのまま使い正規化しただけ。'
              + '**Ω ではない**——Q(.35: now が価格を含む) と F(.22: f2/f4/f5 が歴史側に無い) を除いた43%。',
    weights: { sustain: W_SUS, moat: W_MOAT, sum: SW },
    n_moat_ok: nl4, n_dropped_no_pillar: nNoPill, n: Object.keys(out).length, items: out,
  }, null, 1));
  console.log(`■ ${yr}: 堀4本以上 ${nl4}社 → Ω_B ${Object.keys(out).length}社（柱が取れず落ちた ${nNoPill}社） → ${path.relative(ROOT, p)}`);
}
