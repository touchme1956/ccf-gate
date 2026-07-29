#!/usr/bin/env node
/**
 * night/score_all.js — 門(index.html)の compute() をそのまま走らせて out/ の全パックを採点する検証器
 *
 * 目的: 「基準を変えたら実際に誰がどう動くか」を推測でなく実測で出す。
 *   採点ロジックには一切触れない。DOMだけを差し替えて index.html の中の compute() を呼ぶので、
 *   門が画面で出す点と同じものが出る（＝二重実装を作らない）。
 *
 * 使い方:
 *   node night/score_all.js                 全パックを採点して要約＋out/score_all.json を書く
 *   node night/score_all.js --jp            日本株だけ
 *   node night/score_all.js --us            米国等だけ
 *   node night/score_all.js --set dom=100   全パックの指定欄を上書きして採点（感度分析）
 *     ※--set は欠測分だけでなく**全パック**を上書きする粗い道具。「欠測を埋めたらどうなるか」を
 *       知りたいときは、この結果を答えにしないこと（本来の値が高い社も低い社も一律に化ける）。
 *   node night/score_all.js --only MSFT,6920,NVDA   銘柄を絞る
 *   ※--only / --set の部分実行は out/score_all.partial.json へ書く。**正本 score_all.json は上書きしない**
 *     （部分結果で正本を潰すと、それを読む検査器〔audit_moat / audit_moat_gap / audit_kill_roiic〕が
 *      その数社を全台帳と誤認して静かに嘘をつく。2026-07-29に実際に踏んだ）
 *
 * 妥当性の確認方法: 素の実行で米国のΩ75+に V/ASML/KLAC/NVDA/MSFT/MA/TSM/ADBE/RMD/IDXX 等
 *   保有・監視銘柄が並べば、門の再現ができている。
 *
 * 既知の前提: null は門の applyFields と同じ扱い（INPUT→空欄 / SELECT→既定値）。
 *   ここを間違えると点が大きくズレる（既定値のROIC25やni100が残るため）。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

// ---- 門のHTMLから「select欄とその既定値」「input欄の既定値」を読む ----
const SELECTS = {};
for (const m of HTML.matchAll(/<select[^>]*id="(\w+)"([\s\S]*?)<\/select>/g)) {
  const opts = [...m[2].matchAll(/<option value="([^"]*)"/g)].map(o => o[1]);
  const sel = m[2].match(/<option value="([^"]*)"[^>]*selected/);
  SELECTS[m[1]] = { def: sel ? sel[1] : (opts[0] || ''), opts };
}
const DEFAULTS = {};
for (const m of HTML.matchAll(/<input[^>]*id="(\w+)"[^>]*value="([^"]*)"/g)) {
  if (DEFAULTS[m[1]] === undefined) DEFAULTS[m[1]] = m[2];
}

// ---- 最小限のDOMシム（門のスクリプトを素のnodeで動かすため） ----
const EL = {};
const mkEl = id => ({
  id, tagName: SELECTS[id] ? 'SELECT' : 'INPUT',
  options: SELECTS[id] ? SELECTS[id].opts.map(v => ({ value: v })) : [],
  value: SELECTS[id] ? SELECTS[id].def : (DEFAULTS[id] !== undefined ? DEFAULTS[id] : ''),
  innerHTML: '', textContent: '', className: '', checked: false,
  style: new Proxy({}, { get: () => '', set: () => true }),
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  appendChild() {}, removeChild() {}, setAttribute() {}, getAttribute: () => null,
  addEventListener() {}, removeEventListener() {}, focus() {}, click() {},
  querySelector: () => null, querySelectorAll: () => [],
  getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0 }),
  selectedIndex: 0, dataset: {},
});
global.$ = id => (EL[id] || (EL[id] = mkEl(id)));
global.document = {
  getElementById: id => global.$(id), querySelector: () => null, querySelectorAll: () => [],
  createElement: () => mkEl('tmp'), addEventListener() {}, body: mkEl('body'),
  documentElement: mkEl('html'), cookie: '',
};
global.window = {
  addEventListener() {}, location: { href: '', search: '' },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  setTimeout, clearTimeout, navigator: { clipboard: null },
};
// Node 22 の globalThis.navigator はゲッター専用。代入は例外になるので defineProperty で被せる
try { Object.defineProperty(global, 'navigator', { value: { clipboard: null, userAgent: 'node' }, configurable: true, writable: true }); } catch (e) {}
global.localStorage = {
  _d: {}, getItem(k) { return this._d[k] ?? null; }, setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; }, key(i) { return Object.keys(this._d)[i] ?? null; },
  get length() { return Object.keys(this._d).length; },
};
global.alert = () => {}; global.confirm = () => true; global.prompt = () => null;
global.fetch = () => Promise.reject(new Error('no network'));
global.requestAnimationFrame = fn => fn();

// ---- 門のスクリプトを読み込む ----
const js = [...HTML.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n;\n');
try { (0, eval)(js); } catch (e) { /* 起動時のDOM処理の失敗は無害 */ }
if (typeof compute !== 'function') {
  console.error('compute() を読み込めなかった。index.html の構造が変わった可能性がある');
  process.exit(1);
}

