#!/usr/bin/env node
/**
 * night/explain_score.js — 門の compute() を走らせて **Ωの分解値** を取り出す（2026-08-03新設）
 *
 * 目的: 「Ωはどう採点されているか」を説明するときに、**架空の数字を使わない**ための道具。
 *   score_all.js と同じ方法で index.html の関数をそのまま読むので、二重実装にならない。
 *
 * 使い方: node night/explain_score.js NVDA IRMD 6146 ...
 *   （銘柄を省略すると投下可の全社）
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const { scorePack, lastCoerce, buyGate } = require('./score_all.js');

const argv = process.argv.slice(2);
let tickers = argv.filter(a => !a.startsWith('--'));
if (!tickers.length) {
  tickers = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/score_all.json'), 'utf8'))
    .filter(r => r.buy).map(r => r.t);
}

const gm = (v, w) => {
  let s = 0, tw = 0;
  v.forEach((x, i) => { s += w[i] * Math.log(Math.max(+x || 0, 1)); tw += w[i]; });
  return Math.exp(s / tw);
};

const dom = id => { const v = parseFloat((global.$(id) || {}).textContent); return isFinite(v) ? v : null; };
const out = [];
for (const t of tickers) {
  const p = path.join(ROOT, 'out', `${t}_gate_pack.json`);
  if (!fs.existsSync(p)) { console.error(`${t}: パック無し`); continue; }
  const d = JSON.parse(fs.readFileSync(p, 'utf8'));
  const r = scorePack(d);
  const coerce = lastCoerce();
  const mg = ccfMoatGate(r, d) || {};
  const x = ccfXJudge(d, parseFloat(r.evalScore)) || {};
  const m = ccfMoat(d) || {};
  // B5(2026-08-04): buy は score_all.js と同じ**四関門**で出す。従来この道具だけ旧・関門のままで、
  //   score_all と逆のことを言えた（v9.9.65違反）。
  // 【2026-08-09 再発していた】v9.9.98でE[r]を合否から外し・v9.9.99で事業の収縮を足し・v9.9.119でirr=85の別枠を
  //   入れ・v9.9.94/95で期末後の重大事象と納品検査FAILを関門にしたのに、**この行だけ3版ぶん取り残されていた**
  //   （実測: WST を score_all は buy=true・この道具は buy=false と出していた）。
  //   → **判定式を書き写さず score_all.js の buyGate() を呼ぶ**。写した時点で必ずまた割れる。
  let audE = 0, audU = 0;
  try {
    const M = d._meta || {};
    for (const w of (ccfAudit(d, r, coerce) || [])) {
      if (w.lv === 'err') audE++;
      else if (w.lv === 'warn' && !((M.evidence || {})[w.k] || (M.nulls || {})[w.k])) audU++;
    }
  } catch (e) {}
  out.push({
    t, nm: d.nm || t, omega: +parseFloat(r.evalScore).toFixed(1), tier: r.tierShort,
    // compute() が返すのは Ω・堀・キル・柱の数だけ。Q/F は内部変数なので観測しない
    //   （**推定値を混ぜない**——出せるのは門が実際に外へ出した値だけ）。
    //   二本柱 pm/pr は門が setp() で pmV/prV へ書き出すので拾える。
    //   sustain は規約どおり gm([pm,pr],[.475,.525]) で復元できる（式は門の頭注が正）。
    moatIdx: m.idx != null ? +m.idx.toFixed(1) : null,
    pm: dom('pmV'), pr: dom('prV'),
    sustain: (dom('pmV') != null && dom('prV') != null)
      ? +gm([dom('pmV'), dom('prV')], [.475, .525]).toFixed(1) : null,
    pfail: r.pfail, kills: r.kills,
    // 堀の5本（生値）
    legs: { dom: d.dom, irr: d.irr, rep: d.rep, dur: d.dur, moatW: d.moatW },
    moatMiss: m.miss, moatNA: m.na,
    // 関門
    xEr: x.xEr != null ? +x.xEr.toFixed(1) : null, xPass: x.xPass,
    moatOK: !!mg.pass, audE, audU, audOK: audE === 0 && audU === 0,
    buy: buyGate(t, d, parseFloat(r.evalScore), mg, audE, audU, r),   // v9.9.122: 別枠は r（二本柱）を要る
    exit: r.exit && r.exit.level,
  });
}
console.log(JSON.stringify(out, null, 1));
