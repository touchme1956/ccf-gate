#!/usr/bin/env node
/**
 * night/shadow_irr_step.js — **irr を1段動かすと今日の台帳で誰がどう動くか**（事前登録 Q4）
 *
 * 目的: 原本を読み直す前に「**読んで意味があるか**」を測る。
 *   CLAUDE.md の `kill_impact.py` が確立した作法——26社ぶんの原本読解が「やっても何も動かない」と
 *   先に判ったので読まずに済んだ——を irr に当てる。
 *
 * ⚠ 影の計測。**パックを一切書き換えない**（メモリ上のコピーの irr だけ差し替えて compute を呼ぶ）。
 *   正本 out/score_all.json も**書かない**。出力は out/shadow_irr_step.json だけ。
 *
 * 判定は門の単一実装を呼ぶ（写さない・v9.9.65 の掟）:
 *   score_all.js の scorePack / buyGate ＋ global の ccfMoatGate / ccfAllocTop / ccfAllocScore。
 *
 * 【なぜ Q4 が最優先か】決定に効いているのは 85 ではなく **70↔50 の境界**である:
 *   ・irr=85 を全部70に落としても投下可は0社しか動かない（night/shadow_irr85.js・2026-08-07）
 *   ・判定圏の70を50に落とすと投下可10社中6社が落ちる（同・当時の名簿）
 *   ⚠ ただしその実測は**当時の投下可10社**に対するもので、**今日の名簿は4社入れ替わっている**
 *     （当時 ASML VRSK CW MSFT IDXX RMD KLAC 6857 HWM IRMD → 今日 ASML CW LRCX RBC MSFT V IDXX RMD KLAC HWM）。
 *     **今日の名簿で測り直すのがこの道具の本題**。
 *
 * 使い方: node night/shadow_irr_step.js [--json]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const S = require('./score_all.js');

const STEPS = [50, 70, 85, 100];
const down = v => { const i = STEPS.indexOf(+v); return i > 0 ? STEPS[i - 1] : null; };
const up = v => { const i = STEPS.indexOf(+v); return i >= 0 && i < STEPS.length - 1 ? STEPS[i + 1] : null; };

// ── パックを読む（**書き換えない**。差し替えは毎回コピーの上で行う）──────────
const PACKS = [];
for (const f of fs.readdirSync(path.join(ROOT, 'out'))) {
  if (!f.endsWith('_gate_pack.json')) continue;
  try {
    const d = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8'));
    PACKS.push({ t: f.split('_gate_pack')[0], d });
  } catch (e) {}
}

/** mutate(t, d) が返した値で irr を差し替えて全社を採点し、門と同じ規則で投下可を決める */
function evaluate(mutate) {
  const rows = [];
  for (const { t, d } of PACKS) {
    const irr = mutate ? mutate(t, d) : undefined;
    const dd = irr === undefined ? d : { ...d, irr };
    let r; try { r = S.scorePack(dd); } catch (e) { continue; }
    const coerce = S.lastCoerce();
    let mg = {}; try { mg = ccfMoatGate(r, dd) || {}; } catch (e) {}
    let audE = 0, audU = 0;
    try {
      const M = d._meta || {};
      for (const w of (ccfAudit(dd, r, coerce) || [])) {
        if (w.lv === 'err') audE++;
        else if (w.lv === 'warn' && !((M.evidence || {})[w.k] || (M.nulls || {})[w.k])) audU++;
      }
    } catch (e) {}
    const s = parseFloat(r.evalScore);
    const row = { t, nm: String(d.nm || t), s, irr: dd.irr,
                  moat: mg.idx == null ? null : +mg.idx.toFixed(1), moatOK: !!mg.pass, moatNA: !!mg.na,
                  quali: S.buyGate(t, dd, s, mg, audE, audU, r) };
    try { row.a = +ccfAllocScore(row).toFixed(2); } catch (e) { row.a = 0; }
    rows.push(row);
  }
  const sel = ccfAllocTop(rows.filter(x => x.quali), 10);
  for (const r of rows) r.buy = r.quali && sel.has(r.t);
  return rows;
}