// ---- 門が受け取るキー集合（applyFields のマップが正） ----
const mi = HTML.indexOf('const map={', HTML.indexOf('function applyFields(d)'));
const KEYS = [...HTML.slice(mi + 10, HTML.indexOf('};', mi)).matchAll(/(\w+):'/g)].map(m => m[1]);

/** 門の applyFields と同じ規則でパックを流し込んで採点する */
function scorePack(d) {
  for (const k of KEYS) {
    const e = global.$(k);
    const val = (d[k] !== undefined && d[k] !== null) ? String(d[k]) : '';
    if (e.tagName !== 'SELECT') { e.value = val; continue; }
    const S = SELECTS[k];
    let matched = S && S.opts.includes(val);
    if (matched) e.value = val;
    else if (val !== '' && S) {                      // 数値は最も近い選択肢へ寄せる
      const num = parseFloat(val);
      if (!isNaN(num)) {
        let best = null, bd = Infinity;
        for (const ov of S.opts) {
          const o = parseFloat(ov);
          if (!isNaN(o) && Math.abs(o - num) < bd) { bd = Math.abs(o - num); best = ov; }
        }
        if (best !== null) { e.value = best; matched = true; }
      }
    }
    if (!matched) e.value = S ? S.def : '';          // null・不一致は既定値へ
  }
  return compute();
}
module.exports = { scorePack, KEYS, SELECTS };

if (require.main !== module) return;

// ---- CLI ----
const argv = process.argv.slice(2);
const arg = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
const only = (arg('--only') || '').split(',').filter(Boolean).map(s => s.toUpperCase());
const over = {};
for (const kv of (arg('--set') || '').split(',').filter(Boolean)) {
  const [k, v] = kv.split('=');
  if (k) over[k.trim()] = v === '' || v === undefined ? null : (isNaN(+v) ? v : +v);
}

const rows = [];
for (const f of fs.readdirSync(path.join(ROOT, 'out'))) {
  if (!f.endsWith('_gate_pack.json')) continue;
  let d; try { d = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); } catch { continue; }
  const t = f.split('_gate_pack')[0];
  const nm = String(d.nm || t);
  const jp = /^\d{4,5}(\s|$|\.)/.test(nm);
  if (argv.includes('--jp') && !jp) continue;
  if (argv.includes('--us') && jp) continue;
  if (only.length && !only.includes(t.toUpperCase())) continue;
  const dd = { ...d, ...over };
  let r; try { r = scorePack(dd); } catch (e) { continue; }
  // 門Ωの点だけでは「買えるか」は決まらない。三段関門(Ω75+ ∧ 門X4条件 ∧ 堀75+)を
  // 門と同じ関数(ccfXJudge / ccfMoatGate)で判定する＝二重実装を作らない
  let x = {}, mg = {};
  try { x = ccfXJudge(dd, parseFloat(r.evalScore)) || {}; } catch (e) {}
  try { mg = ccfMoatGate(r, dd) || {}; } catch (e) {}
  const s = parseFloat(r.evalScore);
  rows.push({ t, nm, jp, s, tier: r.tierShort,
              kills: r.kills, pfail: r.pfail, exit: r.exit && r.exit.level,
              moat: mg.idx == null ? null : +mg.idx.toFixed(1), moatNA: !!mg.na, moatOK: !!mg.pass,
              moatMiss: (r.moatMiss && r.moatMiss.length) ? r.moatMiss : undefined,
              xEr: x.xEr == null ? null : +x.xEr.toFixed(1), xPass: x.xPass,
              buy: s >= 75 && x.xPass === true && mg.pass === true });
}
rows.sort((a, b) => b.s - a.s);
// 部分実行(--only / --set)の結果で正本 out/score_all.json を潰さない（2026-07-29）。
// 実害があった: `--only MA,V,...` を打った直後、score_all.json が5件に縮み、
// audit_moat.py / audit_moat_gap.py / audit_kill_roiic.py が**その5件だけを全台帳として**読んだ。
// 採点は正しいのに、それを読む検査器が全員静かに嘘をつく——絶対のルール7(c)「保管された値も毎回検問する」の同型。
const partial = only.length || Object.keys(over).length;
const outFile = partial ? 'score_all.partial.json' : 'score_all.json';
fs.writeFileSync(path.join(ROOT, 'out', outFile), JSON.stringify(rows, null, 1));

const med = a => { const v = a.slice().sort((x, y) => x - y); return v.length ? v[Math.floor(v.length / 2)] : NaN; };
const brief = (lab, g) => {
  if (!g.length) return;
  const s = g.map(x => x.s);
  console.log(`${lab.padEnd(7)} n=${String(g.length).padStart(3)}  中央値 ${med(s).toFixed(1).padStart(5)}`
    + `  Ω80+ ${String(g.filter(x => x.s >= 80).length).padStart(2)}社`
    + `  Ω75+ ${String(g.filter(x => x.s >= 75).length).padStart(3)}社`
    + `  キル ${String(g.filter(x => x.kills).length).padStart(3)}社`);
};
if (Object.keys(over).length) console.log('上書き:', over, '\n');
brief('全体', rows);
brief('日本株', rows.filter(x => x.jp));
brief('米国等', rows.filter(x => !x.jp));
const q75 = rows.filter(x => x.s >= 75);
console.log('\nΩ75+（堀＝絶対MOAT指数／X＝門X4条件／買＝三段関門すべて成立）:');
for (const r of q75) {
  const moat = r.moatNA ? ' NA ' : (r.moat == null ? '  — ' : r.moat.toFixed(0).padStart(3) + ' ');
  console.log(`  ${r.nm.slice(0, 24).padEnd(26)} Ω${r.s.toFixed(1).padStart(5)}  堀${moat}${r.moatOK ? '✓' : '✗'}`
    + `  E[r]${r.xEr == null ? '  na' : r.xEr.toFixed(0).padStart(4) + '%'}${r.xPass ? '✓' : '✗'}`
    + `  ${r.buy ? '🟢投下可' : r.moatOK ? '🟡押し目待ち' : '⛔堀不足'}  出口=${r.exit}`);
}
const buy = rows.filter(x => x.buy);
console.log(`\n三段関門を通過(🟢投下可) ${buy.length}社`
  + `　日本株${buy.filter(x => x.jp).length}／米国等${buy.filter(x => !x.jp).length}`
  + `\n  ${buy.map(x => x.nm.split(/\s/)[0]).join(' ') || '(なし)'}`);
console.log(`⛔堀不足で見送り(Ω75+だが堀が関門に届かない) ${q75.filter(x => !x.moatOK).length}社`);
console.log(`\n→ out/${outFile}（全${rows.length}件・降順）`+ (partial ? '　※部分実行なので正本 score_all.json は書き換えていない' : ''));
