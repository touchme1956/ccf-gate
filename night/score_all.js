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
 *   ※--only / --set / --jp / --us の部分実行は out/score_all.partial.json へ書く。**正本 score_all.json は上書きしない**
 *     （部分結果で正本を潰すと、それを読む検査器〔audit_moat / audit_moat_gap / audit_kill_roiic〕が
 *      その数社を全台帳と誤認して静かに嘘をつく。2026-07-29に--onlyで実際に踏み、
 *      2026-08-04の監査(A5)で --jp/--us も同じ穴だと判った——shadow_jp_us_roic.py が毎回踏んでいた）
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
// B23(2026-08-04): compute だけでなく関門3関数も存在検問する。従来は呼び出し側の try/catch が
//   関数消失を黙って飲み、**ccfAudit が消えると audE=0＝audOK=true＝第四の関門が静かに無効化**する
//   方向に壊れた（「鳴らない警報は鳴りすぎる警報と同じ」）。抽出に失敗したら大声で止まる。
for (const fn of ['ccfXJudge', 'ccfMoatGate', 'ccfAudit', 'ccfAllocTop', 'ccfShrinkGate', 'ccfIrr85Frame']) {
  if (typeof global[fn] !== 'function' && typeof globalThis[fn] !== 'function') {
    console.error(`${fn}() を読み込めなかった。index.html の構造が変わった可能性がある——`
      + '関門の関数が無いまま続けると「点検が通った」という偽の結果を作るので中断する');
    process.exit(1);
  }
}

// ---- 門が受け取るキー集合（applyFields のマップが正） ----
const mi = HTML.indexOf('const map={', HTML.indexOf('function applyFields(d)'));
const KEYS = mi < 0 ? [] : [...HTML.slice(mi + 10, HTML.indexOf('};', mi)).matchAll(/(\w+):'/g)].map(m => m[1]);
if (!KEYS.length) {
  // B23(2026-08-04): 抽出が空のまま続けると**全パックが既定値で採点される**（値は出るのに全部誤り
  //   ＝一番静かな壊れ方）。validate_jp_packs.py の gate_keys() と同じく、抽出失敗は大声で止まる。
  console.error('applyFields のマップ(const map={...})を index.html から抽出できなかった。'
    + '門の構造が変わっている——このまま続けると全パックが既定値で採点されるので中断する');
  process.exit(1);
}

// B4(2026-08-04): 門の applyFields は「黙って化けた」欄を __coerce に記録して ccfAudit へ渡す
//   （v9.9.54＝acq5=2.8 が 'yes' に化けて罰が黙って効いた発生点の痕跡）。端末側の再実装は
//   これを記録せず常に [] を渡していたため、**err①「取込で化けた」が端末で構造的に0件**＝
//   （当時の呼称で）四段関門の第四が端末側で半分無効だった。門と同じ規則で記録し、同じ台帳を見る二つの検査器が
//   違うことを言わないようにする（v9.9.65の教訓）。
let __coerce = [];
const lastCoerce = () => __coerce.slice();

/** 門の applyFields と同じ規則でパックを流し込んで採点する */
function scorePack(d) {
  __coerce = [];
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
        if (best !== null) { e.value = best; matched = true; __coerce.push({ k, from: val, to: best, how: '近い選択肢へ寄せた' }); }
      }
    }
    if (!matched) {                                  // null・不一致は既定値へ（門の v9.9.54 と同じく痕跡を残す）
      if (val !== '' && S) __coerce.push({ k, from: val, to: S.def, how: '選択肢に無い→既定値へ化けた' });
      e.value = S ? S.def : '';
    }
  }
  return compute();
}
module.exports = { scorePack, lastCoerce, KEYS, SELECTS };

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

