#!/usr/bin/env node
/**
 * night/v12_gate.js — v12「機構の門」を全パックに掛ける（影・正本は v9.9.141 のまま不変）
 *
 * 仕様は V12_SPEC.md（**測定を1件も見る前に commit 9fe80eb で固定**）。
 *
 * ■ この器がやらないこと
 *   ・index.html を1バイトも読み書きしない（v12 は合成点を持たないので compute() が要らない）
 *   ・順位を作らない。段4 の席順は「機構等級 → 時価総額」で、**恣意的であることを出力に明記する**
 *   ・価格・E[r] は段3の記録として出すが、合否にも順位にも使わない
 *
 * ■ v9 との比較のために v9 の判定は out/score_all.json から**読むだけ**（再実装しない・v9.9.65）
 *
 * 使い方:
 *   node night/v12_gate.js            要約 + 通過集合 + v9 との差分
 *   node night/v12_gate.js --all      全社の内訳
 *   node night/v12_gate.js --t ASML   1社の内訳
 *   node night/v12_gate.js --json     out/v12_shadow.json を書く
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(ROOT, 'out');

const arg = (k) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const has = (k) => process.argv.includes(k);

function readJson(p, dflt) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return dflt; }
}

// ── 入力（すべて既存の在庫。この器は新しい採取をしない）──────────────────
const packs = fs.readdirSync(OUT).filter(f => f.endsWith('_gate_pack.json'))
  .map(f => readJson(path.join(OUT, f), null)).filter(Boolean);
const scoreAll = readJson(path.join(OUT, 'score_all.json'), []);
const v9 = {};
for (const r of (Array.isArray(scoreAll) ? scoreAll : scoreAll.rows || [])) v9[r.t] = r;
// 利払カバー・5年黒字は v11_facts が既に採ってある（再実装しない）
const factsRaw = readJson(path.join(OUT, 'v11_facts.json'), {});
const facts = factsRaw.items || {};
const dualRaw = readJson(path.join(OUT, 'irr85_dual.json'), {});
const stale = readJson(path.join(OUT, 'stale_bs.json'), {});
const pending = readJson(path.join(OUT, 'pending.json'), {});
const vfail = readJson(path.join(OUT, 'validate_fail.json'), {});

// 二重読みの済み集合（A の特権に要る）
const dualDone = new Set();
for (const k of ['verified', 'rows', 'items']) {
  const v = dualRaw[k];
  if (Array.isArray(v)) for (const r of v) {
    const t = r.ticker || r.t;
    const st = String(r.status || r.state || r.verdict || '');
    if (t && !/未検証|unverified/.test(st)) dualDone.add(t);
  }
}

const tick = (p) => String(p.nm || '?').split(' ')[0];
const num = (v) => {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  if (s === '') return null;
  const x = parseFloat(s);
  return isNaN(x) ? null : x;
};
const setOf = (o, key) => {
  const v = o && (o[key] || o.rows || o.items);
  if (Array.isArray(v)) return new Set(v.map(x => (typeof x === 'string' ? x : (x.t || x.ticker))).filter(Boolean));
  if (v && typeof v === 'object') return new Set(Object.keys(v));
  return new Set();
};
const staleSet = setOf(stale, 'stale');
const pendingSet = setOf(pending, 'items');
const vfailSet = setOf(vfail, 'items');

// ── 段1 機構: irr を3段へ畳む（100 は作らない・V12_SPEC P8）───────────────
function mech(p) {
  const t = tick(p);
  const v = num(p.irr);
  const ev = ((p._meta || {}).evidence || {});
  const quoted = String(ev.irr || '').trim().length > 0;
  if (v === null) return { grade: null, why: 'irr が空欄＝機構を測っていない' };
  if (v >= 85) {
    if (!quoted) return { grade: 'B', why: 'irr≥85 だが引用が無い→Bとして扱う' };
    // 未検証の A は B として扱う（落とさず特権だけ外す）
    if (!dualDone.has(t)) return { grade: 'B', why: 'A だが二重読み未検証→Bとして扱う', wasA: true };
    return { grade: 'A', why: '顧客側が再認定の費用を負う（二重読み済）' };
  }
  if (v >= 70) {
    if (!quoted) return { grade: null, why: 'irr=70 だが引用が無い（v12 は引用必須）' };
    return { grade: 'B', why: '乗り換えに摩擦がある（引用あり）' };
  }
  return { grade: 'C', why: '代替容易' };
}

// ── 段0 土俵 ───────────────────────────────────────────────
function floor0(p) {
  const t = tick(p);
  const f = facts[t] || {};
  const fail = [], na = [];
  const opm = (f.opm !== undefined && f.opm !== null) ? f.opm : num(p.gm);
  if (opm === null) na.push('営業利益率が測れない');
  else if (opm < 10) fail.push(`営業利益率 ${opm.toFixed(1)}%<10`);
  if (f.op5_all_pos === undefined || f.op5_all_pos === null) na.push('5年営業利益がそろわない');
  else if (!f.op5_all_pos) fail.push('5年に営業赤字の年がある');
  if (f.fcf5_all_pos === undefined || f.fcf5_all_pos === null) na.push('5年FCFがそろわない');
  else if (!f.fcf5_all_pos) fail.push('5年にFCF赤字の年がある');
  // データ健全（第四の関門をそのまま引き継ぐ・v9 の判定を読むだけ）
  const r = v9[t] || {};
  if (r.audE) fail.push(`全件点検の要修正 ${r.audE}件`);
  if (r.audU) fail.push(`未解決警告 ${r.audU}件`);
  if (vfailSet.has(t)) fail.push('納品検査FAIL');
  if (staleSet.has(t)) fail.push('期末後の重大事象');
  if (pendingSet.has(t)) fail.push('未完了の重大事象');
  return { fail, na };
}

// ── 段2 拒否 ───────────────────────────────────────────────
const WACC_FALLBACK = 8.93;   // v9 が使っている値（新しい定数を作らない）
// v9 と同じ WACC（index.html:1818-1820 と同式・新しい定数を作らない）
const RFR = 4.68, ERP = 4.45, BETA_DFLT = 1.0;
const waccOf = (p) => { const b = num(p.beta); return RFR + (b === null ? BETA_DFLT : b) * ERP; };

// ★2026-08-13 改訂1（結果を見た後）: rep の線を 60 → 80
//   事前登録済みの OOS 検定（retro_pillars_test）の刻み別中央値が段差の位置を示している——
//     2013: 35=+0.0727 / 60=+0.0909 / **80=+0.1449** / 100=+0.1488
//     2015: 35=+0.0658 / 60=+0.0904 / **80=+0.1288** / 100=+0.1094
//   ＝35→60 の段差は +0.02 しかなく、**跳ぶのは 80**。「困難(60)」は名前ほど効いていない。
//   ⚠これは**結果を見た後の改訂**だが、根拠は結果を見る前に走った検定の出力である。
const REP_LINE = 80;
function veto(p) {
  const t = tick(p);
  const f = facts[t] || {};
  const r = v9[t] || {};
  const out = [], na = [];

  // 事業の収縮
  const cagr = num(p.cagr), gmt = String(p.gmt || '');
  if (cagr !== null && cagr < 0 && gmt === 'down') out.push('事業の収縮（売上縮小∧営業利益率低下）');

  // dep（相手が主権政府なら免除）
  const dep = num(p.dep);
  if (dep !== null && dep >= 40 && String(p.depGov || '') !== 'yes') out.push(`存続級依存 ${dep}%≥40`);

  if (String(p.erosion || '') === 'active') out.push('erosion=active');
  if (String(p.disrupt || '') === 'threat') out.push('disrupt=threat');

  // 利払カバー（nde ではなく intcov・V12_SPEC P5）
  const ic = (f.intcov === undefined || f.intcov === null) ? null : f.intcov;
  if (ic !== null) { if (ic < 3) out.push(`利払カバー ${ic.toFixed(2)}<3`); }
  else if (f.no_debt_evidence) { /* 痕跡ゼロ＝無借金。通過 */ }
  else na.push(`利払カバーが測れない（${(f.intcov_na_reason || f.nulls && f.nulls.intcov || '理由不明')}）`);

  // 債務超過 / Z''
  if (String(p.eq || '') === 'neg') out.push('債務超過');
  const z = num(p.z);
  if (z !== null && z < 1.1) out.push(`Z''=${z}<1.1`);

  // 複利停止 / 買収代金（v9 から引き継ぐ——v11 が引き継ぎ忘れて緩くなった当のもの）
  const roiic = p.roiic, wacc = waccOf(p);
  const ri = num(roiic), ri5 = num(p.roiic5);
  if (String(roiic || '') !== 'na' && ri !== null && ri < wacc) {
    // 5年窓レスキュー（v9 と同じ作法）
    if (!(ri5 !== null && ri5 >= wacc)) out.push(`ROIIC ${ri}<WACC ${wacc}（複利停止）`);
  }
  const roicg = num(p.roicg);
  if (roicg !== null && roicg < wacc) out.push(`roicg ${roicg}<WACC ${wacc.toFixed(2)}（買収代金）`);

  // ★2026-08-13 改訂2（結果を見た後）: v9 のキルの**列挙漏れ**を埋める。
  //   V12_SPEC の段2 は「v9 から引き継ぎ」と書いてあるのに、私が3本を書き落としていた
  //   （ROIC≤WACC / 堀の明確な減衰 / 期限型独占）。**設計の変更ではなく実装の穴**。
  //   index.html:1894 / 1907 / 1909 が正本。
  const roicK = num(p.roicEx) !== null ? num(p.roicEx) : num(p.roic);
  if (roicK !== null && roicK <= wacc) out.push(`ROIC ${roicK}≤WACC ${wacc.toFixed(2)}（価値破壊）`);
  if (String(p.moatdecay || '') === 'yes') out.push('堀の明確な減衰');
  if (String(p.expiry || '') === 'yes') out.push('期限型独占（期限のある独占は独占ではない）');

  return { out, na };
}

