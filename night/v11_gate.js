#!/usr/bin/env node
/**
 * night/v11_gate.js — **v11「引き算の門」の単一実装**（`V11_SPEC.md`・影）
 *
 * 正本(index.html)は一切変えない。ここは影の判定だけを持ち、今日の全パックへ当てて
 * `out/v11_shadow.json` を書き、**v9 との差分を一社ずつ理由つきで出す**（黙って消さない・v9.9.52）。
 *
 * 【v9 の実装を再利用する（写さない・v9.9.65の掟）】
 *   `require('./score_all.js')` で門のスクリプトが eval され、compute() / ccfShrinkGate /
 *   ccfMoatGate / ccfXJudge / ccfAudit が global に載る。v11 が v9 から**持ち込む**関門
 *   （事業の収縮・データ健全）は、その門の関数をそのまま呼ぶ。
 *   ⇒ 二つの門が「事業の収縮」について違うことを言う経路が原理的に無い。
 *
 * 【v11 が v9 と違う点だけを、ここに書く】
 *   層0: 営業利益率≥10% ∧ 5年FCF全年黒字 ∧ 5年営業利益全年黒字（+ データ健全）
 *   層1: 機構 A(顧客が再認定) / B(摩擦のみ) / C(なし) ← irr 85/70/50 と一対一。**100 は作らない**
 *   層2: dep / erosion / disrupt / 事業の収縮 / **利払カバー≥3**（← nde のキルを置き換える）
 *   層3: E[r] は**記述のみ**。ただし成長を減衰させる（実証5年 → 終端6%×15年）
 *   層4: 順位を作らない（機構Aを先に。同格の中の順は「通り続けている期間」＝**今日の repo に無い**）
 *
 * 使い方: node night/v11_gate.js [--json]
 * 出力  : out/v11_shadow.json
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const S = require('./score_all.js');            // ← 門のスクリプトを載せる（compute 等が global に）

const readJson = f => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); } catch (e) { return null; } };
const FACTS = (readJson('v11_facts.json') || {}).items || {};
const HEALTH = {
  stale: readJson('stale_bs.json'), vfail: readJson('validate_fail.json'), pending: readJson('pending.json'),
};
const hit = (o, t, ok) => { const v = ((o || {}).items || {})[t]; return v && ok(v) ? v : null; };

// ── V11_SPEC の線（**この3つだけがこのファイルの定数**。他はすべて v9 の実装から借りる）──
const OPM_LINE = 10;        // 層0 土俵（歴史の質実証プールと同じ）
const INTCOV_LINE = 3;      // 層2 金利負担（歴史の実測: ≤1 0.14 / 1-3 0.05 / 3-5 0.05 → 3で切る）
const TERM_G = 6;           // 層3 終端成長%（retro_growth_persistence の実測帯 +10年で4-6%）
const TERM_FROM = 5;        // 実証成長を信じる年数
const HOLD = 20;            // 保有年数（v9 と同じ）

/** 層1: 機構。irr 85/70/50 と一対一。**100 は作らない**（3ビンテージとも最下位・dom と二重計上） */
function mech(d) {
  const v = d.irr === '' || d.irr == null ? null : parseInt(d.irr, 10);
  if (v == null || isNaN(v)) return { k: null, why: '機構が未測定（原本の引用が無い）' };
  if (v >= 85) return { k: 'A', why: '顧客の側が再認定・再試験をやり直す' };   // 100 も A に畳む
  if (v >= 70) return { k: 'B', why: '移行に摩擦はあるが費用を払うのは当社側' };
  return { k: 'C', why: '移行障壁なし' };
}

/** 層3: 成長を減衰させた E[r]。**合否にも順位にも使わない**（記述のみ） */
function erDecayed(d, s) {
  let x = {}; try { x = ccfXJudge(d, s) || {}; } catch (e) { return null; }
  if (x.xEr == null || x.g == null) return null;
  const g = x.g / 100, per = x.per, shy = x.shy;
  // 実証成長を TERM_FROM 年 → 以降は終端 TERM_G。20年ぶんを年率へ均す
  const tot = Math.pow(1 + g, TERM_FROM) * Math.pow(1 + TERM_G / 100, HOLD - TERM_FROM);
  const gEff = (Math.pow(tot, 1 / HOLD) - 1) * 100;
  const fair = Math.max(16, Math.min(30, 8 + gEff));   // 終端の倍率は終端の成長に合わせる
  const mult = (Math.pow(Math.min(per, fair) / per, 1 / HOLD) - 1) * 100;
  return { er: +(shy + gEff + mult).toFixed(1), g: +gEff.toFixed(1), er_v9: +x.xEr.toFixed(1) };
}

/** 門の compute() が直前に書いた足切りの一覧を読む（**再実装しない**・v9.9.65 の掟）。
 *  DOM の #killSig は compute() の冒頭で毎回クリアされるので、直前の1社ぶんだけが入っている。 */
function v9Kills() {
  const h = (global.$('killSig').innerHTML || '');
  return [...h.matchAll(/<b>論外：<\/b>([^<]*)</g)].map(m => m[1].trim());
}