// ── 期末後の重大事象で貸借対照表が古いパック（v9.9.94・2026-08-06新設）─────────
//   night/audit_stale_bs.py が出す作業リストを読み、**第四の関門(点検)の一部として買付を止める**。
//   なぜ点検の側に置くか: これは「Ωが低い」でも「堀が薄い」でもなく、
//   **台帳の値が会社の現在を描いていない**というデータ健全性の問題だから——
//   v9.9.66 が「取込で化けた/内部矛盾/不可能値を持つ銘柄は Ω がどれだけ高くても買わない」と
//   決めたのとまったく同じ理由。**買わない理由であって売る理由ではない**（Ω・売却規律は不変）。
//   【発端】2026-08-06、roicGapの崖を段階減点にした帰結でAPHが投下可へ入り資産の6.3%を受けたが、
//   パックのreportDateは2025-12-31で、CommScope買収(約105億$・同社史上最大)の完了は**その9日後**。
//   のれんは10,575→17,555百万$(+66%)、のれん＋無形は自己資本の96%→147%へ。
//   既存の鮮度検査は reportDate と auditDate の「年」しか見ないので**同じ年のこれは素通り**だった。
//   ファイルが無ければ空＝検査は眠るだけ（無いことを「異常なし」と偽らない・絶対のルール7）。
let STALE = {};
try {
  const sp = path.join(ROOT, 'out', 'stale_bs.json');
  if (fs.existsSync(sp)) {
    const j = JSON.parse(fs.readFileSync(sp, 'utf8'));
    for (const [k, v] of Object.entries(j.items || {})) if (v && v.verdict === '要審査') STALE[k] = v;
  }
} catch (e) {}