// ── 判定 ───────────────────────────────────────────────────
const rows = [];
for (const p of packs) {
  const t = tick(p);
  const r = v9[t] || {};
  const m = mech(p);
  const f0 = floor0(p);
  const rep = num(p.rep);
  const v2 = veto(p);

  const blockers = [];
  if (f0.fail.length) blockers.push(...f0.fail.map(x => `段0 ${x}`));
  if (f0.na.length) blockers.push(...f0.na.map(x => `段0 na:${x}`));
  if (m.grade === null) blockers.push(`段1 ${m.why}`);
  else if (m.grade === 'C') blockers.push('段1 機構C（代替容易）');
  if (rep === null) blockers.push('段1b rep が空欄');
  else if (rep < REP_LINE) blockers.push(`段1b rep ${rep}<${REP_LINE}`);
  if (v2.out.length) blockers.push(...v2.out.map(x => `段2 ${x}`));
  if (v2.na.length) blockers.push(...v2.na.map(x => `段2 na:${x}`));

  rows.push({
    t, nm: p.nm, pass: blockers.length === 0, grade: m.grade, gradeWhy: m.why,
    wasA: !!m.wasA, rep, blockers,
    mcap: num(p.mcap), per: num(p.per),
    v9: { s: r.s, moat: r.moat, buy: !!r.buy, tier: r.tier, exit: r.exit, pfail: r.pfail, kills: r.kills },
  });
}

