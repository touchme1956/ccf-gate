#!/usr/bin/env node
/**
 * night/audit_weights.js — 採点の**名目の重み**と**実効の重み**の差を実測する（2026-08-03新設）
 *
 * なぜ要るか:
 *   Ω は入れ子の幾何平均なので、「重み .22」と書いてある項が本当に22%効いているとは限らない。
 *   同じ変数が複数の階層に現れると経路が足し算になる（堀は v9.9.36 が**意図して**二経路にした）。
 *   逆に深い階層の項は名目より薄くなる（CLAUDE.md が p1 について
 *   「実効ウェイトは .30×.40×.35≒4.2%」と書いているのがその例）。
 *   **設計の意図と実際の効き方が合っているか**を、推測でなく実測で出すための道具。
 *
 * 測り方:
 *   ルーブリック欄(0-100)を **50 → 90 の40pt** 振って ΔΩ を測る。幾何平均では
 *   d(lnΩ)/d(ln x) がその項の実効ウェイトなので、ΔΩ/40 がほぼそのまま「何%効くか」になる。
 *   キル・上限・クランプ等の非線形も込みで出るのが解析計算との違い。
 *
 * 【初版で踏んだ欠陥3件——測る道具ほど検算が要る】
 *   (1) 列挙欄(dom/irr/rep/dur/moatW)を +5 しても、門の applyFields が**最も近い選択肢へ丸め戻す**
 *       ので何も動かず「効かない」と誤って出た → 刻みの**両端**(50 と 100)で振る
 *   (2) 比率欄(nde)を +5 すると 0.5→5.5 で**キル(>4)を跨ぐ**ため ΔΩ=−8 と桁違いに出た
 *       → 比率欄はルーブリック欄と別表に分け、幅も欄ごとに変える
 *   (3) evalScore は **0.1刻みで丸められる**ので +5 では信号が丸め誤差に埋もれた → 40pt 振る
 *
 * 使い方:
 *   node night/audit_weights.js          全社
 *   node night/audit_weights.js --q75    Ω75+ だけ（判定圏での効き方）
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const { scorePack } = require('./score_all.js');

const q75only = process.argv.includes('--q75');

// 名目の実効ウェイト（門のソースの重みを階層どおり掛けた解析値・**v9.9.67以降の式**）
//   Ω  = gm([Q .35, sustain .30, F .22, moat .13])
//   Q  = gm([P .5333, now .4667])   ← v9.9.67 で F を Q から外した（F二重計上の解消。P:now=40:35 を再正規化）
//   P  = gm([p1 .30, p2 .25, p3 .25, p4 .20])
//   sustain = gm([pm .475, pr .525]) ／ pm = .70*moat + .30*営業利益率（線形）
// 2026-08-04(B6): この表自体が v9.9.67 以前（F二重計上時代の F=.3075 / P=.14）のまま残っていた。
//   「名目 vs 実効」を突き合わせる道具が誤った基準線を出す＝検査器自身の欠陥（v9.9.65の同型）。
const FW = 0.22;                            // F の実効ウェイト（v9.9.67以降は直接項のみ＝名目どおり）
const MW = 0.13 + 0.30 * 0.475 * 0.70;      // 堀の実効ウェイト（直接 + pm経由＝v9.9.36が**意図した**二経路）
const PW = 0.35 * 0.5333;                   // P の実効ウェイト（≈.1867。now は .35×.4667≈.1633）
const NOMINAL = {
  p1: PW * .30, p2: PW * .25, p3: PW * .25, p4: PW * .20,
  f1: FW * .14, f2: FW * .06, f3: FW * .09, f4: FW * .04, f5: FW * .04,
  dom: MW * .25, irr: MW * .25, rep: MW * .20, dur: MW * .12, moatW: MW * .18,
};
const RUBRIC = ['p1', 'p2', 'p3', 'p4', 'f1', 'f2', 'f3', 'f4', 'f5'];
const ENUM5 = ['dom', 'irr', 'rep', 'dur', 'moatW'];   // 刻み 50/70/85/100（rep は 35/60/80/100）
const RATIO = { gm: [10, 40], roic: [10, 40], cagr: [5, 25], nde: [0.5, 2.5] };

const packs = [];
for (const f of fs.readdirSync(path.join(ROOT, 'out'))) {
  if (!f.endsWith('_gate_pack.json')) continue;
  try { packs.push(JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8'))); } catch {}
}
const base = packs.map(d => { try { return parseFloat(scorePack(d).evalScore); } catch { return NaN; } });
const idx = base.map((s, i) => [s, i]).filter(([s]) => isFinite(s) && s > 0 && (!q75only || s >= 75)).map(x => x[1]);
const med = a => { const v = a.slice().sort((x, y) => x - y); return v.length ? v[Math.floor(v.length / 2)] : NaN; };

function swing(k, lo, hi) {
  const dif = [];
  for (const i of idx) {
    const d = packs[i];
    if (d[k] == null || String(d[k]).trim() === '') continue;   // 空欄の社は「この欄を持たない」
    let a, b;
    try {
      a = parseFloat(scorePack({ ...d, [k]: lo }).evalScore);
      b = parseFloat(scorePack({ ...d, [k]: hi }).evalScore);
    } catch { continue; }
    // **対数弾力性**で測る: 幾何平均では d(lnΩ)/d(ln x) がその項の実効ウェイトそのもの。
    //   点差(ΔΩ)で比べると、振り幅の違う欄（列挙50→100 と ルーブリック50→90）を
    //   同じ土俵に載せられない。log で測れば全欄が直接比較できる。
    if (isFinite(a) && isFinite(b) && a > 0 && b > 0)
      dif.push({ e: (Math.log(b) - Math.log(a)) / (Math.log(hi) - Math.log(lo)), d: b - a });
  }
  return { m: med(dif.map(x => x.e)), pt: med(dif.map(x => x.d)), n: dif.length };
}

console.log(`対象 ${idx.length}社${q75only ? '（Ω75+）' : '（全体）'}\n`);
console.log('■ ルーブリック欄（50 → 90 を振る。実効% ＝ 対数弾力性 d(lnΩ)/d(ln x)）');
console.log(`${'欄'.padEnd(7)} ${'ΔΩ'.padStart(7)} ${'実効%'.padStart(7)} ${'名目%'.padStart(7)}  ${'n'.padStart(4)}  判定`);
const seen = [];
for (const k of RUBRIC) {
  const { m, pt, n } = swing(k, 50, 90);
  if (!isFinite(m)) { console.log(`${k.padEnd(7)} ${'—'.padStart(7)}  （この欄を持つ社が無い）`); continue; }
  const eff = m, nom = NOMINAL[k];
  seen.push([k, eff, nom]);
  const r = eff / nom;
  console.log(`${k.padEnd(7)} ${pt.toFixed(2).padStart(7)} ${(eff * 100).toFixed(1).padStart(6)}% ${(nom * 100).toFixed(1).padStart(6)}%  ${String(n).padStart(4)}  `
    + (eff < 0.005 ? '◇ ほぼ効かない' : r > 1.35 ? '▲ 名目より重い' : r < 0.65 ? '▽ 名目より軽い' : '＝ 概ね一致'));
}
console.log('\n■ 堀の5本（列挙欄なので刻みの両端 50 → 100 を振る。実効% は同じ対数弾力性）');
console.log(`${'欄'.padEnd(7)} ${'ΔΩ'.padStart(7)} ${'実効%'.padStart(7)} ${'名目%'.padStart(7)}  ${'n'.padStart(4)}  判定`);
for (const k of ENUM5) {
  const { m, pt, n } = swing(k, 50, 100);
  if (!isFinite(m)) { console.log(`${k.padEnd(7)} ${'—'.padStart(7)}  （この欄を持つ社が無い）`); continue; }
  const eff = m, nom = NOMINAL[k];
  seen.push([k, eff, nom]);
  const r = eff / nom;
  console.log(`${k.padEnd(7)} ${pt.toFixed(2).padStart(7)} ${(eff * 100).toFixed(1).padStart(6)}% ${(nom * 100).toFixed(1).padStart(6)}%  ${String(n).padStart(4)}  `
    + (eff < 0.005 ? '◇ ほぼ効かない' : r > 1.35 ? '▲ 名目より重い' : r < 0.65 ? '▽ 名目より軽い' : '＝ 概ね一致'));
}
console.log('\n■ 機械項目（比率なので欄ごとの現実的な幅で振る。名目重みは定義されていない）');
for (const k of Object.keys(RATIO)) {
  const [lo, hi] = RATIO[k];
  const { m, pt, n } = swing(k, lo, hi);
  if (!isFinite(m)) continue;
  console.log(`${k.padEnd(7)} ${String(lo).padStart(4)} → ${String(hi).padEnd(4)} ΔΩ ${pt.toFixed(2).padStart(7)}  実効 ${(m * 100).toFixed(1).padStart(5)}%   n=${n}`);
}
const sumEff = seen.reduce((a, x) => a + Math.max(0, x[1]), 0);
const sumNom = seen.reduce((a, x) => a + x[2], 0);
console.log(`\n※ ルーブリック9欄＋堀5本の合計: 実効 ${(sumEff * 100).toFixed(0)}% / 名目 ${(sumNom * 100).toFixed(0)}%`);
console.log('  残りは機械項目（ROIC・営業利益率・成長・負債）と now/pr が担う。');
