#!/usr/bin/env node
/**
 * night/audit_monotonic.js — **採点の単調性と崖を実測する**（2026-08-06新設）
 *
 * なぜ要るか:
 *   門の思想は本文にこう書いてある——「白黒にできる死因だけキル、程度問題はすべて坂」。
 *   実装核の `ramp()` は Fritsch-Carlson 単調3次補間で、コメントに
 *   「単調性保証(値↑→スコア↑は絶対)」とまで書いてある。
 *   ところが**その保証は ramp() の中だけの話**で、Ω 全体としては保証されていない。
 *   罰（roicGap −6 / roicg<WACC −8 / gpa<15 −5 / shy>6 −5 / geopol×1.15）は
 *   ramp を通らない**素の if 文**なので、そこに崖が残る。
 *
 *   2026-08-06の全数実測で判ったこと:
 *     ・roic を上げるとΩが下がる社が **181/362社（50%）** ← roicGap>15 の −6 の崖
 *     ・shy を上げるとΩが下がる社が **131社**              ← F10 の >6% で −5 の崖
 *     ・geopol が evalScore>=85 で ×1.15 になる崖のせいで KLAC は f1 を 90→95 に
 *       上げると Ω が 81.4→81.0 と**下がる**（コメントは「崖でなく連続」と宣言している）
 *   いずれも**誰も測っていなかった**ので、何ヶ月も気づかれずに残っていた。
 *
 * 何を測るか:
 *   (A) 単調性違反 — 「良い方向へ動かしたのに Ω が下がる」入力の組
 *   (B) 崖         — 入力を細かく掃いたとき Ω が閾値をまたいで跳ぶ点と、その社数
 *   キル（nde>4・Z''<1.1・spread≤0）の崖は**設計どおり**なので既定では除外する（--with-kills で含める）。
 *
 * 思想:
 *   **採点ロジックには一切触れない。** 読むだけ。直すかどうかは絶対のルール1の領分。
 *
 * 使い方:
 *   node night/audit_monotonic.js              判定圏(Ω72+)で検査
 *   node night/audit_monotonic.js --all        全社
 *   node night/audit_monotonic.js --with-kills キルの崖も出す
 *   node night/audit_monotonic.js --t NVDA     1社だけ詳しく
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const { scorePack } = require('./score_all.js');

const ARGV = process.argv.slice(2);
const ALL = ARGV.includes('--all');
const WITH_KILLS = ARGV.includes('--with-kills');
const ONE = (() => { const i = ARGV.indexOf('--t'); return i >= 0 ? ARGV[i + 1] : null; })();

const S = d => { try { return parseFloat(scorePack(d).evalScore); } catch { return NaN; } };
// キル本数も一緒に返す。キルの発火/解除で跳ぶのは**設計どおり**なので崖から除外するため。
//   閾値を直書きできない罠: ROIC≤WACC の線は WACC が β 依存＝社ごとに違う（実測 roic 8〜11 に散る）。
//   だから「値」でなく「キルが変わったか」で判定する。
const SK = d => {
  // 注: scorePack の kills は**本数（number）**であって配列ではない。
  //     `(r.kills||[]).length` と書くと 1本のとき undefined になり検出が静かに死ぬ（実際に踏んだ）。
  try { const r = scorePack(d); return { s: parseFloat(r.evalScore), k: Number(r.kills) || 0 }; }
  catch { return { s: NaN, k: -1 }; }
};

// 「良い方向」が定義できる欄だけを対象にする（値が大きいほど良い＝昇順で単調であるべき）
const HIGHER_IS_BETTER = {
  roic:  [5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 130],
  gm:    [3, 8, 12, 16, 20, 25, 30, 35, 40, 50],
  cagr:  [0, 3, 5, 8, 12, 15, 20, 25, 30],
  shy:   [0, 1, 2, 3, 4, 5, 6, 7, 8, 10],
  gpa:   [5, 10, 15, 20, 30, 45, 60, 80],
  p1: [50, 65, 80, 90, 95, 100], p2: [50, 75, 90, 95], p4: [50, 65, 80, 90, 100],
  f1: [50, 65, 80, 90, 95, 100], f2: [50, 65, 80, 90, 100],
  f3: [50, 65, 80, 90, 100], f4: [50, 65, 80, 90, 100],
};
// 崖の掃引（連続量のみ・刻みは実務的な精度）
const SWEEP = {
  roic: [5, 130, 0.5], gm: [3, 55, 0.25], cagr: [0, 40, 0.25], roicg: [3, 80, 0.5],
  shy: [0, 12, 0.05], gpa: [5, 90, 0.5], accr: [-30, 30, 0.25], sbc: [0, 15, 0.1],
};
// 設計どおりのキルの崖（既定では除外）
const KILL_ZONES = [
  { f: 'nde', at: 4.0, why: '負債キル(>4)' },
  { f: 'z', at: 1.1, why: '倒産圏キル(<1.1)' },
  { f: 'z', at: 2.6, why: "Z''グレーゾーン −6" },
];

function loadPacks() {
  const rows = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'score_all.json'), 'utf8'));
  const pick = ONE ? rows.filter(r => r.t === ONE) : (ALL ? rows : rows.filter(r => (r.s || 0) >= 72));
  const out = [];
  for (const r of pick) {
    try { out.push({ t: r.t, s: r.s, d: JSON.parse(fs.readFileSync(path.join(ROOT, 'out', `${r.t}_gate_pack.json`), 'utf8')) }); }
    catch { }
  }
  return out;
}

function main() {
  const packs = loadPacks();
  console.log(`■ 採点の単調性・崖の検査　対象 ${packs.length}社${ONE ? `（${ONE}）` : ALL ? '（全社）' : '（判定圏 Ω72+）'}\n`);

  // ── (A) 単調性違反 ─────────────────────────────────
  const viol = {};
  for (const { t, d } of packs) {
    for (const [f, grid] of Object.entries(HIGHER_IS_BETTER)) {
      if (typeof d[f] !== 'number') continue;
      let prev = null, prevX = null, worst = null;
      for (const x of grid) {
        const s = S({ ...d, [f]: x });
        if (!isFinite(s)) { prev = null; continue; }
        if (prev !== null && s < prev - 0.05) {
          const drop = prev - s;
          if (!worst || drop > worst.drop) worst = { drop, from: prevX, to: x, a: prev, b: s };
        }
        prev = s; prevX = x;
      }
      if (worst) (viol[f] = viol[f] || []).push({ t, ...worst });
    }
  }
  console.log('── (A) 単調性違反：その欄を「良く」したのに Ω が下がる ──');
  const vkeys = Object.keys(viol).sort((a, b) => viol[b].length - viol[a].length);
  if (!vkeys.length) console.log('   なし\n');
  for (const f of vkeys) {
    const list = viol[f].sort((a, b) => b.drop - a.drop);
    console.log(`   ${f.padEnd(6)} ${String(list.length).padStart(3)}社 / ${packs.length}社   最大の落差 ${list[0].drop.toFixed(1)}pt`);
    for (const v of list.slice(0, 4))
      console.log(`        ${v.t.padEnd(7)} ${f}=${v.from}→${v.to} で Ω ${v.a.toFixed(1)}→${v.b.toFixed(1)}`);
    if (list.length > 4) console.log(`        …他${list.length - 4}社`);
  }

  // ── (B) 崖 ─────────────────────────────────────────
  console.log('\n── (B) 崖：入力を連続に動かしたとき Ω が 0.5pt 以上跳ぶ点 ──');
  const cliffs = {};
  for (const { t, d } of packs) {
    for (const [f, [lo, hi, st]] of Object.entries(SWEEP)) {
      if (typeof d[f] !== 'number') continue;
      // まず系列を採り、**傾きの中央値**を出す。崖＝「隣の傾きに比べて桁違いに跳ぶ点」。
      //   単純な「0.5pt以上跳んだら崖」だと、roicPt の急な直線区間（roic 5〜8 で 0.5刻みごとに1.1pt）を
      //   崖と誤検出する。坂と崖を分けるのは**絶対量ではなく局所の傾きとの比**。
      const seq = [];
      for (let x = lo; x <= hi; x += st) {
        const { s, k } = SK({ ...d, [f]: x });
        seq.push({ x, s, k });
      }
      // 各刻みの跳び幅
      const dif = [];
      for (let i = 1; i < seq.length; i++) {
        dif[i] = (isFinite(seq[i].s) && isFinite(seq[i - 1].s)) ? Math.abs(seq[i].s - seq[i - 1].s) : null;
      }
      // 局所の傾きと比べる。roic のように**区間で傾きが桁違いに変わる**欄では
      //   系列全体の中央値を基準にすると急な直線区間（roic 5〜8）をまるごと崖と誤検出する。
      //   隣接する刻みの傾きと比べるのが正しい——崖は「隣より突然大きい」ことで定義される。
      for (let i = 1; i < seq.length; i++) {
        const a = seq[i - 1], b = seq[i];
        if (!isFinite(a.s) || !isFinite(b.s)) continue;
        const jump = dif[i];
        if (jump < 0.5) continue;
        const nb = [dif[i - 2], dif[i - 1], dif[i + 1], dif[i + 2]].filter(v => v != null && isFinite(v));
        if (!nb.length) continue;
        const local = Math.max(...nb);
        if (jump < Math.max(0.5, local * 3)) continue;   // 隣の傾きの3倍未満なら「坂」
        // 設計どおりの崖: (a) 明示のキル帯 (b) キル本数が変わった点（ROIC≤WACC等・WACCはβ依存で社ごとに違う）
        const isKill = KILL_ZONES.some(c => c.f === f && Math.abs(a.x - c.at) < st * 1.5) || (a.k !== b.k);
        if (isKill && !WITH_KILLS) continue;
        const xr = Math.round(a.x * 100) / 100;   // 0.1刻みの浮動小数の尾を落とす(2.9000000000000012 対策)
        const key = `${f}@${xr.toFixed(2)}`;
        cliffs[key] = cliffs[key] || { f, x: xr, n: 0, max: 0, ex: '' };
        cliffs[key].n++;
        if (jump > cliffs[key].max) {
          cliffs[key].max = jump;
          cliffs[key].ex = `${t} ${a.s.toFixed(1)}→${b.s.toFixed(1)}`;
        }
      }
    }
  }
  const cl = Object.values(cliffs).filter(c => c.n >= 2).sort((a, b) => b.n - a.n);
  if (!cl.length) console.log('   なし（0.5pt以上の崖は検出されず）');
  for (const c of cl.slice(0, 18))
    console.log(`   ${c.f.padEnd(6)} ≈${String(c.x).padStart(6)}  ${String(c.n).padStart(3)}社が跳ぶ  最大${c.max.toFixed(1)}pt   例 ${c.ex}`);
  if (!WITH_KILLS) console.log('   ※ キルの崖(nde>4・Z<1.1・Z<2.6)は設計どおりなので除外（--with-kills で表示）');

  // ── (C) 飽和の点呼 ────────────────────────────────
  console.log('\n── (C) 飽和：その欄がもう効かなくなっている社 ──');
  const sat = { roicPt: 0, F7: 0, tot: 0 };
  for (const { d } of packs) {
    if (typeof d.roic !== 'number') continue;
    sat.tot++;
    if (d.roic >= 40) sat.roicPt++;
    if (d.roic >= 25) sat.F7++;
  }
  console.log(`   roicPt が96点で頭打ち (roic≥40):     ${sat.roicPt}/${sat.tot}社`);
  console.log(`   F7のROIC項が100点で頭打ち (roic≥25): ${sat.F7}/${sat.tot}社`);
  console.log('   ※ 飽和は欠陥ではない（歴史検証で高ROICの最上段は劣後）。ただし');
  console.log('     「roicの実効ウェイトは36.5%」という自己認識は、飽和帯では成り立たない');

  const totalViol = Object.values(viol).reduce((a, l) => a + l.length, 0);
  console.log(`\n単調性違反 のべ${totalViol}件 / 崖 ${cl.length}箇所`);
  console.log('※ この道具は読むだけで採点に一切触れない（絶対のルール1）');
  return 0;
}

if (require.main === module) process.exit(main());