// ── 納品検査(validate_packs)のFAILも第四の関門に入れる（v9.9.95・2026-08-07 ユーザー指示「いるとおもうなら入れて」）
//   【なぜ入れるか】FAILの運用単位が「投下可10社」だったので、10番目の席が動くたびに
//   **投下可の厳しさで監査されたことのないパックが席に着いてから初めて検査される**という
//   順序になっていた。2026-08-06 だけで6回連続（ECL→ISRG→IDXX→APH→CDNS→MCO）、
//   うち2社は誤値そのものが出て脱落した（ISRG roic 19.6→12.8 ／ CDNS f1=80 が根拠ゼロ→55）。
//   関門にすれば**根拠に穴のあるパックは構造的に席に着けない**＝不意打ちが原理的に消える。
//   【なぜ今日入れてよいか】投下可10社のFAILは**ゼロ**なので今日は誰も落ちない＝純粋なラチェット。
//   落ちるなら規則の追加ではなく現状の是正が先、という順序を守れている。
//   【第五の関門と呼ばない】これは「値が壊れている／根拠が無い」というデータ健全性の検査で、
//   第四の関門（点検・期末後の重大事象）とまったく同じ種類。**当時は「四段関門」の呼称を変えなかった**
//   ——名前を増やすと本文16箇所の書き換えが要り、この repo が繰り返している
//   「規則を変えたら文も全部grepで洗う」の取りこぼしを自分で作ることになる、と判断したため。
//   ※**v9.9.98（2026-08-07）で門X遮断器を関門から外したので呼称は「四関門」になった**
//     （Ω75+ ∧ 堀70+ ∧ データ健全）。そのときは本文41箇所を実際にgrepで洗った。
//   **買わない理由であって売る理由ではない**（Ω・堀・売却規律S1/S2/S3はいずれも不変）。
let VFAIL = {};
try {
  const vp = path.join(ROOT, 'out', 'validate_fail.json');
  if (fs.existsSync(vp)) {
    const j = JSON.parse(fs.readFileSync(vp, 'utf8'));
    for (const [k, v] of Object.entries(j.items || {})) if (v && (v.n || 0) > 0) VFAIL[k] = v;
  }
} catch (e) {}

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
  const coerce = lastCoerce();   // B4: 門の applyFields が記録する「黙って化けた」欄（ccfAudit の err① の材料）
  // 門Ωの点だけでは「買えるか」は決まらない。四関門(Ω75+ ∧ 堀70+ ∧ データ健全 ∧ 事業の収縮なし)＝v9.9.100時点を
  // 門と同じ関数(ccfXJudge / ccfMoatGate)で判定する＝二重実装を作らない
  let x = {}, mg = {};
  try { x = ccfXJudge(dd, parseFloat(r.evalScore)) || {}; } catch (e) {}
  try { mg = ccfMoatGate(r, dd) || {}; } catch (e) {}
  // 第四の関門(v9.9.66・2026-08-03 ユーザー明示指示): 点検が鳴っている社は買付の土俵から降ろす。
  //   門(ブラウザ)は `_meta` を持てないので **要修正(err)** でしか切れないが、
  //   ここは _meta を読めるので **未解決warn**（evidence も nulls も無い warn）まで切る。
  //   実測(2026-08-03): errは全317社で0件、未解決warnは187件。Ω75+では未解決0件＝投下可7社は不変だが、
  //   この日の是正**前**なら IRMD/NVDA/TSM/ADBE/APH の5社が落ちていた（acq5空欄・根拠なきp3・roic乖離）。
  let audE = 0, audU = 0;
  try {
    const M = d._meta || {};
    for (const w of (ccfAudit(dd, r, coerce) || [])) {
      if (w.lv === 'err') audE++;
      else if (w.lv === 'warn' && !((M.evidence || {})[w.k] || (M.nulls || {})[w.k])) audU++;
    }
  } catch (e) {}
  const shrink = ccfShrinkGate(dd);   // v9.9.99: 門の単一実装（再実装しない・v9.9.65の掟）
  const f85 = ccfIrr85Frame(dd);      // v9.9.119: irr=85 の別枠（同上・門と同一実装）
  const s = parseFloat(r.evalScore);
  rows.push({ t, nm, jp, s, tier: r.tierShort,
              kills: r.kills, pfail: r.pfail, exit: r.exit && r.exit.level,
              moat: mg.idx == null ? null : +mg.idx.toFixed(1), moatNA: !!mg.na, moatOK: !!mg.pass,
              moatMiss: (r.moatMiss && r.moatMiss.length) ? r.moatMiss : undefined,
              xEr: x.xEr == null ? null : +x.xEr.toFixed(1), xPass: x.xPass,
              audE, audU, audOK: audE === 0 && audU === 0,
              staleBS: STALE[t] ? STALE[t].newPct : undefined,
              vFail: VFAIL[t] ? VFAIL[t].n : undefined,
              // v9.9.98(2026-08-07 ユーザー明示指示): **門X遮断器 E[r]≥0 を関門から外した**。
              // 四関門＝Ω75+ ∧ 堀70+ ∧ データ健全（点検err・未解決warn・期末後・納品検査）。
              // 門(index.html)の pass=q75c と同一規則（v9.9.65の掟）
              shrink: shrink.hit ? shrink.why : undefined,
              irr: dd.irr,   // v9.9.100: 席の選定で irr=85 を優先するため（門の ccfAllocTop が読む）
              // v9.9.99(2026-08-07 ユーザー明示指示): **事業の収縮の遮断器**を第四の関門に。
              //   売上縮小 ∧ 営業利益率低下（門の単一実装 ccfShrinkGate を呼ぶ＝再実装しない）
              // v9.9.119(2026-08-09 ユーザー明示指示「2いれて」): **irr=85 の別枠**。
              //   irr=85 ∧ 歴史の継続組の下限（営利率11.9 / FCF転換0.64 / cagr1.8）∧ nde≤4 なら
              //   Ω75+ を免除する。免除するのはΩの線だけで、堀・データ健全・収縮はそのまま。
              //   根拠の全文は index.html の ccfIrr85Frame 頭注（門と同一実装＝v9.9.65の掟）
              frame85: f85.pass ? (f85.why || true) : undefined,
              buy: (s >= 75 || f85.pass) && mg.pass === true && audE === 0 && audU === 0
                   && !STALE[t] && !VFAIL[t] && !shrink.hit });
}
rows.sort((a, b) => b.s - a.s);
// v9.9.88(2026-08-05 ユーザー明示指示「上位10社を買い付け可にして」): 第五の枠。
//   投下可＝四関門∧席順上位10社（v9.9.98でE[r]項を外し・v9.9.100でirr=85を先頭へ）。判定は門の ccfAllocTop（単一実装＝Ⅵ・盤・snapと同一・v9.9.65の掟）。
//   四段通過だが11位以下は quali=true / buy=false ＝🔵次点（買わないが資格は保持）。
let ALLOC_CAPPED = [], ALLOC_CAPN = 0;
{
  const four = rows.filter(r => r.buy);
  const sel = ccfAllocTop(four, 10);
  ALLOC_CAPPED = sel.capped || []; ALLOC_CAPN = sel.capN || 0;
  for (const r of rows) { r.quali = r.buy; if (r.buy) r.buy = sel.has(r.t); }
  // 合成点を**出力にも載せる**（2026-08-07）。下流の道具（audit_promotion_ready 等）が
  // 式を書き写すと v9.9.65 の「同じ台帳を見る二つの検査器が違うことを言う」になる。
  // 門の単一実装 ccfAllocScore の値をそのまま配る。
  for (const r of rows) r.a = +ccfAllocScore(r).toFixed(2);
}
// 部分実行(--only / --set / --jp / --us)の結果で正本 out/score_all.json を潰さない（2026-07-29）。
// 実害があった: `--only MA,V,...` を打った直後、score_all.json が5件に縮み、
// audit_moat.py / audit_moat_gap.py / audit_kill_roiic.py が**その5件だけを全台帳として**読んだ。
// 採点は正しいのに、それを読む検査器が全員静かに嘘をつく——絶対のルール7(c)「保管された値も毎回検問する」の同型。
// 2026-08-04(A5): 当初のガードは --only/--set しか見ておらず、**--jp/--us が同じ穴のまま**だった
//   （shadow_jp_us_roic.py が --jp を毎回踏み、正本が約40行に縮んだまま残った）。行を絞る旗は全部 partial。
const partial = only.length || Object.keys(over).length || argv.includes('--jp') || argv.includes('--us');
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
// 落ちた理由は**全部**出す（v9.9.52「城の行が理由不明で出ない」の教訓）。
//   一つだけ出すと、二つ以上の関門に落ちている社で**残りが見えなくなる**——
//   実測 6920 は E[r]−22% と納品検査FAIL の両方だが、単一表示では後者しか出ず
//   「根拠さえ埋めれば買える」と読めてしまう（実際は遮断器で止まっている）。
const blockers = r => {
  const b = [];
  if (!r.moatOK) b.push('⛔堀不足');
  // v9.9.97: xPass===null（per未取得でE[r]を算出していない）を『押し目待ち』と呼ばない。
  //   価格が高いのではなく価格が入っていない＝直し方が原本読解でなく market_fetch。門のⅥと同じ分け方。
  // v9.9.98: E[r]は合否に効かなくなったので blockers から外した。
  //   E[r]の値そのものは一行表示に出ており、負なら数字で判る（情報として残す・v9.9.52）
  if (!r.audOK) b.push('⛔点検要修正');
  if (r.shrink) b.push('⛔事業の収縮');
  if (r.staleBS != null) b.push('⛔期末後の重大事象');
  if (r.vFail) b.push(`⛔納品検査FAIL${r.vFail}`);
  return b.length ? b : ['—'];
};
// v9.9.119: irr=85 の別枠で土俵に上がった社（Ω75未満）も**この表に出す**——
//   出さないと「なぜΩ63.9の社が🟢に居るのか」が端末から追えず、門と端末が違うことを言う（v9.9.65）
const q75 = rows.filter(x => x.s >= 75 || x.frame85).sort((a, b) => b.s - a.s);
console.log('\nΩ75+（堀＝絶対MOAT指数／E[r]＝参考値・合否に不使用／点＝全件点検／買＝四関門すべて成立・v9.9.98）'
  + '\n  ※【別枠85】＝irr=85 の別枠でΩ75+を免除して土俵に上がった社（v9.9.119）:');
