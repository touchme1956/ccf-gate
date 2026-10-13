#!/usr/bin/env node
/**
 * night/check_pft_card.js — 🏦保有の「目標ポートフォリオ」カード（v9.9.214）を実ブラウザで検査する
 *
 * 何のカードか: 🏦保有の「ポートフォリオ」カード（ccfPfcHTML・v9.9.204）の下に出る、**目標の比率**の円グラフ（index.html の ccfPftModel / ccfPftHTML）。
 *   ETF・投資信託の区分＝ccfNetRows（portfolio.json の target.ami_weights）・個別株の各社＝ccfCastleWeights（🛒買付順位の目標ウェイトと同じ関数）。
 *   **表示だけ**——Ω・四関門・席・売却規律・配分に触れない。
 *
 * ★A は**この検査の中で固定したデータ**で式と振る舞いを測る（台帳の保有・席・門外例外を関数へ直接渡す）。
 *   目標の数字（ami_weights・shiro_castle_pct・castle_rank_weights）は repo の portfolio.json から**期待値を作る**＝配分を変えても検査は壊れない。
 * ★B（--full）は全パックを取り込み、**🛒買付順位と同じ数字か**を測る（注文書の目標ウェイト __ccfCastleW と区分の比率 __ccfCat）。約2分。
 *
 * 見ること:
 *   A1 円グラフ（円の数＝目標>0 の行の数・長さの合計＝周−隙間×数・割合の合計＝100・真ん中「ETF : 個別株」）
 *   A2 ETF・投資信託の区分（ami_names の順・目標>0 の本だけ・同じ指数の本〔QQQM〕を含む・その他の区分〔XLK〕を含む・今＝台帳の保有から）
 *   A3 個別株の重み（席 1/5/7/10 社で castle_rank_weights どおり・合計＝個別株の目標）・席0社／台帳が空なら理由つきの1行
 *   A4 門外例外（按分に入る社＝最後の重み・特別枠＝別の行で按分の枠から引く）
 *   A5 席の外の個別株＝目標0%の行・保有が無ければ「今」を出さない
 *   A6 色（今のカードと同じ保有は同じ色・区分は中のいちばん大きい本の色・重複なし）
 *   A7 目標の合計が100でなければ警告（黙って割り直さない）
 *   A8 🏦保有で今のカードの下に出る・金額（¥）を出さない・幅 320/360/390 ではみ出さない・JSエラーなし
 *   B1 個別株の各社の目標＝🛒買付順位の目標ウェイト（window.__ccfCastleW.w）・席の順も同じ
 *   B2 区分の今＝注文書の区分の比率（window.__ccfCat の now）
 *   B3 円グラフの円の数・割合の合計100
 *
 * 使い方: NODE_PATH=$(npm root -g) node night/check_pft_card.js [--full]
 *   前提: playwright と Chromium。終了コード 1 = 1件でも ✗。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const FULL = process.argv.includes('--full');
const PORT = 8983;
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓ ' + m); } else { fail++; console.log('  ✗ ' + m); } };
const near = (a, b, e = 0.01) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= e;

// ── 固定の保有（円＝株数×ドル価格×150）。名義は無し（ルール9）
const FX = 150;
const POS = [
  { t: 'MSFT', nm: 'Microsoft', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 8, npx: 500, bjpy: 497469, bd: '2026-04-15', v: 0 },
  { t: 'ASML', nm: 'ASMLホールディングス', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 1, npx: 1500, bjpy: 226006, bd: '2026-04-08', v: 0 },
  { t: 'XLK', nm: 'XLK テクノロジーセレクトセクターSPDR', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 24, npx: 200, bjpy: 679758, bd: '2026-06-17', v: 0 },
  { t: 'SMH', nm: 'ヴァンエック・半導体株ETF', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 4, npx: 610, bjpy: 362153, bd: '2026-06-22', v: 0 },
  { t: 'QQQM', nm: 'インベスコ NASDAQ 100 ETF', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 8, npx: 300, bjpy: 382617, bd: '2026-07-23', v: 0 },
];
const VAL = Object.fromEntries(POS.map(p => [p.t, p.sh * p.npx * FX]));
const TOT = Object.values(VAL).reduce((a, b) => a + b, 0);
const W = t => (VAL[t] || 0) / TOT * 100;
const DASH = { asof: '2026-10-09T01:00:00+00:00', fx: { USDJPY: FX }, news: {},
  quotes: Object.fromEntries(POS.map(p => [p.t, { px: p.npx, prev: p.npx, chgPct: 0, src: 'fixture' }])) };
const jr = (r, o) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(o) });

// ── 目標（repo の portfolio.json から期待値を作る）
const PF = JSON.parse(fs.readFileSync(path.join(ROOT, 'portfolio.json'), 'utf8'));
const T = PF.target || {};
const U = s => String(s || '').trim().toUpperCase();
const CT = (+T.shiro_castle_pct > 0) ? +T.shiro_castle_pct : 50;
const WN = Object.fromEntries(Object.entries(T.ami_weights || {}).map(([k, v]) => [U(k), +v]));
// 同じ区分に数える本＝同じ指数の本（ami_same_index・QQQM）と同じ扱いの本（ami_same_bucket・XLK・v9.9.214）。門の ccfSameAll と同じ読み方
const SAMEOF = {}, SKIND = {};
for (const [src, kind] of [[T.ami_same_index || {}, 'idx'], [T.ami_same_bucket || {}, 'bucket']])
  for (const k in src) if (Array.isArray(src[k])) for (const a of src[k]) { const A = U(a); if (A && A !== U(k) && !SAMEOF[A]) { SAMEOF[A] = U(k); SKIND[A] = kind; } }
const NAMES = (T.ami_names || []).map(U);
const ETF_EXP = NAMES.filter(t => (WN[t] || 0) > 0 && !SAMEOF[t]);            // 円グラフに出る ETF の区分（ami_names の順）
const OB = (T.ami_other && T.ami_other.buy) ? U(T.ami_other.buy) : '';
const heldNet = POS.filter(p => p.sleeve === 'net').map(p => p.t);
const nowEtf = k => {                                                         // 区分の今（注文書と同じ数え方）
  let v = W(k); for (const a in SAMEOF) if (SAMEOF[a] === k) v += W(a);
  if (k === OB) heldNet.forEach(t => { if (!ETF_EXP.includes(t) && !SAMEOF[t]) v += W(t); });
  return v;
};
function rankExp(seats, exIn, city) {                                          // ccfRankWeights と同じ考え方（席の順の相対の重み・門外例外は最後の重み）
  const Uw = (T.castle_rank_weights || []).map(Number), last = Uw[Uw.length - 1];
  const unit = {}; seats.forEach((t, i) => { unit[t] = i < Uw.length ? Uw[i] : last; }); (exIn || []).forEach(t => { unit[t] = last; });
  const us = Object.values(unit).reduce((a, b) => a + b, 0), w = {};
  for (const t in unit) w[t] = city * unit[t] / us;
  return w;
}
const RANK = String(T.castle_weighting || '').toLowerCase() === 'rank' && Array.isArray(T.castle_rank_weights) && T.castle_rank_weights.length;

(async () => {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch (e) { console.error('playwright が無い。NODE_PATH=$(npm root -g) を付けるか `npm i playwright`'); process.exit(2); }
  const srv = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1500));
  const EXE = '/opt/pw-browsers/chromium';
  const browser = await chromium.launch(fs.existsSync(EXE) ? { executablePath: EXE } : {});
  const errs = [];
  async function open(w = 390, route = true) {
    const ctx = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript(() => { try { localStorage.setItem('ccf_theme', 'light'); } catch (e) {} });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push('PAGEERROR ' + e.message));
    if (route) await p.route('**/*', r => {
      const u = r.request().url();
      if (/out\/dashboard\.json/.test(u)) return jr(r, DASH);
      return r.continue();
    });
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2000);
    return { p, ctx };
  }
  // ページの中で ccfPftModel / ccfPftHTML を呼ぶ（台帳・席・門外例外はここで固定）
  const model = (p, o) => p.evaluate(async o => {
    localStorage.setItem('pf:portfolio', JSON.stringify(o.pf));
    const pfJ = await (await fetch('portfolio.json?t=' + Date.now())).json();
    if (o.mut === 'sum') pfJ.target.shiro_castle_pct = +pfJ.target.shiro_castle_pct + 5;
    if (o.mut === 'noOther') { delete pfJ.target.ami_other; delete pfJ.target.ami_same_bucket; }   // XLK をどの区分にも数えない形
    if (o.mut === 'equal') pfJ.target.castle_weighting = 'equal';
    if (o.mut === 'badRank') pfJ.target.castle_rank_weights = [5, 0, 'x'];
    if (o.mut === 'noSnap') pfJ.positions = [];
    const led = {}; (o.led || []).forEach(t => { led[t] = { nm: t, d: {}, r: {} }; });
    const buy = (o.seats || []).map((t, i) => ({ t, s: 85 - i, nm: t }));
    const M = ccfPftModel(pfJ, o.exJ || { items: [] }, led, buy, o.fx, o.pfRows || [], o.nmOf || {});
    const box = document.createElement('div'); box.innerHTML = ccfPftHTML(M); document.body.appendChild(box);
    const c = box.querySelector('#pftCard');
    const C = 2 * Math.PI * 100, segs = c ? [...c.querySelectorAll('.pft-ring circle')] : [];
    const out = { M: JSON.parse(JSON.stringify(M)), n: segs.length, C,
      arc: segs.reduce((s, e) => s + parseFloat(e.getAttribute('stroke-dasharray').split(' ')[0]), 0),
      colors: segs.map(e => e.getAttribute('stroke')),
      centre: c ? c.querySelector('.pft-c2').textContent : null, text: c ? c.innerText : '',
      rows: c ? [...c.querySelectorAll('.pft-r')].map(e => ({ k: e.dataset.k, z: e.classList.contains('z'), txt: e.innerText.replace(/\s+/g, ' ') })) : [] };
    box.remove();
    return out;
  }, o);
  const base = { asof: '2026-10-09', fx: FX, positions: POS };
  const pfRows = POS.map(p => ({ t: p.t, val: VAL[p.t], label: p.nm }));
  const nmOf = Object.fromEntries(POS.map(p => [p.t, p.nm]));

  try {
    const { p, ctx } = await open();
    const SEATS10 = ['CW', 'LRCX', 'MSFT', 'ASML', 'GOOGL', 'KLAC', 'MCO', 'IDXX', 'ADBE', 'SAP'];
    const ledAll = SEATS10.concat(['TDG', 'VRT']);

    console.log(`■ A1. 円グラフ（席5社・保有5銘柄・目標＝repo の portfolio.json: ETF ${ETF_EXP.map(t => t + ' ' + WN[t]).join(' / ')}・個別株 ${CT}）`);
    {
      const r = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf });
      const nSl = ETF_EXP.length + 5;
      ok(r.n === nSl, `円の数＝目標>0 の行の数（${r.n} / ${nSl}）`);
      ok(near(r.arc, r.C - 2 * nSl, 0.05), `長さの合計＝周−隙間×数（${r.arc.toFixed(2)} / ${(r.C - 2 * nSl).toFixed(2)}）`);
      const sum = r.M.etf.concat(r.M.castle).reduce((a, x) => a + x.tw, 0);
      const sumExp = ETF_EXP.reduce((a, t) => a + WN[t], 0) + CT;
      ok(near(sum, sumExp, 1e-6), `割合の合計＝ETF の目標＋個別株の目標（${sum} / ${sumExp}）`);
      ok(near(sumExp, 100, 0.5) ? !/目標の合計が/.test(r.text) : /目標の合計が/.test(r.text), `合計${sumExp}%なら警告${near(sumExp, 100, 0.5) ? 'なし' : 'あり'}`);
      const g = v => (Math.abs(v - Math.round(v)) < 1e-6 ? String(Math.round(v)) : v.toFixed(1));
      ok(r.centre === `${g(sumExp - CT)} : ${g(CT)}`, `真ん中は「ETF・投資信託 : 個別株」＝${r.centre}`);
      ok(!/¥/.test(r.text), '金額（¥）を出さない（割合だけ）');
    }

    console.log('■ A2. ETF・投資信託の区分（今＝台帳の保有から・注文書と同じ数え方）');
    {
      const r = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf });
      ok(JSON.stringify(r.M.etf.map(x => x.k)) === JSON.stringify(ETF_EXP.map(t => 'n:' + t)), `並び＝ami_names の順の目標>0 の本（${r.M.etf.map(x => x.k).join(' / ')}）`);
      for (const x of r.M.etf) {
        const t = x.k.slice(2);
        ok(near(x.tw, WN[t], 1e-9) && near(x.now, nowEtf(t), 0.001), `${t}: 目標 ${x.tw}%・今 ${x.now.toFixed(2)}%（期待 ${nowEtf(t).toFixed(2)}%）`);
      }
      for (const x of r.M.etf) {                                              // 区分に数えた保有は注記に名前が出る（同じ扱いの本は「（同じ扱い）」）
        const t = x.k.slice(2), mem = heldNet.filter(a => SAMEOF[a] === t);
        if (t === OB) heldNet.forEach(a => { if (!ETF_EXP.includes(a) && !SAMEOF[a]) mem.push(a); });
        if (!mem.length) { ok(!/を含む/.test(x.sub), `${t}: 区分に数える保有が無ければ「を含む」と書かない（${x.sub}）`); continue; }
        ok(mem.every(a => x.sub.includes(SKIND[a] === 'bucket' ? a + '（同じ扱い）' : a)) && /を含む/.test(x.sub), `${t}: 区分に数えた保有を注記に出す（${x.sub}）`);
      }
      const oth = r.M.etf.find(x => x.k === 'n:' + OB);
      if (OB && oth) ok(/その他/.test(oth.nm), `その他の区分の名前（${oth.nm}）`);
      // 2026-10-13 ユーザー明示指示「ITAはその他ETF投資信託はなくして」で正本から ami_other を外した——どの区分の名前にも「その他」が出ない
      else if (!OB) ok(r.M.etf.every(x => !/その他/.test(String(x.nm) + String(x.label))), `その他の区分なし（正本に ami_other が無い）: 区分の名前は ${r.M.etf.map(x => x.label).join('・')}`);
      ok(near(r.M.etfNow + r.M.castleNow, 100, 1e-6) && near(r.M.castleNow, W('MSFT') + W('ASML'), 0.001), `ETF と個別株の今の合計100（個別株 ${r.M.castleNow.toFixed(2)}%）`);
      ok(r.M.etfExtra.length === 0, OB ? 'その他の区分があれば目標0%の ETF の行は出ない（区分に数えた）'
        : '目標0%で持つ ETF（QQQM・XLK）は同じ指数・同じ扱いで NASDAQ100 に数えた＝目標0%の行は出ない');
      const r2 = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf, mut: 'noOther' });
      const xk = r2.M.etfExtra.find(x => x.k === 'n:XLK');
      ok(!!xk && xk.tw === 0 && near(xk.now, W('XLK'), 0.001) && r2.rows.some(q => q.k === 'n:XLK' && q.z), `その他の区分も同じ扱いの設定も無ければ XLK は目標0%の行（今 ${xk ? xk.now.toFixed(2) : '—'}%・売らずに持ち続ける）`);
    }

    console.log(`■ A3. 個別株の重み（${RANK ? 'castle_rank_weights ' + JSON.stringify(T.castle_rank_weights) : '順位の重みが無い→合計だけ'}）`);
    for (const n of [1, 5, 7, 10]) {
      const seats = SEATS10.slice(0, n);
      const r = await model(p, { pf: base, led: ledAll, seats, fx: FX, pfRows, nmOf });
      const cs = r.M.castle.filter(x => x.k !== 'c:_rest');
      const sum = r.M.castle.reduce((a, x) => a + x.tw, 0);
      const exp = RANK ? rankExp(seats, [], CT) : null;
      const okW = !exp || cs.every(x => near(x.tw, exp[x.k.slice(2)], 1e-9));
      ok(cs.length === n && near(sum, CT, 1e-9) && okW && JSON.stringify(cs.map(x => x.k.slice(2))) === JSON.stringify(seats),
        `席${n}社: 席の順・合計 ${sum.toFixed(4)}%＝${CT}%${exp ? '・各社 ' + [...new Set(cs.map(x => x.tw.toFixed(3)))].join('/') + '%' : ''}`);
      if (n === 10) ok(r.n === ETF_EXP.length + 10 && new Set(r.colors).size === r.colors.length, `席10社: 円 ${r.n} 個の色が重ならない（今のカードの12色＋予備）`);
    }
    {
      const r = await model(p, { pf: base, led: ledAll, seats: [], fx: FX, pfRows, nmOf });
      const rest = r.M.castle.find(x => x.k === 'c:_rest');
      ok(!!rest && near(rest.tw, CT, 1e-9) && /四関門を通る社が無い/.test(rest.sub), `席0社（台帳あり）: 個別株 ${CT}% の1行・理由「${rest ? rest.sub : ''}」`);
      const r2 = await model(p, { pf: base, led: [], seats: [], fx: FX, pfRows, nmOf });
      const rest2 = r2.M.castle.find(x => x.k === 'c:_rest');
      ok(!!rest2 && /台帳が空/.test(rest2.sub), `台帳が空: 理由は「${rest2 ? rest2.sub : ''}」（四関門の不通過と取り違えない）`);
      const r3 = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf, mut: 'equal' });
      ok(r3.M.castle.every(x => near(x.tw, CT / 5, 1e-9)) && /均等/.test(r3.text), `castle_weighting=equal なら等分（各 ${(CT / 5).toFixed(2)}%）`);
      const r4 = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf, mut: 'badRank' });
      ok(r4.M.rankMiss && r4.M.castle.every(x => near(x.tw, CT / 5, 1e-9)) && /castle_rank_weights が読めない/.test(r4.text), '順位の重みが読めなければ均等へ倒し、名指しする（🛒買付順位と同じ扱い）');
    }

    console.log('■ A4. 門外例外（按分に入る社・特別枠）');
    {
      const exJ = { items: [{ t: 'TDG', in_castle_split: true, weight_pct: 0 }, { t: 'VRT', in_castle_split: false, weight_pct: 1.0 }] };
      const seats = SEATS10.slice(0, 5);
      const r = await model(p, { pf: base, led: ledAll, seats, fx: FX, pfRows, nmOf, exJ });
      const by = Object.fromEntries(r.M.castle.map(x => [x.k.slice(2), x]));
      const exp = RANK ? rankExp(seats, ['TDG'], CT - 1.0) : null;
      ok(!!by.TDG && /按分に入る例外/.test(by.TDG.sub) && (!exp || near(by.TDG.tw, exp.TDG, 1e-9)), `按分に入る門外例外は最後の重み（TDG ${by.TDG ? by.TDG.tw.toFixed(3) : '—'}%）`);
      ok(!!by.VRT && near(by.VRT.tw, 1.0, 1e-9) && /特別枠/.test(by.VRT.sub), '特別枠は weight_pct の行（VRT 1.0%）');
      ok(near(r.M.castle.reduce((a, x) => a + x.tw, 0), CT, 1e-9), `個別株の合計は ${CT}% のまま（特別枠の分を席の按分から引く）`);
      ok(!exp || seats.every(t => near(by[t].tw, exp[t], 1e-9)), `席の社は ${CT}−1.0% を順位の重みで（${seats.map(t => by[t].tw.toFixed(3)).join('/')}）`);
    }

    console.log('■ A5. 席の外の個別株・保有が無いとき');
    {
      const seats = ['CW', 'LRCX', 'MSFT', 'GOOGL', 'KLAC'];                     // ASML は席の外
      const r = await model(p, { pf: base, led: ledAll, seats, fx: FX, pfRows, nmOf });
      const a = r.M.castleExtra.find(x => x.k === 'c:ASML');
      ok(!!a && a.tw === 0 && near(a.now, W('ASML'), 0.001) && /席の外/.test(a.sub) && r.rows.some(q => q.k === 'c:ASML' && q.z), `ASML は目標0%の行（今 ${a ? a.now.toFixed(2) : '—'}%・売らずに持ち続ける）`);
      ok(r.n === ETF_EXP.length + 5, '目標0%の行は円グラフに入れない');
      const empty = { asof: '2026-10-09', fx: FX, positions: [] };
      const r1 = await model(p, { pf: empty, led: ledAll, seats, fx: FX, pfRows: [], nmOf: {} });
      ok(r1.M.live && r1.M.src === 'snapshot' && /今＝portfolio\.json の保有の写し/.test(r1.text), '台帳が空なら今は portfolio.json の保有の写し（注文書と同じ倒し方）と副題に出す');
      const r2 = await model(p, { pf: empty, led: ledAll, seats, fx: FX, pfRows: [], nmOf: {}, mut: 'noSnap' });
      ok(!r2.M.live && !/今 \d/.test(r2.text) && /読めないので出していない/.test(r2.text), '保有がどこにも無ければ「今」を出さず、注記でそう言う（0%と読まない）');
      const cw = r.M.castle.find(x => x.k === 'c:CW'), ms = r.M.castle.find(x => x.k === 'c:MSFT');
      ok(cw && near(cw.now, 0, 1e-9) && ms && ms.nm === 'Microsoft' && /^MSFT・席3位/.test(ms.sub), `持っていない席の社は今0%・持っている社は保有の名前（${ms ? ms.nm + '／' + ms.sub : '—'}）`);
    }

    console.log('■ A6. 色（今のカードと同じ保有は同じ色）');
    {
      const r = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf });
      const COL = await p.evaluate(() => CCF_PFC_COLORS);
      const cur = {}; pfRows.slice().sort((a, b) => b.val - a.val).forEach((q, i) => { cur[q.t] = COL[i % COL.length]; });
      const col = Object.fromEntries(r.M.etf.concat(r.M.castle).map(x => [x.k, x.color]));
      for (const t of ETF_EXP) {                                               // 区分は中の保有のうち今いちばん大きい本の色（保有が無ければ残りの色）
        const mem = [t].concat(heldNet.filter(a => SAMEOF[a] === t));
        if (t === OB) heldNet.forEach(a => { if (!ETF_EXP.includes(a) && !SAMEOF[a]) mem.push(a); });
        const big = mem.filter(a => VAL[a] > 0).sort((a, b) => VAL[b] - VAL[a])[0];
        if (big) ok(col['n:' + t] === cur[big], `${t} の区分は中のいちばん大きい ${big} の色（${col['n:' + t]}）`);
        else ok(!Object.values(cur).includes(col['n:' + t]), `${t} の区分は保有が無いので今のカードに無い色（${col['n:' + t]}）`);
      }
      ok(col['c:MSFT'] === cur.MSFT && col['c:ASML'] === cur.ASML, 'MSFT・ASML は今のカードと同じ色');
      ok(new Set(r.colors).size === r.colors.length, `円グラフの色に重複なし（${r.colors.length}色）`);
    }

    console.log('■ A7. 目標の合計が100でないとき');
    {
      const r = await model(p, { pf: base, led: ledAll, seats: SEATS10.slice(0, 5), fx: FX, pfRows, nmOf, mut: 'sum' });
      ok(/目標の合計が/.test(r.text) && /黙って割り直していない/.test(r.text), '警告を出す（黙って割り直さない）');
      ok(near(r.M.castle.reduce((a, x) => a + x.tw, 0), CT + 5, 1e-9), `値はそのまま使う（個別株 ${CT + 5}%）`);
    }
    await ctx.close();

    console.log('■ A8. 🏦保有で今のカードの下に出る・はみ出さない');
    for (const w of [320, 360, 390]) {
      const o = await open(w);
      await o.p.evaluate(pf => { localStorage.setItem('pf:portfolio', JSON.stringify(pf)); showPage(6); }, base);
      await o.p.waitForTimeout(1600);
      const r = await o.p.evaluate(() => {
        const a = document.getElementById('pfcCard'), b = document.getElementById('pftCard');
        if (!b) return null;
        const rb = b.getBoundingClientRect();
        const over = [...b.querySelectorAll('*')].filter(e => { const q = e.getBoundingClientRect(); return q.width > 0 && (q.right > rb.right + 0.5 || q.left < rb.left - 0.5); }).length;
        return { after: !!(a && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)), sw: document.documentElement.scrollWidth,
          cw: document.documentElement.clientWidth, over, text: b.innerText, n: b.querySelectorAll('.pft-ring circle').length };
      });
      if (!r) { ok(false, `${w}px: カードが出ない`); await o.ctx.close(); continue; }
      ok(r.after && r.sw <= r.cw && r.over === 0, `${w}px: 今のカードの下・横にはみ出さない（${r.sw}/${r.cw}・カードの外へ出る要素 ${r.over}）`);
      if (w === 390) {
        ok(!/¥/.test(r.text), '金額（¥）を出さない');
        // v9.9.218: 台帳が空の端末は開いた時点で自動取込が始まる＝その間は「取り込んでいる途中」と言う（どちらも四関門の不通過と取り違えない）
        ok(/台帳が空|取り込んでいる途中/.test(r.text), '台帳（📚）が空なら個別株の行は「台帳が空」か「取り込んでいる途中」と言う');
      }
      await o.ctx.close();
    }

    if (FULL) {
      console.log('■ B. 全パック取込のうえで 🛒買付順位と同じ数字か（repo の保有・約2分）');
      const o = await open(1280, false);
      const q = o.p;
      await q.evaluate(() => { const t = document.getElementById('tab3'); if (t) t.click(); });
      await q.waitForTimeout(600);
      await q.evaluate(() => (typeof ccfImportAllPacks === 'function' ? ccfImportAllPacks() : null));
      let prev = -1, stable = 0;
      for (let i = 0; i < 90; i++) { await q.waitForTimeout(2000);
        const n = await q.evaluate(() => { let c = 0; for (let i = 0; i < localStorage.length; i++) if (localStorage.key(i).startsWith('g7:')) c++; return c; });
        if (n === prev) { if (++stable >= 3) break; } else { stable = 0; prev = n; } }
      console.log(`  （台帳 ${prev} 件）`);
      await q.evaluate(() => showPage(5)); await q.waitForTimeout(6000);
      const plan = await q.evaluate(() => ({ cw: window.__ccfCastleW ? JSON.parse(JSON.stringify(window.__ccfCastleW)) : null, cat: window.__ccfCat ? JSON.parse(JSON.stringify(window.__ccfCat)) : null }));
      await q.evaluate(() => showPage(6)); await q.waitForTimeout(3000);
      const M = await q.evaluate(() => window.__pftData ? JSON.parse(JSON.stringify(window.__pftData)) : null);
      const n = await q.evaluate(() => document.querySelectorAll('#pftCard .pft-ring circle').length);
      if (!plan.cw || !M) ok(false, `材料が読めない（__ccfCastleW ${!!plan.cw}・__pftData ${!!M}）`);
      else {
        const cs = M.castle.filter(x => x.k !== 'c:_rest');
        ok(JSON.stringify(cs.map(x => x.k.slice(2))) === JSON.stringify(plan.cw.seats || []), `席の順が同じ（${cs.map(x => x.k.slice(2)).join(' / ')}）`);
        ok(cs.every(x => near(x.tw, +plan.cw.w[x.k.slice(2)], 1e-9)), `各社の目標＝注文書の目標ウェイト（${cs.map(x => x.k.slice(2) + ' ' + x.tw.toFixed(2)).join(' / ')}）`);
        if (plan.cat) {
          const diffs = M.etf.map(x => [x.k, x.now, plan.cat[x.k] ? plan.cat[x.k].now : null]).concat([['c', M.castleNow, plan.cat.c ? plan.cat.c.now : null]]);
          ok(diffs.every(([, a, b]) => a != null && b != null && near(a, b, 0.001)), `区分の今＝注文書の区分の比率（${diffs.map(([k, a]) => k + ' ' + (a == null ? '—' : a.toFixed(1))).join(' / ')}）`);
          ok(M.etf.every(x => plan.cat[x.k] && near(x.tw, +plan.cat[x.k].t, 1e-9)) && plan.cat.c && near(M.castleT, +plan.cat.c.t, 1e-9), '区分の目標＝注文書の区分の目標');
        } else ok(false, '注文書の区分の比率（__ccfCat）が無い');
        ok(n === M.etf.length + M.castle.length && near(M.sum, 100, 0.5), `円の数 ${n}・割合の合計 ${M.sum}%`);
      }
      await o.ctx.close();
    }
  } finally {
    await browser.close(); srv.kill();
  }
  console.log(errs.length ? '\n' + errs.slice(0, 5).join('\n') : '\n（ページ内のJSエラーなし）');
  if (errs.length) fail++;
  console.log(`\n結果: ✓ ${pass} / ✗ ${fail}`);
  process.exit(fail ? 1 : 0);
})();