/** v11 の判定（**この関数だけが v11 の合否を知っている**） */
function v11Gate(t, d, r, kills) {
  const F = FACTS[t] || {};
  const blockers = [], holes = [];
  const jp = /^\d{4,5}(\s|$|\.)/.test(String(d.nm || t));

  // ── 層0 土俵 ────────────────────────────────────────────
  const opm = F.opm != null ? F.opm : (d.gm === '' || d.gm == null ? null : parseFloat(d.gm));
  if (opm == null) holes.push('営業利益率が測れない');
  else if (opm < OPM_LINE) blockers.push(`層0 営業利益率 ${opm.toFixed(1)}% < ${OPM_LINE}%`);
  for (const [k, lab] of [['op5_all_pos', '5年すべて営業利益黒字'], ['fcf5_all_pos', '5年すべてFCF黒字']]) {
    if (F[k] === false) blockers.push(`層0 ${lab}でない`);
    else if (F[k] == null) holes.push(`${lab}が測れない${jp ? '（日本株＝SEC経路に無い）' : ''}`);
  }
  // データ健全（v9 から持ち込む。採点の話ではなく「パックが会社の現在を描いているか」の話）
  const st = hit(HEALTH.stale, t, v => v.verdict === '要審査');
  const vf = hit(HEALTH.vfail, t, v => (v.n || 0) > 0);
  const pd = hit(HEALTH.pending, t, v => v.verdict !== 'ok');
  if (st) blockers.push(`層0 期末後の重大事象（のれんの${st.newPct}%が新規）`);
  if (vf) blockers.push(`層0 納品検査FAIL ${vf.n}件`);
  if (pd) blockers.push(`層0 未完了の重大事象（${pd.target || pd.kind || '判定不能'}）`);

  // ── 層1 機構 ────────────────────────────────────────────
  const m = mech(d);
  if (m.k == null) holes.push('機構が未測定');
  else if (m.k === 'C') blockers.push('層1 機構C（移行障壁なし）');

  // ── 層2 壊れない ────────────────────────────────────────
  const dep = d.dep === '' || d.dep == null ? null : parseFloat(d.dep);
  if (dep != null && dep >= 40 && d.depGov !== 'yes') blockers.push(`層2 存続級依存 ${dep}%`);
  if (d.erosion === 'active') blockers.push('層2 粗利の侵食が進行中');
  if (d.disrupt === 'threat') blockers.push('層2 破壊の脅威');
  let sh = {}; try { sh = ccfShrinkGate(d) || {}; } catch (e) {}
  if (sh.hit) blockers.push(`層2 事業の収縮（${sh.why}）`);
  // ⚠**2026-08-12 の追補（影を実際に走らせて判った欠陥・結果を見た後の改訂）**——
  //   V11_SPEC の初版は「捨てるもの」に Ω・ルーブリック・堀4本・irr=100・nde のキルを挙げたが、
  //   **v9 の足切り群（債務超過 / Z''<1.1 / ROIC≤WACC / ROIIC³<WACC / 堀の減衰 / 期限型独占）を
  //   どうするか一言も書いていなかった**。書かなければ落ちる＝仕様どおりに実装すると
  //   **Ω26.9(DSGX) や Ω33.7(DLB) を通す**（実測: v9 の投下可に無い社を18社通した）。
  //   v11 はこの群が効かないとは一度も主張していないので、**そのまま持ち込む**のが筋。
  //   ただし `負債/EBITDA>4` だけは v11 が intcov に置き換えるので除外する（二重に数えない）。
  for (const k of (kills || [])) {
    if (k.includes('負債/EBITDA')) continue;          // ← v11 は intcov で裁く
    blockers.push(`層2 足切り（${k.replace(/&gt;/g, '>').replace(/&lt;/g, '<')}）`);
  }
  // 金利負担。**「採れない」と「無い（無借金）」を区別する**——区別しないと無借金の会社を落とす
  //   （歴史パネルの実測: 層2が落とした81社のうち68社が未測定で、恒久毀損は0社だった）
  if (F.intcov != null) {
    if (F.intcov < INTCOV_LINE) blockers.push(`層2 利払カバー ${F.intcov.toFixed(1)} < ${INTCOV_LINE}`);
  } else if (F.intcov_na_reason === 'no_debt') {
    /* 無借金＝痕跡ゼロ。上限の不等式で「金利負担なし」を事実とする（hachimon_fetch.debt_evidence と同じ作法） */
  } else if (F.intcov_na_reason === 'ext_only') {
    holes.push(`利払カバーが歴史と同じ3タグでは採れない（拡張タグでは ${F.intcov_ext}）`);
  } else {
    holes.push(`利払カバーが測れない${jp ? '（日本株＝SEC経路に無い）' : ''}`);
  }
  return { mech: m, opm, blockers, holes, pass: blockers.length === 0 && holes.length === 0 };
}

module.exports = { v11Gate, mech, erDecayed, v9Kills, FACTS };
if (require.main !== module) return;