// ── 段4 席（機構等級 → 時価総額。⚠恣意的であることを明記する）────────────
const SEATS = 10;
const pass = rows.filter(x => x.pass);
pass.sort((a, b) => {
  const g = (x) => (x.grade === 'A' ? 0 : 1);
  return g(a) - g(b) || ((b.mcap || 0) - (a.mcap || 0)) || a.t.localeCompare(b.t);
});
const seats = pass.slice(0, SEATS);

// ── 出力 ───────────────────────────────────────────────────
const v9buy = Object.values(v9).filter(r => r.buy).map(r => r.t).sort();
const v12set = new Set(pass.map(x => x.t));
const seatSet = new Set(seats.map(x => x.t));

console.log('■ v12「機構の門」影の計測（正本は v9.9.141 のまま不変）');
console.log(`  パック ${rows.length}社 ／ 段0-2 をすべて通過 **${pass.length}社** ／ 席 ${seats.length}`);
console.log(`  等級: A ${pass.filter(x => x.grade === 'A').length} ／ B ${pass.filter(x => x.grade === 'B').length}`
  + `（うち二重読み未検証で B へ落とした ${pass.filter(x => x.wasA).length}）`);
console.log();
console.log('── 段4 席（機構等級 → 時価総額）──');
console.log('  ⚠ この順序は**恣意的**。規模は生存を予言するがリターンは予言しない（V12_SPEC P1）');
for (const [i, x] of seats.entries()) {
  console.log(`  ${String(i + 1).padStart(2)}. ${x.t.padEnd(7)} ${x.grade}級  rep${String(x.rep).padStart(4)}`
    + `  時価${x.mcap === null ? '   —' : x.mcap.toFixed(0).padStart(6)}十億`
    + `   v9: Ω${(x.v9.s ?? 0).toFixed(1).padStart(5)} ${x.v9.buy ? '🟢' : '  '} 出口=${x.v9.exit || '—'}`);
}
if (pass.length > SEATS) {
  console.log(`  （席外 ${pass.length - SEATS}社: ${pass.slice(SEATS).map(x => x.t).join(' ')}）`);
}
console.log();