for (const r of q75) {
  const moat = r.moatNA ? ' NA ' : (r.moat == null ? '  — ' : r.moat.toFixed(0).padStart(3) + ' ');
  const aud = r.audOK ? '  ✓' : `${r.audE ? '要' + r.audE : ''}${r.audU ? '未' + r.audU : ''}`.padStart(3) + '✗';
  console.log(`  ${(r.nm.slice(0, 24) + (r.frame85 && r.s < 75 ? '【別枠85】' : '')).padEnd(26)} Ω${r.s.toFixed(1).padStart(5)}  堀${moat}${r.moatOK ? '✓' : '✗'}`
    // v9.9.100: E[r] の ✓/✗ を外した——v9.9.98 で E[r] は合否に効かなくなったのに、
    //   ✓/✗ が残っていると『これで落ちている』と読めてしまう（落ちた理由は blockers が名指しする）。
    + `  E[r]${r.xEr == null ? '  na' : r.xEr.toFixed(0).padStart(4) + '%'} `
    + `  点${aud}`
    + `  ${r.buy ? '🟢投下可' : r.quali ? '🔵次点(11位以下)' : blockers(r).join('＋')}  出口=${r.exit}`);
}
// v9.9.91→v9.9.100: ロスターの並びは**席の順**（irr=85優先→Ω順）。当時の呼称は「合成点上位10社」と名乗りながらΩで並べていた）
// v9.9.94(2026-08-06): ここに合成点を**書き写していた**のをやめ、門の単一実装 ccfAllocScore を呼ぶ。
//   実害: v9.9.93 で配分の錨を (Ω−70)→Ω へ変えたとき、ccfAllocScore は直したのに
//   **この写しだけが錨70のまま取り残された**——席の選定(ccfAllocTop)と表示の並びが違う式で動いていた。
//   v9.9.65「同じ台帳を見る二つの検査器が違うことを言ってはいけない」を、写しを作ったせいで自分で破っていた。
const _ascore = x => ccfAllocScore(x);
// v9.9.100: 表示の並びも席の順と同じ規則（irr=85 を先に）＝門と端末が同じことを言う（v9.9.65）
const _mech = x => (+x.irr === 85) ? 0 : 1;
const buy = rows.filter(x => x.buy).sort((a, b) => _mech(a) - _mech(b) || _ascore(b) - _ascore(a) || b.s - a.s);
const nextUp = rows.filter(x => x.quali && !x.buy).sort((a, b) => _mech(a) - _mech(b) || _ascore(b) - _ascore(a) || b.s - a.s);
console.log(`\n🟢投下可(四関門∧irr=85優先→Ω順の上位10社／半導体連鎖は城の30%まで・v9.9.117) ${buy.length}社`
  + `　日本株${buy.filter(x => x.jp).length}／米国等${buy.filter(x => !x.jp).length}`
  + `\n  ${buy.map(x => x.nm.split(/\s/)[0]).join(' ') || '(なし)'}`);