// ── CLI ──────────────────────────────────────────────────────
const v9 = readJson('score_all.json') || [];
const v9buy = new Set(v9.filter(x => x.buy).map(x => x.t));
const v9quali = new Set(v9.filter(x => x.quali).map(x => x.t));
const rows = [];
for (const f of fs.readdirSync(path.join(ROOT, 'out'))) {
  if (!f.endsWith('_gate_pack.json')) continue;
  let d; try { d = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); } catch { continue; }
  const t = f.split('_gate_pack')[0];
  let r; try { r = S.scorePack(d); } catch (e) { continue; }
  const kills = v9Kills();
  const g = v11Gate(t, d, r, kills);
  const gNoKill = v11Gate(t, d, r, []);   // 追補の前（＝仕様初版）でどうなっていたかを併記する
  const s = parseFloat(r.evalScore);
  rows.push({ t, nm: String(d.nm || t), jp: /^\d{4,5}(\s|$|\.)/.test(String(d.nm || t)),
              mech: g.mech.k, opm: g.opm, intcov: (FACTS[t] || {}).intcov ?? null,
              intcov_na: (FACTS[t] || {}).intcov_na_reason ?? null,
              kills, blockers: g.blockers, holes: g.holes, pass: g.pass,
              pass_specV1: gNoKill.pass,
              er: erDecayed(d, s), s, v9buy: v9buy.has(t), v9quali: v9quali.has(t) });
}
const pass = rows.filter(x => x.pass).sort((a, b) => (a.mech === 'A' ? 0 : 1) - (b.mech === 'A' ? 0 : 1));
const out = {
  generated: new Date().toISOString().slice(0, 10), tool: 'night/v11_gate.js',
  spec: 'V11_SPEC.md（影・正本は v9.9.x のまま不変）',
  seat_order: '未実装——「通り続けている期間」を repo が記録していないため。'
            + '機構Aを先に置くところまでは決まるが、同格の中の順は今日は作れない（設計の未解決点）',
  n: rows.length, n_pass: pass.length,
  amendment_2026_08_12: {
    what: 'v9 の足切り群を層2へ持ち込む（負債/EBITDA>4 だけは intcov が置き換えるので除外）',
    why: '仕様初版が足切り群に一言も触れておらず、書かれていない＝落ちる、で Ω26.9 の社まで通していた',
    honest: '**結果を見た後の改訂**なので、これで通った数字を「当たった」とは呼べない',
    n_pass_specV1: rows.filter(x => x.pass_specV1).length,
    only_specV1: rows.filter(x => x.pass_specV1 && !x.pass).map(x => x.t),
  },
  v11_pass: pass.map(x => x.t), v9_buy: [...v9buy],
  only_v9: [...v9buy].filter(t => !pass.some(x => x.t === t)),
  only_v11: pass.filter(x => !v9buy.has(x.t)).map(x => x.t),
  rows: rows.sort((a, b) => b.s - a.s),
};
fs.writeFileSync(path.join(ROOT, 'out', 'v11_shadow.json'), JSON.stringify(out, null, 1));
if (process.argv.includes('--json')) { console.log(JSON.stringify(out, null, 1)); return; }

const nm = t => (rows.find(x => x.t === t) || {}).nm || t;
console.log(`■ v11 影（V11_SPEC.md）— 全${rows.length}社中 **${pass.length}社**が層0∧1∧2 を通る`);
console.log(`  機構A ${pass.filter(x => x.mech === 'A').length}社 ／ 機構B ${pass.filter(x => x.mech === 'B').length}社`);
console.log(`\n【v9 の投下可10社を v11 で見ると】`);
for (const t of [...v9buy]) {
  const x = rows.find(y => y.t === t) || {};
  const why = x.pass ? '✓ v11 も通す' : [...(x.blockers || []), ...(x.holes || []).map(h => `〔穴〕${h}`)].join('／');
  console.log(`  ${nm(t).split(/\s/)[0].padEnd(6)} 機構${x.mech || '—'}  ${why}`);
}
console.log(`\n【v11 だけが通す社（v9 の投下可に無い）】${out.only_v11.length}社`);
for (const t of out.only_v11) {
  const x = rows.find(y => y.t === t);
  console.log(`  ${x.nm.split(/\s/)[0].padEnd(6)} 機構${x.mech}  Ω${x.s.toFixed(1)}  `
    + `${x.v9quali ? 'v9では🔵次点' : 'v9では四関門で落ちている'}`
    + `${x.er ? `  E[r] v9 ${x.er.er_v9}% → 減衰版 ${x.er.er}%` : ''}`);
}
console.log(`\n【穴（v11 が判定できない社）】`);
const holeCount = {};
for (const x of rows) for (const h of x.holes) holeCount[h] = (holeCount[h] || 0) + 1;
for (const [h, n] of Object.entries(holeCount).sort((a, b) => b[1] - a[1]).slice(0, 8))
  console.log(`  ${String(n).padStart(3)}社  ${h}`);
console.log(`\n→ out/v11_shadow.json　※${out.seat_order}`);
