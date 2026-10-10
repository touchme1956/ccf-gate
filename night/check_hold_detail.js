#!/usr/bin/env node
/**
 * night/check_hold_detail.js — 🏦保有の「銘柄の詳細」（v9.9.209）と、保有が変わったときの自動の描き直し・鍵の撤去・📈成績の差の表示を実ブラウザで検査する
 *
 * 何の画面か: 🏦保有のカードの銘柄の行（と 💰銘柄の行）を押すと全画面で開く、家計アプリの「タグ」詳細と同じ作りの画面
 *   （合計金額・損益・前日比・口座ごとの行・配当利回り）。index.html の ccfPfdModel / ccfPfdHTML。
 *   **表示だけ**——Ω・四関門・売却規律・配分に触れない。数字は ccfDash の集計（カードと同じ）を使い、口座の行は**同じ式**で株数だけ替える。
 *
 * ★データは**この検査の中で固定**する（保有・価格・配当・成績を route で差し替える）。名前は A / B（絶対のルール9: 実名を repo に書かない）。
 *   期待値は画面の式を**写さずに**独立の算術で出す（前日の評価額＝株数×前日の株価×前日のドル円 など）。
 *
 * 見ること:
 *   A 押せる行（カードの内訳・💰銘柄・キーボード）  B 開く＝合計・損益・前日比・口座ごとの行（合計と一致）・ロットの名義/口座・古い記録の見出し
 *   C 損益が出せない口座は「—」（0と読まない）・D 口座の内訳なし／一部売却後／残りの行  E 配当利回り（評価額・取得額・n=0・投資信託・通貨違い・取れていない）
 *   F 閉じる（←・Esc・端末の戻る）・背景のスクロール固定  G 金額を隠す（¥数字・株数が出ない）
 *   H 自動の描き直し（開いたまま保有が書き換わる／機械の書き戻しでは動かない／別の文書の書き込み／売り切ると閉じる）
 *   I 鍵の撤去（ccfState に pushRepo/setToken/hasToken が無い・端末の鍵は消える・記録のあとの案内に「鍵」が無い）
 *   J 📈成績の先頭の差の表示（違いを銘柄名で・同じなら出さない・金額を隠すと数字を出さない・未書き出しの有無で案内が変わる）
 *   K 横にはみ出さない（幅 --width・既定 360）
 *
 * 使い方: NODE_PATH=$(npm root -g) node night/check_hold_detail.js [--width 360]
 *   前提: playwright と Chromium。終了コード 1 = 1件でも ✗。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const argv = process.argv.slice(2);
const W = argv.includes('--width') ? Number(argv[argv.indexOf('--width') + 1]) : 360;
const PORT = 8982;
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓ ' + m); } else { fail++; console.log('  ✗ ' + m); } };
const near = (a, b, e = 0.006) => Math.abs(a - b) <= e;

// ── 固定のデータ
const FX = 150, FXP = 149.4;
const lotA = { sh: 3, jpy: 190000, bd: '2026-04-15', who: 'A', acct: '成長', src: '門の🏦保有で記録（約定日 2026-04-15）（A・成長）' };
const lotB = { sh: 3, jpy: 200000, bd: '2026-05-20', who: 'B', acct: 'つみたて', src: '門の🏦保有で記録（約定日 2026-05-20）（B・つみたて）' };
const lotC = { sh: 2, jpy: 107469, src: '楽天証券 A 証券口座(新NISA) 2026-05-01 2株（旧い記録のメモ）' };   // 古い記録（名義・口座の欄が無い）
const POS = [
  { t: 'MSFT', nm: 'Microsoft', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 8, bjpy: 497469, bd: '2026-04-15', npx: 0, v: 0, bdLots: [lotA, lotB, lotC] },
  { t: 'XLK', nm: 'XLK テクノロジーセレクトセクターSPDR', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 24, bjpy: 679758, bd: '2026-06-17', npx: 0, v: 0,
    bdLots: [{ sh: 11, usd: 169.5, src: '楽天証券 B 約定' }, { sh: 13, usd: 185.4, src: '楽天証券 B 2026-08-23 特定口座 13株' }] },   // 円の取得額が無い口座
  { t: 'SMH', nm: 'ヴァンエック・半導体株ETF', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 4, bjpy: 362153, bd: '2026-06-22', npx: 0, v: 0 },
  { t: 'IFREE-NDX', nm: 'iFreeNEXT NASDAQ100インデックス', sleeve: 'net', kind: '投資信託', ccy: 'JPY', sh: 100000, bjpy: 600, bd: '2026-09-29', npx: 5.8668, v: 0, navPer: 10000 },
  { t: 'OVER', nm: 'Over Corp', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 3, bjpy: 90000, npx: 0, v: 0, bdLots: [{ sh: 2, jpy: 60000, who: 'A', acct: '特定', src: 'x' }, { sh: 2, jpy: 60000, who: 'B', acct: '特定', src: 'x' }] },   // 一部売却のあと（内訳の合計 4 > 保有 3）
  { t: 'PART', nm: 'Part Inc', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 5, bjpy: 100000, npx: 0, v: 0, bdLots: [{ sh: 2, jpy: 40000, who: 'A', acct: '成長', src: 'x' }] },       // 内訳が保有より少ない（残り3株）
  { t: '6146', nm: 'ディスコ', sleeve: 'castle', kind: '個別', ccy: 'JPY', sh: 10, bjpy: 300000, npx: 0, v: 0 },
  { t: 'EURX', nm: 'Euro Stock', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 1, bjpy: 100000, npx: 0, v: 0 },                                                         // 配当の通貨が合わない
  { t: 'NODV', nm: 'No Div Co', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 1, bjpy: 100000, npx: 0, v: 0 },                                                           // 配当の実績が無い
  { t: 'MEMO', nm: 'Memo Co', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 2, bjpy: 50000, npx: 0, v: 0, note: '2026-10-01 1株売却（門で記録）',                        // 古い記録（口座が判る一節が無い）・メモに株数と金額が入っている
    bdLots: [{ sh: 2, jpy: 50000, src: '2026-08-21 NISA成長 2株 ¥50,000（画面から写した）' }] },
];
const PX = { MSFT: [500, -1.9608], XLK: [200, -1.0], SMH: [610, -3.0], OVER: [100, 2.0], PART: [100, 0.0], '6146': [38000, 1.0], EURX: [100, 1.0], NODV: [100, 1.0], MEMO: [100, 0.0] };
const DASH = (fx) => ({ asof: '2026-10-09T01:00:00+00:00', fx: Object.assign({ USDJPY: FX, prev: FXP }, fx || {}), news: {},
  quotes: Object.assign(Object.fromEntries(Object.entries(PX).map(([t, [px, c]]) => [t, { px, prev: px / (1 + c / 100), chgPct: c, src: 'fixture' }])),
    { 'IFREE-NDX': { px: 5.8668, chgPct: null, src: 'toushin-lib', navPer: 10000 } }) });
const DIV = { asof: '2026-10-09', src: 'fixture', div: {
  MSFT: { ttm: 3.64, n: 4, ccy: 'USD', last_d: '2026-09-10' }, XLK: { ttm: 0.7, n: 4, ccy: 'USD', last_d: '2026-09-22' },
  SMH: { ttm: 0, n: 0, ccy: 'USD', last_d: '2025-12-23' }, '6146': { ttm: 600, n: 2, ccy: 'JPY', last_d: '2026-09-29' },
  EURX: { ttm: 2, n: 1, ccy: 'EUR', last_d: '2026-07-01' }, OVER: { ttm: 1, n: 4, ccy: 'USD', last_d: '2026-09-01', stale: true } } };
const jr = (r, o) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(o) });
const RET = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'returns.json'), 'utf8'));

(async () => {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch (e) { console.error('playwright が無い。NODE_PATH=$(npm root -g) を付けるか `npm i playwright`'); process.exit(2); }
  const srv = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1500));
  const _EXE = '/opt/pw-browsers/chromium';
  const browser = await chromium.launch(fs.existsSync(_EXE) ? { executablePath: _EXE } : {});
  const errs = [];
  async function open(o = {}) {
    const ctx = o.ctx || await browser.newContext({ viewport: { width: W, height: 900 }, deviceScaleFactor: 1 });
    if (!o.ctx) await ctx.addInitScript((tok) => { try { localStorage.setItem('ccf_theme', 'light'); if (tok) localStorage.setItem('ccf:ghToken', 'ghp_FIXTURE_NOT_A_REAL_KEY'); } catch (e) {} }, !!o.token);
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push('PAGEERROR ' + e.message));
    await p.route('**/*', r => {
      const u = r.request().url();
      if (/out\/dashboard\.json/.test(u)) return jr(r, DASH(o.fx));
      if (/out\/holdings_div\.json/.test(u)) return o.noDiv ? r.fulfill({ status: 404, body: '' }) : jr(r, o.div || DIV);
      if (/out\/returns\.json/.test(u) && o.returns) return o.returns === 'none' ? r.fulfill({ status: 404, body: '' }) : jr(r, o.returns);
      return r.continue();
    });
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2000);
    return { p, ctx };
  }
  const pfOf = (positions) => ({ asof: '2026-10-09', fx: FX, positions });
  async function showDash(p, pf, money) {
    await p.evaluate(([pf, money]) => {
      try { localStorage.setItem('pf:showMoney', money ? '1' : '0'); } catch (e) {}
      localStorage.setItem('pf:portfolio', JSON.stringify(pf));
      showPage(6);
    }, [pf, money]);
    await p.waitForTimeout(1500);
  }
  const sheet = (p) => p.evaluate(() => {
    const el = document.getElementById('pfdSheet'); if (!el || !el.classList.contains('on')) return null;
    const t = s => (el.querySelector(s) || {}).innerText || '';
    return { head: t('.pfd-name'), tot: t('.pfd-tv'), sub: [...el.querySelectorAll('.pfd-sub > div')].map(e => e.innerText.replace(/\s+/g, ' ').trim()),
      info: t('.pfd-info').replace(/\s+/g, ' '), sec: t('.pfd-sec'), warn: [...el.querySelectorAll('.pfd-warn')].map(e => e.innerText), note: t('.pfd-note').replace(/\s+/g, ' '),
      lots: [...el.querySelectorAll('.pfd-lot')].map(l => ({ name: (l.querySelector('.pfd-ln') || {}).innerText, cap: (l.querySelector('.pfd-lc') || {}).innerText,
        qty: [...l.querySelectorAll('.pfd-lq')].map(e => e.innerText).join(' / '), val: (l.querySelector('.pfd-lv') || {}).innerText,
        d: [...l.querySelectorAll('.pfd-d')].map(e => e.innerText.replace(/\s+/g, ' ').trim()), y: [...l.querySelectorAll('.pfd-y')].map(e => e.innerText.replace(/\s+/g, ' ').trim()),
        memo: !!l.querySelector('.pfd-memo') })),
      full: el.innerText, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, lock: document.documentElement.classList.contains('pfd-open'),
      sheetW: el.scrollWidth, sheetCW: el.clientWidth };
  });
  const money = s => { const t = String(s).replace(/,/g, ''); const m = t.match(/(−?)¥([0-9]+)/); return m ? (m[1] ? -1 : 1) * Number(m[2]) : NaN; };
  const pctOf = s => { const m = String(s).match(/(−?)([0-9]+\.[0-9]+)%/); return m ? (m[1] ? -1 : 1) * Number(m[2]) : NaN; };

  try {
    console.log(`■ A. 押せる行（幅${W}px）`);
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      const a = await p.evaluate(() => ({
        card: [...document.querySelectorAll('#pfcCard .pfc-r')].map(e => ({ t: e.dataset.t, role: e.getAttribute('role'), tab: e.tabIndex })),
        led: [...document.querySelectorAll('#dashBox .led[data-t]')].map(e => e.dataset.t) }));
      ok(a.card.length === POS.length && a.card.every(x => x.role === 'button' && x.tab === 0), `カードの内訳は全${POS.length}行が role=button・tabindex=0（${a.card.length}行）`);
      ok(a.led.length === POS.length, `💰銘柄の行も全${POS.length}行が押せる（${a.led.length}行）`);
      await p.focus('#pfcCard .pfc-r[data-t="MSFT"]'); await p.keyboard.press('Enter'); await p.waitForTimeout(300);
      let s = await sheet(p);
      ok(s && s.head === 'Microsoft', 'キーボード（Enter）で開く');
      await p.keyboard.press('Escape'); await p.waitForTimeout(200);
      ok((await sheet(p)) === null, 'Esc で閉じる');
      await p.click('#dashBox .led[data-t="SMH"]'); await p.waitForTimeout(300);
      s = await sheet(p);
      ok(s && /ヴァンエック/.test(s.head), '💰銘柄の行を押しても開く');
      await ctx.close();
    }

    console.log('■ B. 開く（Microsoft・3つの口座）');
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      await p.click('#pfcCard .pfc-r[data-t="MSFT"]'); await p.waitForTimeout(400);
      const s = await sheet(p);
      // 独立の算術（画面の式を写さない）: 評価額＝株数×株価×ドル円。前日の評価額＝株数×前日の株価×前日のドル円
      const px = 500, chg = -1.9608, prevPx = px / (1 + chg / 100);
      const val = (n) => n * px * FX, prev = (n) => n * prevPx * FXP;
      const cost = { A: 190000, B: 200000, C: 107469 };
      ok(s && s.head === 'Microsoft' && s.sec === '株式(現物)', `見出し・区分（${s && s.head}／${s && s.sec}）`);
      ok(s && money(s.tot) === val(8), `合計金額（${s && s.tot}）＝ 8株×$500×150 = ¥${val(8).toLocaleString('en-US')}`);
      ok(s && near(money(s.sub[0]), Math.round(val(8) - 497469), 1) && near(pctOf(s.sub[0]), (val(8) / 497469 - 1) * 100, 0.006), `合計の損益（${s && s.sub[0]}）`);
      ok(s && near(money(s.sub[1]), Math.round(val(8) - prev(8)), 1) && money(s.sub[1]) < 0, `合計の前日比は株価と為替の動き（${s && s.sub[1]}）＝ ${(val(8) - prev(8)).toFixed(0)}`);
      ok(s && s.lots.length === 3, `口座ごとの行は3つ（${s && s.lots.length}）`);
      ok(s && s.lots[0].cap === 'A　NISA 成長投資枠' && s.lots[1].cap === 'B　NISA つみたて投資枠', `名義と口座（${s && s.lots.map(l => l.cap).join(' | ')}）`);
      ok(s && s.lots[2].cap === '楽天証券 A 証券口座(新NISA)', `古い記録は「楽天証券 …」の頭の一節だけ（日付・株数・括弧のメモを除く）（${s && s.lots[2].cap}）`);
      ok(s && s.lots.map(l => l.memo).join() === 'false,false,true', '記録のメモは古い記録だけに付く（新しい記録のメモは機械の定型文）');
      ok(s && /購入日 2026-04-15/.test(s.lots[0].qty) && /購入日 2026-05-20/.test(s.lots[1].qty) && !/購入日/.test(s.lots[2].qty), '購入日は記録のある口座だけ');
      ok(s && s.lots.map(l => money(l.val)).join() === [val(3), val(3), val(2)].join(), `口座ごとの評価額（${s && s.lots.map(l => l.val).join(' / ')}）`);
      const sumV = s ? s.lots.reduce((a, l) => a + money(l.val), 0) : NaN;
      ok(near(sumV, money(s.tot), 0.5), `口座の評価額の合計 ＝ 合計金額（${sumV}）`);
      const sumPl = s ? s.lots.reduce((a, l) => a + money(l.d[0]), 0) : NaN;
      ok(near(sumPl, money(s.sub[0]), 2), `口座の損益の合計 ＝ 合計の損益（${sumPl} ≒ ${s && money(s.sub[0])}）`);
      ok(s && s.lots.every((l, i) => near(money(l.d[0]), Math.round(val([3, 3, 2][i]) - [cost.A, cost.B, cost.C][i]), 1)), '口座ごとの損益 ＝ その口座の評価額 − その口座の取得額（円）');
      ok(s && s.lots.every((l, i) => near(money(l.d[1]), Math.round(val([3, 3, 2][i]) - prev([3, 3, 2][i])), 1)), '口座ごとの前日比 ＝ 株数×(今の株価×今のドル円 − 前日の株価×前日のドル円)');
      ok(s && s.info.includes('保有 8株') && s.info.includes('現在値 $500'), `保有と現在値（${s && s.info}）`);
      ok(s && s.lots.every(l => l.name === 'Microsoft (MSFT)'), `口座の行の銘柄名は短く（${s && s.lots[0].name}）`);
      ok(s && s.sw <= s.cw && s.sheetW <= s.sheetCW, `横にはみ出さない（${s && s.sw}/${s && s.cw}・シート ${s && s.sheetW}/${s && s.sheetCW}）`);
      ok(s && s.lock, '開いている間は後ろをスクロールさせない（html.pfd-open）');
      await ctx.close();
    }

    console.log('■ C/D. 損益が出せない口座・口座の内訳なし・一部売却のあと・残りの行');
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      const open_ = async t => { await p.evaluate(t => ccfHoldOpen(t), t); await p.waitForTimeout(250); return sheet(p); };
      let s = await open_('XLK');
      ok(s && s.lots.length === 2 && s.lots.every(l => /^損益: —$/.test(l.d[0])), `円の取得額が無い口座は損益「—」（0と読まない）（${s && s.lots.map(l => l.d[0]).join(' | ')}）`);
      ok(s && money(s.sub[0]) === Math.round(24 * 200 * FX - 679758), `その場合も合計の損益は保有全体の取得額で出る（${s && s.sub[0]}）`);
      ok(s && /楽天証券 B/.test(s.lots[0].cap) && !/2026-08-23/.test(s.lots[1].cap), `古い記録の見出しから日付を除く（${s && s.lots.map(l => l.cap).join(' | ')}）`);
      s = await open_('SMH');
      ok(s && s.lots.length === 1 && s.lots[0].cap === '口座の内訳なし' && money(s.lots[0].val) === money(s.tot), `記録の無い銘柄は合計1行「口座の内訳なし」で合計と同じ（${s && s.lots[0].val}）`);
      s = await open_('OVER');
      ok(s && s.lots.length === 1 && /口座ごとの内訳は出せません/.test(s.lots[0].cap) && s.warn.some(w => /一部売却/.test(w)), `内訳の株数が保有より多い（一部売却のあと）＝内訳を使わず合計1行＋理由（${s && s.warn[0] && s.warn[0].slice(0, 40)}…）`);
      s = await open_('MEMO');
      ok(s && s.lots[0].cap === '2026-08-21 NISA成長 2株 ¥50,000（画面から写した）' && !s.lots[0].memo && /メモ: 2026-10-01 1株売却/.test(s.note), `口座が判る一節が無い古い記録は、書かれた文の頭をそのまま見せる（口座名を作らない）（${s && s.lots[0].cap}）`);
      s = await open_('PART');
      ok(s && s.lots.length === 2 && s.lots[1].cap === '口座の記録なし（残り）' && /^3株$/.test(s.lots[1].qty.split(' / ')[0]), `内訳が保有より少ない＝「口座の記録なし（残り）」3株（${s && s.lots.map(l => l.cap + ' ' + l.qty).join(' | ')}）`);
      ok(s && money(s.lots[1].d[0].replace('損益: ', '')) === Math.round(3 * 100 * FX - 60000) && money(s.lots[0].val) + money(s.lots[1].val) === money(s.tot), '残りの取得額＝保有全体の取得額 − 内訳の取得額（円）・合計と一致');
      await ctx.close();
    }

    console.log('■ E. 配当利回り');
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      const open_ = async t => { await p.evaluate(t => ccfHoldOpen(t), t); await p.waitForTimeout(250); return sheet(p); };
      let s = await open_('MSFT');
      const yM = 3.64 / 500 * 100, yC = n => 3.64 * n * FX / ({ 3: 190000, 33: 200000, 2: 107469 }[n === 3 ? 3 : 2]) * 100;
      ok(s && s.lots.every(l => /配当利回り（評価額）: 0\.73%/.test(l.y.join(' '))) && near(yM, 0.728, 0.001), `評価額ベース ＝ 直近12か月の1株配当 ÷ 現在値（3.64÷500＝${yM.toFixed(3)}%）`);
      const yCs = s ? s.lots.map(l => pctOf((l.y.find(x => /取得額/.test(x)) || ''))) : [];
      ok(near(yCs[0], 3.64 * 3 * FX / 190000 * 100, 0.006) && near(yCs[1], 3.64 * 3 * FX / 200000 * 100, 0.006) && near(yCs[2], 3.64 * 2 * FX / 107469 * 100, 0.006), `取得額ベース ＝ 配当×株数×ドル円 ÷ その口座の取得額（${yCs.map(v => v.toFixed(2)).join(' / ')}）`);
      ok(s && /最後の支払い 2026-09-10/.test(s.note) && /取得日 2026-10-09/.test(s.note) && /予想ではありません/.test(s.note), '注記: 実績・税引前・最後の支払い・取得日・予想ではない');
      s = await open_('XLK');
      ok(s && s.lots.every(l => /評価額）: 0\.35%/.test(l.y.join(' ')) && /取得額）: —/.test(l.y.join(' '))), `取得額が無い口座の取得額ベースは「—」・評価額ベースは出る（${s && s.lots[0].y.join(' ')}）`);
      s = await open_('SMH');
      ok(s && s.lots[0].y.join(' ') === '配当: 直近12か月に支払いなし' && !/0\.00%/.test(s.full), '直近12か月に支払いが無い＝「配当なし」と書く（0%と書かない）');
      s = await open_('6146');
      ok(s && /評価額）: 1\.58%/.test(s.lots[0].y.join(' ')) && /取得額）: 2\.00%/.test(s.lots[0].y.join(' ')), `日本株（円）は為替を掛けない: 600÷38,000＝1.58%・600×10÷300,000＝2.00%（${s && s.lots[0].y.join(' ')}）`);
      s = await open_('EURX');
      ok(s && /^配当利回り: —/.test(s.lots[0].y[0]), `配当の通貨（EUR）が株価の通貨（USD）と違えば「—」（換算を黙ってしない）（${s && s.lots[0].y[0]}）`);
      s = await open_('NODV');
      ok(s && /^配当利回り: —/.test(s.lots[0].y[0]) && /取れていません/.test(s.lots[0].y[0]), '配当の実績が取れていない銘柄は「—（取れていません）」（0%と読まない）');
      s = await open_('IFREE-NDX');
      ok(s && s.sec === '投資信託' && /対象外（投資信託）/.test(s.lots[0].y[0]) && /前日比: —/.test(s.sub[1]), `投資信託は配当「対象外」・前日比「—」（${s && s.lots[0].y[0]}）`);
      ok(s && /¥58,668\/万口/.test(s.info) && /保有 100,000口/.test(s.info), `基準価額は1万口あたり・単位は「口」（${s && s.info}）`);
      s = await open_('OVER');
      ok(s && /取得失敗＝前回値/.test(s.note), '配当が取得失敗の前回値なら、その旨を注記に出す');
      await ctx.close();
      const o2 = await open({ noDiv: true }); await showDash(o2.p, pfOf(POS), true);
      await o2.p.evaluate(() => ccfHoldOpen('MSFT')); await o2.p.waitForTimeout(250);
      s = await sheet(o2.p);
      ok(s && s.lots.every(l => /^配当利回り: —（配当の実績が取れていません）$/.test(l.y.join(' '))), '配当のファイルが読めない日は全部「—」（0%にしない）');
      await o2.ctx.close();
    }

    console.log('■ F. 閉じる（←・Esc・端末の戻る）');
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      const st = () => p.evaluate(() => ({ on: !!(document.getElementById('pfdSheet') || {}).classList && document.getElementById('pfdSheet').classList.contains('on'), lock: document.documentElement.classList.contains('pfd-open'), hist: history.length, hs: !!(history.state && history.state.ccfPfd) }));
      await p.click('#pfcCard .pfc-r[data-t="MSFT"]'); await p.waitForTimeout(250);
      let a = await st(); ok(a.on && a.lock && a.hs, '開く: シートが出て・背景を固定・戻る用の履歴が1件入る');
      await p.click('.pfd-back'); await p.waitForTimeout(350);
      a = await st(); ok(!a.on && !a.lock && !a.hs, '← で閉じる（固定が外れ・履歴も戻る）');
      await p.click('#pfcCard .pfc-r[data-t="XLK"]'); await p.waitForTimeout(250);
      await p.goBack(); await p.waitForTimeout(350);
      a = await st(); ok(!a.on && !a.lock, '端末の「戻る」でも閉じる');
      const url = p.url();
      await p.click('#pfcCard .pfc-r[data-t="SMH"]'); await p.waitForTimeout(250);
      await p.keyboard.press('Escape'); await p.waitForTimeout(350);
      a = await st(); ok(!a.on && !a.lock && !a.hs && p.url() === url, 'Esc で閉じる（別のページへ戻ってしまわない）');
      await p.click('#pfcCard .pfc-r[data-t="MSFT"]'); await p.waitForTimeout(250);
      await p.click('.pfd-edit'); await p.waitForTimeout(500);
      const e = await p.evaluate(() => ({ page: window.__ccfPage, on: document.getElementById('pfdSheet').classList.contains('on') }));
      ok(e.page === 7 && !e.on, `「✎ 株数・買値を編集」で詳細を閉じて編集の画面（7）へ（${e.page}）`);
      await ctx.close();
    }

    console.log('■ G. 金額を隠す');
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), false);
      await p.click('#pfcCard .pfc-r[data-t="MSFT"]'); await p.waitForTimeout(300);
      let s = await sheet(p);
      ok(s && !/¥[0-9]/.test(s.full), '隠すと ¥数字 が1つも残らない');
      ok(s && /保有 •株/.test(s.info) && s.lots.every(l => /^•株/.test(l.qty)), `株数も隠す（株数×株価で金額が出るため）（${s && s.info}）`);
      ok(s && /\d+\.\d\d%/.test(s.sub[0]) && /0\.73%/.test(s.full), '％（損益・前日比・配当利回り）は出したまま');
      ok(s && s.lots[2].memo === false, '古い記録の「記録のメモ」（株数・金額が書かれていることがある）は、隠している間は出さない');
      await p.evaluate(() => ccfHoldOpen('MEMO')); await p.waitForTimeout(250);
      let m = await sheet(p);
      ok(m && !/2株|¥50|50,000/.test(m.lots[0].cap) && /金額を隠している間は出しません/.test(m.lots[0].cap) && !/メモ:|1株売却/.test(m.note), `記録の文から取った見出しも、持ち物のメモも、隠している間は出さない（${m && m.lots[0].cap}）`);
      await p.evaluate(() => ccfHoldOpen('OVER')); await p.waitForTimeout(250);
      m = await sheet(p);
      ok(m && m.warn.length === 1 && /一部売却/.test(m.warn[0]) && !/[0-9]/.test(m.warn[0]), `一部売却のあとの注意書きにも株数を出さない（${m && m.warn[0] && m.warn[0].slice(0, 30)}…）`);
      await p.evaluate(() => ccfHoldOpen('MSFT')); await p.waitForTimeout(250);
      await p.click('.pfd .ccf-money-btn'); await p.waitForTimeout(1600);
      s = await sheet(p);
      ok(s && /¥600,000/.test(s.tot) && /保有 8株/.test(s.info) && s.lots[2].memo === true, 'シートの中の「金額を表示」で、開いたまま金額が出る（描き直される・メモも戻る）');
      await ctx.close();
    }

    console.log('■ H. 自動の描き直し（保有が書き換わったら、操作なしで全部）');
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      await p.evaluate(() => { window.__n = { dash: 0, plan: 0 }; const d = window.ccfDash; window.ccfDash = async function () { window.__n.dash++; return d.apply(this, arguments); };
        const r = window.renderPlan; if (r) window.renderPlan = async function () { window.__n.plan++; return r.apply(this, arguments); }; });
      await p.click('#pfcCard .pfc-r[data-t="MSFT"]'); await p.waitForTimeout(300);
      // ① 人が株数を増やした（買い増し）→ 開いたシートが 9株 になる・カードの合計も変わる
      await p.evaluate((pf) => { const o = JSON.parse(JSON.stringify(pf)); const m = o.positions.find(x => x.t === 'MSFT'); m.sh = 9; m.bjpy += 80000;
        m.bdLots.push({ sh: 1, jpy: 80000, bd: '2026-10-10', who: 'A', acct: '成長', src: 'x' }); localStorage.setItem('pf:portfolio', JSON.stringify(o)); }, pfOf(POS));
      await p.waitForTimeout(1500);
      let s = await sheet(p), card = await p.evaluate(() => document.querySelector('#pfcCard .pfc-c2').textContent);
      ok(s && /保有 9株/.test(s.info) && money(s.tot) === 9 * 500 * FX && s.lots.length === 4, `開いたままのシートが自動で 9株・4口座に（${s && s.info}・${s && s.lots.length}行）`);
      const expTot = Math.round(9 * 500 * FX + 24 * 200 * FX + 4 * 610 * FX + 100000 * 5.8668 + 3 * 100 * FX + 5 * 100 * FX + 10 * 38000 + 100 * FX + 100 * FX + 2 * 100 * FX);
      ok(card === '¥' + expTot.toLocaleString('en-US'), `カードの合計も同時に変わる（${card} ＝ 独立に足した ¥${expTot.toLocaleString('en-US')}）`);
      const bar = await p.evaluate(() => (document.getElementById('stateBar') || {}).innerText || '');
      ok(/株数が未書き出し/.test(bar), `赤い帯も記録した直後に判定し直される（何が未書き出しかを名指し）（${bar.replace(/\s+/g, ' ').slice(0, 40)}…）`);
      // ② 機械の書き戻し（盤の株価・ドル円だけ）では描き直さない
      const n0 = await p.evaluate(() => window.__n.dash);
      await p.evaluate(() => { const o = JSON.parse(localStorage.getItem('pf:portfolio')); o.fx = 151.5; o.positions.forEach(x => { x.npx = 123.45; x.npxAuto = true; }); localStorage.setItem('pf:portfolio', JSON.stringify(o)); });
      await p.waitForTimeout(700);
      const n1 = await p.evaluate(() => window.__n.dash);
      ok(n1 === n0, `機械の書き戻し（npx・npxAuto・fx）だけなら描き直さない（ccfDash ${n0}→${n1}）`);
      // ③ 売却記録だけが変わっても描き直す
      await p.evaluate(() => localStorage.setItem('pf:sold', JSON.stringify([{ t: 'ZZZ', sh: 1, date: '2026-10-10' }])));
      await p.waitForTimeout(700);
      ok(await p.evaluate(() => window.__n.dash) > n1, '売却記録(pf:sold)が変わっても描き直す');
      // ④ 別の文書（🏦保有の iframe・別のタブ）が書いた分は storage イベントで拾う
      const p2 = await ctx.newPage(); await p2.route('**/*', r => /out\/dashboard\.json/.test(r.request().url()) ? jr(r, DASH()) : r.continue());
      await p2.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' }); await p2.waitForTimeout(1200);
      await p2.evaluate(() => localStorage.setItem('pf:showMoney', '1'));    // 門は開いた時に金額を隠す（共有の鍵を '0' へ戻す）ので、出し直す
      await p.waitForTimeout(600);
      await p2.evaluate(() => { const o = JSON.parse(localStorage.getItem('pf:portfolio')); o.positions.find(x => x.t === 'MSFT').sh = 10; o.positions.find(x => x.t === 'MSFT').bjpy += 1; localStorage.setItem('pf:portfolio', JSON.stringify(o)); });
      await p.waitForTimeout(1600);
      s = await sheet(p);
      ok(s && /保有 10株/.test(s.info), `別のタブが書いた保有の変更も、開いているシートに自動で届く（${s && s.info}）`);
      await p2.close();
      // ⑤ 見えているタブだけを重く描き直す: 買付順位（5）を開いているとき
      await p.evaluate(() => { ccfHoldClose(); showPage(5); }); await p.waitForTimeout(2500);
      const q0 = await p.evaluate(() => window.__n.plan);
      await p.evaluate(() => { const o = JSON.parse(localStorage.getItem('pf:portfolio')); o.positions.find(x => x.t === 'MSFT').sh = 11; o.positions.find(x => x.t === 'MSFT').bjpy += 1; localStorage.setItem('pf:portfolio', JSON.stringify(o)); });
      await p.waitForTimeout(2500);
      ok(await p.evaluate(() => window.__n.plan) > q0, '買付順位（5）を見ているときに保有が変わると、買付順位も自動でつくり直される');
      // ⑥ 売り切る（保有から外れる）→ 開いているシートは閉じる
      await p.evaluate(() => { showPage(6); }); await p.waitForTimeout(1500);
      await p.evaluate(() => ccfHoldOpen('SMH')); await p.waitForTimeout(250);
      await p.evaluate(() => { const o = JSON.parse(localStorage.getItem('pf:portfolio')); o.positions = o.positions.filter(x => x.t !== 'SMH'); localStorage.setItem('pf:portfolio', JSON.stringify(o)); });
      await p.waitForTimeout(1500);
      ok((await sheet(p)) === null && await p.evaluate(() => !document.documentElement.classList.contains('pfd-open')), '開いている銘柄を売り切って保有から外れると、シートは閉じる（空の画面を残さない）');
      await ctx.close();
    }

    console.log('■ I. 鍵の撤去');
    {
      const { p, ctx } = await open({ token: true }); await showDash(p, pfOf(POS), true);
      const r = await p.evaluate(() => ({ api: ['pushRepo', 'setToken', 'hasToken'].filter(k => typeof ccfState[k] !== 'undefined'), tok: localStorage.getItem('ccf:ghToken'),
        src: [...document.querySelectorAll('script')].map(s => s.textContent).join('\n') }));
      ok(r.api.length === 0, `ccfState に 鍵の道（pushRepo / setToken / hasToken）は無い（${r.api.join(',') || 'なし'}）`);
      ok(r.tok === null, '過去に端末へ置かれた鍵（ccf:ghToken）は、読み込み時に消える');
      ok(!/ghp_FIXTURE|鍵を設定して反映する|鍵を入れ直す|ccfState\.setToken|ccfState\.pushRepo/.test(r.src), 'ページの中に「鍵を設定して反映する」の入口（setToken / pushRepo の呼び出し）は無い');
      await p.evaluate(() => { const d = document.createElement('div'); d.id = 'trAfter'; document.body.appendChild(d); ccfTradeAfter('買い QQQM 1株'); });
      await p.waitForTimeout(1500);
      const t = await p.evaluate(() => document.getElementById('trAfter').innerText);
      ok(/この端末の保有に反映しました/.test(t) && /📈成績/.test(t) && !/鍵を設定|鍵を入れ直|🔑|トークン/.test(t) && /鍵は要りません/.test(t),
         `記録のあとの案内は「鍵を置く道」を勧めない（鍵は要りません）・何が自動で何が待つかを言う（${t.replace(/\s+/g, ' ').slice(0, 70)}…）`);
      ok(/Submit new issue/.test(t) && /GitHub を開いて反映する|書き出す/.test(t), '待つのは成績だけ・入れる道は「GitHub を開いて反映する」（Issue 経由・v9.9.210）か「📤 書き出す」');
      await ctx.close();
    }

    console.log('■ J. 📈成績の先頭の差の表示（成績は repo の保有で CI が計算する）');
    {
      const mkRet = (rows) => Object.assign({}, RET, { generated: '2026-10-09', positions: rows });
      const same = RET.positions.map(r => ({ t: r.t, nm: r.nm, sh: r.sh }));
      const devPos = (over) => RET.positions.map(r => ({ t: r.t, nm: r.nm, sleeve: r.sleeve || 'castle', kind: r.sleeve === 'net' ? 'ETF' : '個別', ccy: r.ccy || 'USD', sh: r.sh, bjpy: r.cost_jpy, bd: r.bd, npx: 0, v: 0 })).map(over || (x => x));
      // 同じ → 出さない
      let o = await open({ returns: Object.assign({}, RET) }); await showDash(o.p, pfOf(devPos()), true);
      await o.p.evaluate(() => showPage(12)); await o.p.waitForTimeout(1800);
      ok(await o.p.evaluate(() => !document.getElementById('perfSync')), '株数が同じなら差の表示は出さない');
      // 違い（株数が違う・端末にだけある・売却済み）
      await o.p.evaluate(() => { const x = JSON.parse(localStorage.getItem('pf:portfolio')); x.positions.find(p => p.t === 'XLK').sh += 2; x.positions = x.positions.filter(p => p.t !== 'ASML'); x.positions.push({ t: 'NEWC', nm: 'New Co', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 3, bjpy: 1000, npx: 0, v: 0 }); localStorage.setItem('pf:portfolio', JSON.stringify(x)); });
      await o.p.waitForTimeout(1800);
      let h = await o.p.evaluate(() => { const e = document.getElementById('perfSync'); return e ? e.innerText.replace(/\s+/g, ' ') : null; });
      const xr = RET.positions.find(r => r.t === 'XLK').sh;
      ok(h && /この成績は repo の保有で計算されていて、この端末の保有と違います/.test(h), '違いがあれば先頭に「この端末の保有と違います」');
      ok(h && h.includes(`XLK：${xr}株 → ${xr + 2}株（+2株）`) && /NEWC：この端末にだけある/.test(h) && /ASML：この端末では保有から外れている（売却済み）/.test(h), `銘柄名で3種類の違いを言う（${h && h.slice(40, 190)}…）`);
      ok(h && h.includes('成績の計算日 ' + RET.generated), `成績の計算日を出す（${RET.generated}）`);
      ok(h && /Submit new issue/.test(h) && /鍵は要りません/.test(h), '未書き出しの決定があるとき（この記録は dirty）は「GitHub で Submit new issue を1回押す」（鍵は要りません）と案内する');
      await o.p.evaluate(() => { localStorage.removeItem('ccf:stateDirty'); ccfPerf(); }); await o.p.waitForTimeout(1500);
      h = await o.p.evaluate(() => { const e = document.getElementById('perfSync'); return e ? e.innerText.replace(/\s+/g, ' ') : null; });
      ok(h && /この端末の記録は repo と同じです/.test(h) && !/書き出す/.test(h), '未書き出しが無いなら「成績の計算が追いついていないだけ（3〜5分）」と案内する');
      await o.p.evaluate(() => { localStorage.setItem('pf:showMoney', '0'); ccfPerf(); }); await o.p.waitForTimeout(1500);
      h = await o.p.evaluate(() => { const e = document.getElementById('perfSync'); return e ? e.innerText.replace(/\s+/g, ' ') : null; });
      ok(h && /XLK：株数が違う/.test(h) && !new RegExp('(?<![0-9-])' + (xr + 2) + '(?![0-9-])').test(h), `金額を隠している間は株数も出さない（${h && h.slice(40, 120)}…）`);
      await o.ctx.close();
      // 成績が読めない／行に株数が無い → 何も言わない（断定しない）
      o = await open({ returns: 'none' }); await showDash(o.p, pfOf(devPos()), true);
      await o.p.evaluate(() => showPage(12)); await o.p.waitForTimeout(1500);
      ok(await o.p.evaluate(() => !document.getElementById('perfSync')), '成績のファイルが読めない日は、違うとも同じとも言わない');
      await o.ctx.close();
      o = await open({ returns: mkRet(same.map(r => ({ t: r.t, nm: r.nm }))) }); await showDash(o.p, pfOf(devPos()), true);
      await o.p.evaluate(() => showPage(12)); await o.p.waitForTimeout(1500);
      ok(await o.p.evaluate(() => !document.getElementById('perfSync')), '成績の行に株数が無い銘柄は比べない（測れないものを違いと断定しない）');
      await o.ctx.close();
    }

    console.log(`■ K. 携帯幅（${W}px）で横にはみ出さない・文字が重ならない`);
    {
      const { p, ctx } = await open(); await showDash(p, pfOf(POS), true);
      for (const t of ['MSFT', 'XLK', 'IFREE-NDX', 'OVER', 'PART']) {
        await p.evaluate(t => ccfHoldOpen(t), t); await p.waitForTimeout(250);
        const r = await p.evaluate(() => { const el = document.getElementById('pfdSheet'); const bad = [...el.querySelectorAll('.pfd-lot')].filter(l => { const a = l.querySelector('.pfd-ll').getBoundingClientRect(), b = l.querySelector('.pfd-lr').getBoundingClientRect(); return a.right > b.left + 1; }).length;
          return { sw: el.scrollWidth, cw: el.clientWidth, bad }; });
        ok(r.sw <= r.cw && r.bad === 0, `${t}: シートの幅 ${r.sw}/${r.cw}・左右の列が重ならない（重なり ${r.bad}）`);
      }
      await ctx.close();
    }
  } finally {
    console.log(errs.length ? '\n' + errs.join('\n') : '\n（ページ内のJSエラーなし）');
    await browser.close(); srv.kill();
  }
  console.log(`\n結果: ✓ ${pass} / ✗ ${fail}${errs.length ? ` / JSエラー ${errs.length}` : ''}`);
  process.exit(fail || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