if (nextUp.length) console.log(`🔵次点(四関門通過・席順11位以下＝買わない) ${nextUp.length}社\n  ${nextUp.map(x => x.nm.split(/\s/)[0]).join(' ')}`);
// v9.9.117: 半導体連鎖の相関上限（城の30%）で席から外れた社は**名指しで出す**（黙って消さない・v9.9.52）。
//   門(Ⅵ・盤)と端末が同じことを言う（v9.9.65の掟）
if (ALLOC_CAPPED.length)
  console.log(`◇半導体連鎖の相関上限で枠外(城の30%＝${ALLOC_CAPN}席・資格は保持) ${ALLOC_CAPPED.length}社\n  ${ALLOC_CAPPED.join(' ')}`);
console.log(`⛔堀不足で見送り(Ω75+だが堀が関門に届かない) ${q75.filter(x => !x.moatOK).length}社`);
console.log(`⛔点検で見送り(Ω75+・堀70+だが要修正/未解決警告あり) ${q75.filter(x => x.moatOK && !x.audOK).length}社`);
// 期末後の重大事象で落ちた社は**必ず名指しで出す**。黙って消えると v9.9.52
// 「城の行が理由不明で出ない」と同じ事故になる（四関門を通っているのに枠から消えるので、
//  理由を書かないと「なぜ居ないのか」が誰にも分からない）。
{
  const st = rows.filter(x => x.staleBS != null && x.s >= 75);
  console.log(`⛔期末後の重大事象で見送り(貸借対照表がパックのreportDate以降に大きく変わった) ${st.length}社`);
  for (const r of st) console.log(`     ${r.nm.split(/\s/)[0]}  Ω${r.s.toFixed(1)}  のれんの${r.staleBS}%がreportDate以降に流入`
    + `　→ night/audit_stale_bs.py の作業リスト。最新四半期で再審査すれば復帰しうる`);
}
{
  // v9.9.99: 事業の収縮で落ちた社は**名指しで出す**（黙って消さない・v9.9.52）
  const sh = rows.filter(r => r.s >= 75 && r.moatOK && r.shrink);
  console.log(`⛔事業の収縮で見送り(Ω75+・堀70+だが売上縮小 ∧ 営業利益率低下) ${sh.length}社`);
  for (const r of sh) console.log(`     ${r.nm.split(/\s/)[0]}  Ω${r.s.toFixed(1)}  ${r.shrink}`
    + `　→ 数字が戻れば自動で復帰。買わない理由であって売る理由ではない`);
}
console.log(`   ※全${rows.length}社: 要修正 ${rows.reduce((a,x)=>a+x.audE,0)}件 / 未解決警告 ${rows.reduce((a,x)=>a+x.audU,0)}件`);
console.log(`\n→ out/${outFile}（全${rows.length}件・降順）`+ (partial ? '　※部分実行なので正本 score_all.json は書き換えていない' : ''));
