#!/usr/bin/env node
/**
 * night/omega_retro_build.js — 歴史のビンテージで Ω̂（近似Ω）を組む（2026-08-14新設）
 *
 * ■ 何をするか
 *   2013/2015 の読解（堀5本）＋ omega_retro_collect.py の機械値から**合成パック**を作り、
 *   **門の compute() をそのまま呼ぶ**（night/score_all.js の scorePack を import）。
 *   Ω̂ は再実装ではなく、**門の Ω を歴史の入力に当てたもの**＝v9.9.65 の掟に従う。
 *
 * ■ ★再構成できない欄は「全社で同じ値に固定」する
 *   f2/f4/f5・erosion/disrupt/moatdecay/expiry/geopol・acq5・sht・gls は歴史側に無い。
 *   これらは **null（＝門の applyFields の既定＝未測定と同じ扱い）** にする。
 *   全社同値なので**順位に寄与しない**——つまり Ω̂ が測るのは
 *   「**再構成できた部分の重みが正しいか**」であって Ω 全体ではない。
 *   **これは限界であって欠陥ではない。報告で必ず明記する。**
 *
 * ■ ⚠ 基準の一致について（この作業でいちばん危なかった所）
 *   `retro_cohort` の roic_med5 は **gate0 の roic ＝ 営業利益×0.79÷(自己資本+有利子負債)**
 *   ＝**門の roicg** であって門の roic ではない。だから機械値は omega_retro_collect.py が
 *   **門の採取器 build_numbers をそのまま**当てて採り直したものだけを使う。
 *   cohort の値は**結果側（前方ROIC）にしか使わない**。
 *
 * 使い方: node night/omega_retro_build.js
 * 出力:   out/omega_retro_omega_{2013,2015}.json
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

const V = {
  2013: { pil: 'out/retro_moat_pillars_2013.json',
          irr: ['out/retro_moat_2013.json', 'out/retro_moat_2013q.json'],
          mach: 'out/omega_retro_machine_2013.json' },
  2015: { pil: 'out/retro_moat_pillars_2015.json',
          irr: ['out/retro_moat_2015.json', 'out/retro_moat_2015q.json', 'out/retro_moat_2015qb.json'],
          mach: 'out/omega_retro_machine_2015.json' },
};

for (const yr of Object.keys(V)) {
  const v = V[yr];
  if (!fs.existsSync(path.join(ROOT, v.mach))) {
    console.log(`  ${yr}: ${v.mach} が無い（先に python3 night/omega_retro_collect.py）`); continue;
  }
  const P = Object.fromEntries(load(v.pil).map(x => [K(x), x]));
  const irr = {};
  for (const f of v.irr) for (const x of load(f)) if (x.irr != null) irr[K(x)] = x.irr;
  const M = JSON.parse(fs.readFileSync(path.join(ROOT, v.mach), 'utf8')).items || {};

  const out = {};
  let nLegs = 0, nMach = 0;
  for (const [t, p] of Object.entries(P)) {
    const legs = { dom: p.dom, irr: irr[t], rep: p.rep, dur: p.dur, moatW: p.moatW };
    const nl = Object.values(legs).filter(x => x != null).length;
    if (nl < 4) continue;                      // 門の堀指数の下限
    nLegs++;
    const m = M[t]; if (!m) continue;
    nMach++;
    // ★合成パック。**再構成できない欄は入れない＝null＝門の既定（未測定）**
    const d = { nm: t, ...legs,
      roic: m.roic, roicg: m.roicg, roicEx: m.roicEx, nde: m.nde,
      roiic: m.roiic, roiic5: m.roiic5, gm: m.gm, cagr: m.cagr, accr: m.accr,
      fcf: m.fcf, ni: m.ni, dilNet: m.dilNet, sbc: m.sbc, z: m.z, gpa: m.gpa,
      intcov: m.intcov, eq: m.eq, acc: m.acc };
    const r = scorePack(d);
    out[t] = { omega: r.evalScore, moat: r.moatIdx, pm: r.pm, pr: r.pr,
               pfail: r.pfail, kills: (r.kills || []).length,
               legs, n_legs: nl,
               has: { roic: m.roic != null, roicg: m.roicg != null, nde: m.nde != null,
                      roiic: m.roiic != null, gm: m.gm != null, cagr: m.cagr != null } };
  }
  const p = path.join(ROOT, 'out', `omega_retro_omega_${yr}.json`);
  fs.writeFileSync(p, JSON.stringify({
    generated: new Date().toISOString().slice(0, 10), vintage: +yr,
    note: '門の compute() をそのまま歴史の入力に当てた Ω̂。再構成できない欄（f2/f4/f5・erosion/disrupt/'
        + 'moatdecay/expiry/geopol・acq5・sht・gls）は全社 null で固定＝順位に寄与しない。'
        + 'Ω̂ は Ω ではない——測っているのは「再構成できた部分の重みが正しいか」だけ。',
    n_moat_ok: nLegs, n: Object.keys(out).length, items: out,
  }, null, 1));
  const withRoic = Object.values(out).filter(x => x.has.roic).length;
  console.log(`■ ${yr}: 堀4本以上 ${nLegs}社 → 機械値あり ${nMach}社 → Ω̂ ${Object.keys(out).length}社`
            + `（うち門式roicあり ${withRoic}社）  → ${path.relative(ROOT, p)}`);
}