// ── ★条件1: v9 が⛔にしている社で「柱陥落∨キル∨出口s1」を持つ社を通していないか
const bad = pass.filter(x => !x.v9.buy && ((x.v9.pfail || 0) > 0 || (x.v9.kills || 0) > 0 || /^s[123]$/.test(String(x.v9.exit || ''))));
console.log('── ★条件1（緩くないか）——v11 の唯一にして致命の失敗の再発検査 ──');
if (bad.length === 0) {
  console.log('  ✓ v9 が⛔にしている社のうち「柱陥落∨キル∨出口s1」を持つ社を **1社も通していない**');
} else {
  console.log(`  ✗ **${bad.length}社 通してしまっている**（v11 と同じ失敗）:`);
  for (const x of bad) {
    console.log(`     ${x.t.padEnd(7)} Ω${(x.v9.s ?? 0).toFixed(1)} 柱fail${x.v9.pfail} キル${x.v9.kills} 出口=${x.v9.exit}`);
  }
}
console.log();

console.log('── ★条件4（今日の差分を名指しできるか）──');
console.log(`  v9 投下可 ${v9buy.length}社: ${v9buy.join(' ')}`);
console.log(`  v12 席   ${seats.length}社: ${seats.map(x => x.t).join(' ')}`);
const onlyV9 = v9buy.filter(t => !seatSet.has(t));
const onlyV12 = seats.map(x => x.t).filter(t => !v9buy.includes(t));
console.log(`\n  ▸ v9 だけが買う ${onlyV9.length}社——v12 が落とす理由:`);
for (const t of onlyV9) {
  const x = rows.find(r => r.t === t);
  console.log(`     ${t.padEnd(7)} ${x && x.pass ? '（通過しているが席外）' : (x ? x.blockers.join(' ／ ') : '不明')}`);
}
console.log(`\n  ▸ v12 だけが買う ${onlyV12.length}社——v9 が落とす理由:`);
for (const t of onlyV12) {
  const r = v9[t] || {};
  const x = rows.find(z => z.t === t);
  console.log(`     ${t.padEnd(7)} v9: Ω${(r.s ?? 0).toFixed(1)} 堀${r.moat ?? '—'} 柱fail${r.pfail ?? '—'} キル${r.kills ?? '—'}`
    + ` 出口=${r.exit || '—'} ${(r.blockers || []).join('＋') || ''}   v12: ${x.grade}級`);
}
console.log();

// 落ちた理由の分布
const why = {};
for (const x of rows) if (!x.pass) for (const b of x.blockers) {
  const k = b.replace(/\s+[\d.]+.*$/, '').slice(0, 40);
  why[k] = (why[k] || 0) + 1;
}
console.log('── 落ちた理由の分布（社数・重複あり）──');
for (const [k, v] of Object.entries(why).sort((a, b) => b[1] - a[1]).slice(0, 18)) {
  console.log(`  ${String(v).padStart(4)}  ${k}`);
}

if (has('--all') || arg('--t')) {
  const only = arg('--t') ? new Set(arg('--t').split(',').map(s => s.trim().toUpperCase())) : null;
  console.log('\n── 内訳 ──');
  for (const x of rows) {
    if (only && !only.has(x.t.toUpperCase())) continue;
    console.log(`  ${x.pass ? '🟢' : '  '}${x.t.padEnd(8)}${x.grade || '—'}級 rep${x.rep}  ${x.gradeWhy}`);
    if (x.blockers.length) console.log(`      ${x.blockers.join(' ／ ')}`);
  }
}

if (has('--json')) {
  fs.writeFileSync(path.join(OUT, 'v12_shadow.json'), JSON.stringify({
    generated: new Date().toISOString().slice(0, 10),
    tool: 'night/v12_gate.js', spec: 'V12_SPEC.md（事前登録 commit 9fe80eb・影・正本は v9.9.141 のまま不変）',
    seats: SEATS, n: rows.length, n_pass: pass.length,
    seat_order_note: '機構等級 → 時価総額。⚠恣意的（規模は生存を予言するがリターンは予言しない・V12_SPEC P1）',
    v12_seats: seats.map(x => x.t), v12_pass: pass.map(x => x.t), v9_buy: v9buy,
    only_v9: onlyV9, only_v12: onlyV12,
    cond1_leak: bad.map(x => ({ t: x.t, s: x.v9.s, pfail: x.v9.pfail, kills: x.v9.kills, exit: x.v9.exit })),
    cond1_pass: bad.length === 0,
    rows,
  }, null, 1));
  console.log('\n→ out/v12_shadow.json');
}