const base = evaluate(null);
const B = Object.fromEntries(base.map(r => [r.t, r]));
const buySet = base.filter(r => r.buy).map(r => r.t);
const qualiSet = base.filter(r => r.quali).map(r => r.t);

// 正本との照合——**門と端末が同じことを言うか**を先に確かめる（v9.9.65）
let ref = [];
try { ref = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'score_all.json'), 'utf8')); } catch (e) {}
const refBuy = ref.filter(x => x.buy).map(x => x.t).sort();
const okBase = JSON.stringify(refBuy) === JSON.stringify(buySet.slice().sort());

const BAND = 72;                       // 判定圏（CLAUDE.md の既存の線。新しい定数を作らない）
const inBand = t => (B[t] || {}).s >= BAND;

function scenario(name, mutate) {
  const rows = evaluate(mutate);
  const R = Object.fromEntries(rows.map(r => [r.t, r]));
  const nb = rows.filter(r => r.buy).map(r => r.t);
  const nq = rows.filter(r => r.quali).map(r => r.t);
  return {
    name,
    buy_n: nb.length, buy: nb,
    出た: buySet.filter(t => !nb.includes(t)),
    入った: nb.filter(t => !buySet.includes(t)),
    四関門通過の増減: nq.length - qualiSet.length,
    堀の関門を割った社: base.filter(r => r.moatOK && R[r.t] && !R[r.t].moatOK)
      .map(r => ({ t: r.t, 堀: r.moat, 変更後: R[r.t].moat })),
  };
}

const out = {
  generated: new Date().toISOString().slice(0, 10), tool: 'night/shadow_irr_step.js',
  prereg: 'out/irr_precision_prereg.json Q4',
  baseline: { buy: buySet, quali_n: qualiSet.length, 正本と一致: okBase, 正本の投下可: refBuy },
  irr分布: base.reduce((a, r) => { const k = r.irr === '' || r.irr == null ? '未測定' : String(r.irr); a[k] = (a[k] || 0) + 1; return a; }, {}),
  scenarios: [],
};

// ① 判定圏の 70 → 50（既記録「投下可10社中6社が落ちる」を今日の名簿で測り直す）
out.scenarios.push(scenario('判定圏(Ω72+)の irr=70 → 50',
  (t, d) => (inBand(t) && +d.irr === 70) ? 50 : undefined));
// ② 判定圏の 70 → 85
out.scenarios.push(scenario('判定圏の irr=70 → 85',
  (t, d) => (inBand(t) && +d.irr === 70) ? 85 : undefined));
// ③ 50 → 70（全社／判定圏のみ）
out.scenarios.push(scenario('全社の irr=50 → 70', (t, d) => (+d.irr === 50) ? 70 : undefined));
out.scenarios.push(scenario('判定圏の irr=50 → 70',
  (t, d) => (inBand(t) && +d.irr === 50) ? 70 : undefined));
// ④ 未測定を各刻みに置く
for (const v of [50, 70, 85]) {
  out.scenarios.push(scenario(`未測定12社を irr=${v} に置く`,
    (t, d) => (d.irr === '' || d.irr == null) ? v : undefined));
}
// ⑤ 全社の 70 → 50（判定圏に限らない・上限の把握）
out.scenarios.push(scenario('全社の irr=70 → 50', (t, d) => (+d.irr === 70) ? 50 : undefined));

// ── 投下可10社の「余裕」——1社ずつ irr を1段下げる ─────────────────
out.投下可の余裕 = buySet.map(t => {
  const r = B[t];
  const dn = down(r.irr);
  const one = dn == null ? null : evaluate((tt) => tt === t ? dn : undefined);
  const R = one ? Object.fromEntries(one.map(x => [x.t, x])) : {};
  const nb = one ? one.filter(x => x.buy).map(x => x.t) : [];
  return {
    t, nm: r.nm, irr: r.irr, 堀: r.moat, 関門70までの余裕pt: r.moat == null ? null : +(r.moat - 70).toFixed(1),
    一段下げると: dn,
    下げた堀: R[t] ? R[t].moat : null,
    下げても投下可か: dn == null ? null : nb.includes(t),
    押し出された社: dn == null ? null : buySet.filter(x => !nb.includes(x)),
    入れ替わりで入った社: dn == null ? null : nb.filter(x => !buySet.includes(x)),
  };
});

if (process.argv.includes('--json')) { console.log(JSON.stringify(out, null, 1)); return; }

console.log(`■ 基準の照合: 正本 out/score_all.json と ${okBase ? '一致 ✓' : '**不一致 ✗**'}`);
console.log(`  投下可10社: ${buySet.join(' ')}`);
console.log(`  irr分布: ${JSON.stringify(out.irr分布)}`);
console.log('\n■ irr を動かすと投下可はどうなるか');
for (const s of out.scenarios) {
  console.log(`  ${s.name.padEnd(28)} 投下可${String(s.buy_n).padStart(3)}社`
    + `　出:${s.出た.join(',') || '—'}　入:${s.入った.join(',') || '—'}`
    + `　堀の関門を割った:${s.堀の関門を割った社.length}社`);
}
// ★落ちる理由を**二つに分ける**——「堀の関門70を割る」と「席を失う」は別の機構である。
//   混ぜて『7社が落ちる』と書くと、堀が無傷の社まで堀の問題に見える（2026-08-12 に自分で踏んだ）。
{
  const g = out.投下可の余裕.filter(x => x.下げても投下可か === false);
  const byMoat = g.filter(x => x.下げた堀 != null && x.下げた堀 < 70);
  const bySeat = g.filter(x => !(x.下げた堀 != null && x.下げた堀 < 70));
  out.落ちる理由の内訳 = {
    合計: g.length,
    '堀の関門70を割る': byMoat.map(x => `${x.t}(${x.堀}→${x.下げた堀})`),
    '堀は無傷だが席を失う': bySeat.map(x => `${x.t}(${x.堀}→${x.下げた堀}・irr=85の優先を失う)`),
    注: '席の順は irr=85 優先→Ω順なので、85→70 は堀が70以上でも順位を落とす（ccfAllocTop）',
  };
  console.log(`\n■ 落ちる理由の内訳（合計${g.length}社）`);
  console.log(`  堀の関門70を割る      ${byMoat.length}社: ${byMoat.map(x=>x.t).join(' ') || '—'}`);
  console.log(`  堀は無傷だが席を失う  ${bySeat.length}社: ${bySeat.map(x=>x.t).join(' ') || '—'}`);
}
console.log('\n■ 投下可10社の余裕（irr を1段下げたら？）');
console.log(`  ${'銘柄'.padEnd(6)}${'irr'.padStart(5)}${'堀'.padStart(7)}${'関門70まで'.padStart(11)}   1段下げた堀   投下可のまま?`);
for (const x of out.投下可の余裕) {
  console.log(`  ${x.t.padEnd(6)}${String(x.irr).padStart(5)}${String(x.堀).padStart(7)}`
    + `${String(x.関門70までの余裕pt).padStart(9)}pt   `
    + `${x.一段下げると == null ? '  （最下段）' : String(x.下げた堀).padStart(8)}     `
    + `${x.下げても投下可か == null ? '—' : (x.下げても投下可か ? '✓' : '**✗ 落ちる**')}`);
}
fs.writeFileSync(path.join(ROOT, 'out', 'shadow_irr_step.json'), JSON.stringify(out, null, 1));
console.log('\n→ out/shadow_irr_step.json');
