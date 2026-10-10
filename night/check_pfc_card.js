#!/usr/bin/env node
/**
 * night/check_pfc_card.js — 🏦保有の「ポートフォリオ」カード（v9.9.204）を実ブラウザで検査する
 *
 * 何のカードか: 🏦保有の先頭（金額を隠すボタンの行の下）に出る、円グラフ・年初来比・評価損益・銘柄ごとの内訳（index.html の ccfPfcHTML）。
 *   v9.9.208 で「総資産」の大きな見出し（.rb-hero）は外した。見出しが持っていた 金額を隠す切替・含み損益の対象外の銘柄名 の行き先も L で見る。
 *   **表示だけ**——Ω・四関門・売却規律・配分に触れない。数字は ccfDash の集計をそのまま渡している。
 *
 * ★データは**この検査の中で固定**する（保有5銘柄・価格・年初来比の系列を route で差し替える）。
 *   repo の state.json / out/dashboard.json は毎日変わるので、それを読むと「先頭は XLK」のような断定が日々壊れる。
 *   カードの**式と振る舞い**を測る検査であって、今日の数字を測る検査ではない。
 *
 * 見ること:
 *   A 円グラフ（円の数・長さの合計＝周−隙間・12時から・評価額順・割合の合計100%・年初来比「--%」・横にはみ出さない）
 *   B ⋮メニュー（開く・並び替え3通り・選ぶと閉じる・外側クリック・Esc・並びが残る）
 *   C 金額を隠す（¥数字がカードに1つも残らない・％は出したまま）
 *   D シェア（割合だけ・金額が入らない・共有シートが無ければクリップボード＋ひとこと）
 *   E 価格が取れない（前日比は「—」・0%と読まない）
 *   F 投資信託の行（前日比「—」）・評価額が出せない行（注記で名指し・円グラフに入れない）・系列に無い銘柄があれば年初来比は「—」
 *   G 年初来比（去年の系列があれば 今の評価額 − 去年末の評価額・％も出る）
 *   H 保有が空ならカードを出さない  I 1銘柄だけなら全周の1つの円
 *   J 為替込みの前日比（v9.9.205・fx.prev があるとき）: 合計・うち為替・各行を**独立に計算した値**と突き合わせる／円建ての行は為替の影響を受けない
 *   K fx.prev が無い・取得失敗の据え置き（stale）の日は株価だけ（画面にそう書く）
 *   L 総資産の見出しを外した（v9.9.208）: 見出しが出ない・金額を隠すボタンは右寄せの1行で残る（押すと隠れる／出る）・
 *     取得額が無い銘柄の名前はカードの注記へ・保有が空ならボタンも出さない
 *
 * 使い方: NODE_PATH=$(npm root -g) node night/check_pfc_card.js [--width 360]
 *   前提: playwright と Chromium。終了コード 1 = 1件でも ✗。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const argv = process.argv.slice(2);
const W = argv.includes('--width') ? Number(argv[argv.indexOf('--width') + 1]) : 360;
const PORT = 8981;
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓ ' + m); } else { fail++; console.log('  ✗ ' + m); } };

// ── 固定のデータ（円＝株数×ドル価格×150）
const FX = 150;
const POS = [
  { t: 'MSFT', nm: 'Microsoft', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 8, bjpy: 497469, bd: '2026-04-15', npx: 0, v: 0 },
  { t: 'ASML', nm: 'ASMLホールディングス', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 1, bjpy: 226006, bd: '2026-04-08', npx: 0, v: 0 },
  { t: 'XLK', nm: 'XLK テクノロジーセレクトセクターSPDR', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 24, bjpy: 679758, bd: '2026-06-17', npx: 0, v: 0 },
  { t: 'SMH', nm: 'ヴァンエック・半導体株ETF', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 4, bjpy: 362153, bd: '2026-06-22', npx: 0, v: 0 },
  { t: 'QQQM', nm: 'インベスコ NASDAQ 100 ETF', sleeve: 'net', kind: 'ETF', ccy: 'USD', sh: 8, bjpy: 382617, bd: '2026-07-23', npx: 0, v: 0 },
];
const PX = { MSFT: [500, -1.9608], ASML: [1500, 0.5], XLK: [200, -1.0], SMH: [610, -3.0], QQQM: [300, 0.0] };
// 評価額: MSFT 600,000 / ASML 225,000 / XLK 720,000 / SMH 366,000 / QQQM 360,000 ＝ 2,271,000
const TOT = 2271000;
const DASH = (o = {}) => ({ asof: '2026-10-09T01:00:00+00:00', fx: Object.assign({ USDJPY: FX }, o.fx || {}), news: {},
  quotes: Object.assign(Object.fromEntries(Object.entries(PX).map(([t, [px, c]]) => [t, { px, prev: px / (1 + c / 100), chgPct: c, src: 'fixture' }])), o.q || {}) });
const SERIES = (extra) => {
  const days = ['2026-04-08', '2026-10-08'], val = [225000, 2200000];
  const s = { days, val, inv: [226006, 2148003], tr: val.slice(), bmk: [226006, 2100000], tickers: POS.map(p => p.t), n: 5, base_ccy: 'JPY' };
  if (extra) { s.days = extra.days.concat(s.days); s.val = extra.val.concat(s.val); s.inv = extra.val.concat(s.inv); s.tr = s.val.slice(); s.bmk = s.val.slice(); }
  return s;
};
const jr = (r, o) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(o) });

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
    const ctx = await browser.newContext({ viewport: { width: W, height: 900 }, deviceScaleFactor: 1 });
    await ctx.addInitScript(() => { try { localStorage.setItem('ccf_theme', 'light'); } catch (e) {} });
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push('PAGEERROR ' + e.message));
    await p.route('**/*', r => {
      const u = r.request().url();
      if (/out\/dashboard\.json/.test(u)) return o.noDash ? r.fulfill({ status: 404, body: '' }) : jr(r, DASH(o));
      if (/out\/returns_series\.json/.test(u)) return jr(r, SERIES(o.prevYear));
      return r.continue();
    });
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2000);
    return { p, ctx };
  }
  async function showDash(p, pf, money) {
    await p.evaluate(([pf, money]) => {
      try { localStorage.setItem('pf:showMoney', money ? '1' : '0'); } catch (e) {}
      localStorage.setItem('pf:portfolio', JSON.stringify(pf));
      showPage(6);
    }, [pf, money]);
    await p.waitForTimeout(1400);
  }
  const base = { asof: '2026-10-09', fx: FX, positions: POS };
  const open_ = async p => p.evaluate(() => document.getElementById('pfcMenu').classList.contains('on'));

  try {
    console.log(`■ A. 円グラフと数字（保有5銘柄・金額を出す・幅${W}px）`);
    {
      const { p, ctx } = await open(); await showDash(p, base, true);
      const a = await p.evaluate(() => {
        const c = document.getElementById('pfcCard'); if (!c) return null;
        const segs = [...c.querySelectorAll('.pfc-ring circle')], C = 2 * Math.PI * 100;
        const lens = segs.map(s => parseFloat(s.getAttribute('stroke-dasharray').split(' ')[0]));
        const ps = c.querySelectorAll('.pfc-sc .p');
        return { n: segs.length, sum: lens.reduce((x, y) => x + y, 0), C, off0: parseFloat(segs[0].getAttribute('stroke-dashoffset')),
          rows: [...c.querySelectorAll('.pfc-n')].map(e => e.textContent), centre: c.querySelector('.pfc-c2').textContent,
          share: [...c.querySelectorAll('.pfc-w')].reduce((s, e) => s + parseFloat(e.textContent.replace(/[^0-9.]/g, '')), 0),
          ytdP: ps[0].textContent, plP: ps[1].textContent, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
      });
      ok(a && a.n === 5, '円グラフは5つの円');
      ok(a && Math.abs(a.sum - (a.C - 5 * 2)) < 0.5, `円の長さの合計 ＝ 周 − 隙間2px×5（${a && a.sum.toFixed(1)}）`);
      ok(a && a.off0 < 0 && a.off0 > -2, '最初の円は12時の位置から（dashoffset ≈ −1）');
      ok(a && a.rows.join('/') === 'XLK/Microsoft/SMH/QQQM/ASMLホールディングス', `評価額の大きい順（${a && a.rows.join('/')}）`);
      ok(a && Math.abs(a.share - 100) < 0.3, `割合の合計は100%（${a && a.share.toFixed(1)}）`);
      ok(a && a.centre === '¥2,271,000', `合計（${a && a.centre}）`);
      ok(a && a.ytdP === '--%', '年初来比の％は「--%」（今年に買い始めた＝年初の評価額0）');
      ok(a && /^[−]?\d+\.\d\d%$/.test(a.plP), `評価損益の％（${a && a.plP}）`);
      ok(a && a.sw <= a.cw, `横にはみ出さない（${a && a.sw}/${a && a.cw}）`);
      const n0 = await p.evaluate(() => document.querySelector('.pfc-note').innerText);
      ok(/株価だけ/.test(n0) && /為替は含まない/.test(n0), 'fx.prev が無い日のカードの注記は「株価だけ・為替は含まない」（為替を黙って0と読まない）');
      await ctx.close();
    }

    console.log('■ B. ⋮メニューと並び替え');
    {
      const { p, ctx } = await open(); await showDash(p, base, true);
      const first = () => p.evaluate(() => document.querySelector('.pfc-n').textContent);
      await p.click('.pfc-kebab');
      ok(await open_(p), '⋮ でメニューが開く');
      await p.click('#pfcMenu button:has-text("前日比の高い順")'); await p.waitForTimeout(200);
      ok(await first() === 'ASMLホールディングス', `前日比の高い順の先頭は ASML（${await first()}）`);
      ok(!(await open_(p)), '並びを選ぶとメニューは閉じる');
      ok(await p.evaluate(() => localStorage.getItem('pf:pfcSort')) === 'day', '並びは localStorage(pf:pfcSort) に残る');
      ok(await p.evaluate(() => document.querySelectorAll('.pfc-ring circle').length) === 5, '並びを替えても円グラフはそのまま');
      await p.click('.pfc-kebab'); await p.click('#pfcMenu button:has-text("損益率の高い順")'); await p.waitForTimeout(200);
      ok(await first() === 'Microsoft', `損益率の高い順の先頭は Microsoft（${await first()}）`);
      await p.click('.pfc-kebab'); await p.click('#pfcMenu button:has-text("評価額の大きい順")'); await p.waitForTimeout(200);
      ok(await first() === 'XLK', '評価額の大きい順へ戻る');
      await p.click('.pfc-kebab'); await p.mouse.click(10, 300);
      ok(!(await open_(p)), '外側をクリックすると閉じる');
      await p.click('.pfc-kebab'); await p.keyboard.press('Escape');
      ok(!(await open_(p)), 'Esc で閉じる');
      await ctx.close();
    }

    console.log('■ C. 金額を隠す（メニューから）');
    {
      const { p, ctx } = await open(); await showDash(p, base, true);
      await p.click('.pfc-kebab'); await p.click('#pfcMenu button:has-text("金額を隠す")'); await p.waitForTimeout(1400);
      const r = await p.evaluate(() => { const c = document.getElementById('pfcCard').cloneNode(true);
        const fx = (c.querySelector('.pfc-fx') || {}).textContent || ''; c.querySelectorAll('.pfc-fx').forEach(e => e.remove());
        return { txt: c.innerText, fx, key: localStorage.getItem('pf:showMoney') }; });
      ok(r.key === '0', 'pf:showMoney=0（隠す）になる');
      ok(!/¥[0-9]/.test(r.txt), '保有の金額は ¥数字 が1つも残らない（ドル円の行は市場の値なので除く）');
      ok(/ドル円 ¥150\.00/.test(r.fx), 'ドル円は保有の金額ではないので、隠してもそのまま出る');
      ok(/\d+\.\d\d%/.test(r.txt) && /割合/.test(r.txt), '％（評価損益・割合）は出したまま');
      await ctx.close();
    }

    console.log('■ D. シェア（割合だけ）');
    {
      const { p, ctx } = await open(); await showDash(p, base, true);
      await p.evaluate(() => { window.__shared = null; navigator.share = async d => { window.__shared = d; }; });
      await p.click('.pfc-share'); await p.waitForTimeout(200);
      const sh = await p.evaluate(() => window.__shared);
      ok(sh && /ポートフォリオ/.test(sh.text), '共有シートへ文が渡る');
      ok(sh && !/¥|円/.test(sh.text) && !/\d{4,}/.test(sh.text.replace(/\d{4}-\d{2}-\d{2}/, '')), '金額が入っていない');
      ok(sh && /XLK 31\.7%/.test(sh.text) && /前日比/.test(sh.text) && /評価損益/.test(sh.text), `割合・前日比・評価損益の％が入っている（${sh && JSON.stringify(sh.text).slice(0, 60)}…）`);
      await p.evaluate(() => { navigator.share = undefined; window.__clip = null; Object.defineProperty(navigator, 'clipboard', { value: { writeText: async t => { window.__clip = t; } }, configurable: true }); });
      await p.click('.pfc-share'); await p.waitForTimeout(300);
      const t = await p.evaluate(() => { const e = document.getElementById('pfcToast'); return { clip: window.__clip, toast: e && e.textContent, on: !!(e && e.classList.contains('on')) }; });
      ok(t.clip && /ポートフォリオ/.test(t.clip), '共有シートが無ければクリップボードへ書く');
      ok(t.on && /コピー/.test(t.toast), `ひとこと（${t.toast}）`);
      await ctx.close();
    }

    console.log('■ E. 価格が取れない（out/dashboard.json が無い）');
    {
      const { p, ctx } = await open({ noDash: true }); await showDash(p, { ...base, positions: POS.map(x => ({ ...x, npx: 100 })) }, true);
      const r = await p.evaluate(() => { const c = document.getElementById('pfcCard'); return c ? { days: [...c.querySelectorAll('.pfc-dd')].map(e => e.textContent), c4: c.querySelector('.pfc-c4').textContent.trim() } : null; });
      ok(r !== null, '価格が無くてもカードは出る（手入力の現値で評価）');
      ok(r && r.days.length === 5 && r.days.every(d => /—/.test(d)), '前日比は全行「—」（0%と読まない）');
      ok(r && r.c4 === '—', `合計の前日比も「—」（${r && r.c4}）`);
      await ctx.close();
    }

    console.log('■ F. 投資信託の行・評価額が出せない行・系列に無い銘柄');
    {
      const { p, ctx } = await open();
      const pf = JSON.parse(JSON.stringify(base));
      pf.positions.push({ t: 'IFREE-NDX', nm: 'iFreeNEXT NASDAQ100インデックス', sleeve: 'net', kind: '投資信託', ccy: 'JPY', sh: 1700000, bjpy: 95000, bd: '2026-09-29', npx: 5.8668, v: 0, navPer: 10000 });
      pf.positions.push({ t: 'ZZZZ', nm: '価格なし', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 3, bjpy: 0, bpx: 0, npx: 0, v: 0 });
      await showDash(p, pf, true);
      const r = await p.evaluate(() => { const c = document.getElementById('pfcCard'); if (!c) return null;
        const row = [...c.querySelectorAll('.pfc-r')].find(e => /iFreeNEXT/.test(e.textContent));
        return { fund: row ? row.innerText.replace(/\s+/g, ' ') : null, note: c.querySelector('.pfc-note').innerText, n: c.querySelectorAll('.pfc-ring circle').length,
          ytd: c.querySelectorAll('.pfc-sc .v')[0].innerText.trim(), ytdP: c.querySelectorAll('.pfc-sc .p')[0].innerText }; });
      ok(r && r.fund && /前日比: —/.test(r.fund), `投資信託は前日比「—」（${r && r.fund}）`);
      ok(r && /ZZZZ/.test(r.note), '評価額が出せない銘柄は注記で名指し');
      ok(r && r.n === 6, `円グラフは評価額のある6行（${r && r.n}）`);
      ok(r && r.ytd === '—' && r.ytdP === '--%', `系列に無い銘柄があれば年初来比は測れない「—」（${r && r.ytd}）`);
      await ctx.close();
    }

    console.log('■ G. 年初来比（去年の系列がある）');
    {
      const yr = new Date().getFullYear();
      const { p, ctx } = await open({ prevYear: { days: [`${yr - 1}-12-29`, `${yr - 1}-12-30`], val: [1000000, 1200000] } });
      await showDash(p, base, true);
      const r = await p.evaluate(() => { const c = document.getElementById('pfcCard'); return { v: c.querySelectorAll('.pfc-sc .v')[0].innerText.trim(), p: c.querySelectorAll('.pfc-sc .p')[0].innerText, tot: window.__pfcData.tot }; });
      ok(Math.abs(parseInt(r.v.replace(/[^0-9]/g, ''), 10) - Math.round(r.tot - 1200000)) <= 1, `年初来比 ＝ 今の評価額 − 去年末の評価額 1,200,000（${r.v}）`);
      ok(Math.abs(parseFloat(r.p.replace('−', '-')) - (r.tot / 1200000 - 1) * 100) < 0.01, `％も出る（${r.p}）`);
      await ctx.close();
    }

    console.log('■ H. 保有が空');
    {
      const { p, ctx } = await open(); await showDash(p, { asof: '2026-10-10', fx: FX, positions: [] }, true);
      ok(!(await p.evaluate(() => !!document.getElementById('pfcCard'))), '保有が空ならカードは出さない');
      ok(!(await p.evaluate(() => !!document.querySelector('#dashBox .ccf-money-btn'))), '保有が空なら金額を隠すボタンも出さない（隠す金額が無い）');
      await ctx.close();
    }

    console.log('■ I. 1銘柄だけ');
    {
      const { p, ctx } = await open(); await showDash(p, { ...base, positions: [POS[0]] }, true);
      const r = await p.evaluate(() => ({ n: document.querySelectorAll('.pfc-ring circle').length, da: document.querySelector('.pfc-ring circle').getAttribute('stroke-dasharray'), w: document.querySelector('.pfc-w').textContent }));
      ok(r.n === 1 && parseFloat(r.da.split(' ')[0]) > 620 && /100\.0%/.test(r.w), `全周の1つの円（${r.da}・${r.w}）`);
      await ctx.close();
    }

    // ── 独立な計算（門のコードを写さない）: 各行の 前日の評価額 ＝ 株価を前日へ戻す × ドル円も前日へ戻す（ドル建てだけ）
    const expectDay = (pos, quotes, fxNow, fxPrev) => {
      let day = 0, prevSum = 0, fxJ = 0, priceJ = 0; const rows = {};
      for (const x of pos) {
        const q = quotes[x.t]; if (!q) continue;
        const usd = x.ccy !== 'JPY', k = usd ? fxNow : 1;
        const val = x.sh * q[0] * k;
        const vPx = val / (1 + q[1] / 100);
        const vPrev = usd && fxPrev ? vPx * (fxPrev / fxNow) : vPx;
        day += val - vPrev; prevSum += vPrev; if (usd && fxPrev) fxJ += val * (1 - fxPrev / fxNow);
        // 株価の分（前日のドル円で換算）＝株数×(今の株価−前日の株価)×前日のドル円。前日の株価 ＝ 今の株価 ÷ (1+前日比%)
        priceJ += x.sh * (q[0] - q[0] / (1 + q[1] / 100)) * (usd ? (fxPrev || fxNow) : 1);
        rows[x.kind === 'ETF' ? x.t : x.nm] = [val - vPrev, (val / vPrev - 1) * 100];
      }
      return { day, dayP: day / prevSum * 100, fxJ, priceJ, rows };
    };

    console.log('■ J. 為替込みの前日比（fx.prev がある日）');
    {
      const FXP = 148;
      const JP = { t: '6146', nm: 'ディスコ', sleeve: 'castle', kind: '個別', ccy: 'JPY', sh: 100, bjpy: 3000000, bd: '2026-04-20', npx: 0, v: 0 };
      const pos2 = POS.concat([JP]);
      const q2 = Object.assign({}, PX, { '6146': [38000, 1.0] });
      const { p, ctx } = await open({ fx: { prev: FXP, chgPct: (FX / FXP - 1) * 100, src: 'fixture', asof: '2026-10-09T01:00:00+00:00' },
        q: { '6146': { px: 38000, prev: 38000 / 1.01, chgPct: 1.0, src: 'fixture' } } });
      await showDash(p, { ...base, positions: pos2 }, true);
      const e = expectDay(pos2, q2, FX, FXP);
      const r = await p.evaluate(() => { const c = document.getElementById('pfcCard'), D = window.__pfcData;
        return { fxIn: D.fxIn, day: D.dayJ, dayP: D.dayP, fxJ: D.dayFxJ, sub: [...c.querySelectorAll('.pfc-s')].map(x => x.textContent).join(' | '), note: c.querySelector('.pfc-note').innerText,
                 rows: Object.fromEntries(D.rows.map(x => [x.label, [x.day, x.dayP]])), asof: document.getElementById('dashAsof').innerText }; });
      ok(r.fxIn === true, 'fx.prev があれば為替込み（fxIn）');
      ok(Math.abs(r.day - e.day) < 1, `合計の前日比 ＝ 独立計算（${Math.round(r.day)} / ${Math.round(e.day)}）`);
      ok(Math.abs(r.dayP - e.dayP) < 0.001, `前日比の％（${r.dayP.toFixed(3)} / ${e.dayP.toFixed(3)}）`);
      ok(Math.abs(r.fxJ - e.fxJ) < 1, `うち為替 ＝ 独立計算（${Math.round(r.fxJ)} / ${Math.round(e.fxJ)}）`);
      ok(Math.abs(r.fxJ) > 1 && Math.abs((r.day - r.fxJ) - e.priceJ) < 1, `前日比 ＝ 株価の分（前日のドル円で換算）＋為替の分（${Math.round(e.priceJ)} ＋ ${Math.round(r.fxJ)}）`);
      ok(Object.entries(e.rows).every(([nm, v]) => r.rows[nm] && Math.abs(r.rows[nm][0] - v[0]) < 1 && Math.abs(r.rows[nm][1] - v[1]) < 0.001), '各行の前日比（円・％）が独立計算と一致');
      ok(Math.abs(r.rows['ディスコ'][1] - 1.0) < 1e-6, `円建ての行はドル円の影響を受けない（ディスコ +${r.rows['ディスコ'][1].toFixed(3)}%）`);
      const usdJ = expectDay(POS, PX, FX, FXP).fxJ;
      ok(Math.abs(r.fxJ - usdJ) < 1, '円建ての行を足しても「うち為替」は変わらない');
      ok(/うち為替は \+¥/.test(r.note), 'カードの注記: 「うち為替は +¥…」（総資産の見出しのチップはもう無いので、金額はここで出す）');
      ok(/ドル円 ¥150\.00 \(\+1\.35%\)/.test(r.sub) && /自動更新/.test(r.sub), `カードのドル円の行（${r.sub.split('|')[1].trim()}）`);
      ok(/株価と為替（ドル円）の動き/.test(r.note), 'カードの注記が為替込みになる');
      ok(/前日比 \+1\.35%/.test(r.asof), '上の「市場データ…$1=¥…」の行にも為替の前日比');
      await ctx.close();
    }

    console.log('■ K. fx.prev が無い／据え置き（stale）の日は株価だけ');
    {
      const e0 = expectDay(POS, PX, FX, 0);
      for (const [label, fxo] of [['fx.prev 無し', {}], ['stale', { prev: 148, stale: true }]]) {
        const { p, ctx } = await open({ fx: fxo }); await showDash(p, base, true);
        const r = await p.evaluate(() => { const D = window.__pfcData, c = document.getElementById('pfcCard');
          return { fxIn: D.fxIn, day: D.dayJ, fxJ: D.dayFxJ, note: c.querySelector('.pfc-note').innerText,
                   sub: [...c.querySelectorAll('.pfc-s')].map(x => x.textContent).join(' | '), asof: document.getElementById('dashAsof').innerText }; });
        ok(r.fxIn === false && r.fxJ === 0, `${label}: 為替を含めない（fxIn=false・うち為替0）`);
        ok(Math.abs(r.day - e0.day) < 1, `${label}: 前日比は株価だけの独立計算と一致（${Math.round(r.day)}）`);
        ok(/株価だけ/.test(r.note) && /為替は含まない/.test(r.note), `${label}: 画面に「為替は含まない」と書く`);
        if (fxo.stale) ok(/取得失敗＝前回値/.test(r.sub) && /取得失敗＝前回値/.test(r.asof), 'stale: ドル円の行と上の行に「取得失敗＝前回値」と出す（止まっているのを黙らない）');
        await ctx.close();
      }
    }

    console.log('■ L. 総資産の見出しを外した（v9.9.208）と、見出しにあったものの行き先');
    {
      const pf = JSON.parse(JSON.stringify(base));
      // 取得額（bjpy も bpx も）が無いが価格はある行 → 評価額は合計に入る・評価損益からは外す・名前は注記に出す
      pf.positions.push({ t: 'NOCOST', nm: '取得額なし', sleeve: 'castle', kind: '個別', ccy: 'USD', sh: 2, bjpy: 0, bpx: 0, npx: 100, v: 0 });
      const { p, ctx } = await open(); await showDash(p, pf, true);
      const snap = () => p.evaluate(() => { const b = document.getElementById('dashBox'), c = document.getElementById('pfcCard'), btn = b.querySelector('.ccf-money-btn');
        const cc = c.cloneNode(true); cc.querySelectorAll('.pfc-fx').forEach(e => e.remove());
        return { hero: !!document.querySelector('.rb-hero'), nBtn: b.querySelectorAll('.ccf-money-btn').length, pill: btn ? btn.textContent.trim() : null,
          pillFirst: !!btn && !!(btn.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING),
          pillRight: btn ? getComputedStyle(btn.parentElement).textAlign : null, cardTxt: cc.innerText, note: c.querySelector('.pfc-note').innerText,
          centre: c.querySelector('.pfc-c2').textContent, n: c.querySelectorAll('.pfc-ring circle').length, key: localStorage.getItem('pf:showMoney'),
          sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }; });
      let r = await snap();
      ok(!r.hero, '「総資産」の大きな見出し（.rb-hero）は出ない');
      ok(!/総資産/.test(r.cardTxt), 'カードの中にも「総資産」の文字は無い（真ん中は「合計」）');
      ok(r.nBtn === 1 && r.pill === '🙈 金額を隠す' && r.pillFirst && r.pillRight === 'right', `金額を隠すボタンは右寄せの1行でカードの上に残る（${r.pill}）`);
      ok(/評価損益は取得額が判る銘柄だけ（対象外: NOCOST）/.test(r.note), `取得額が無い銘柄の名前は注記に出る（見出しの「含み損益の対象外」の行き先）`);
      ok(r.n === 6 && /^¥[0-9,]+$/.test(r.centre) && r.centre === '¥' + (2271000 + 2 * 100 * FX).toLocaleString('en-US'), `その行の評価額は合計に入る（${r.centre}・円グラフ${r.n}つ）`);
      ok(r.sw <= r.cw, `横にはみ出さない（${r.sw}/${r.cw}）`);
      await p.click('#dashBox .ccf-money-btn'); await p.waitForTimeout(1400);
      r = await snap();
      ok(r.key === '0' && r.pill === '👁 金額を表示' && !/¥[0-9]/.test(r.cardTxt), `ボタンを押すと金額が隠れ、ボタンは「${r.pill}」になる（カードに ¥数字 なし）`);
      await p.click('#dashBox .ccf-money-btn'); await p.waitForTimeout(1400);
      r = await snap();
      ok(r.key === '1' && r.pill === '🙈 金額を隠す' && /¥[0-9]/.test(r.cardTxt), 'もう一度押すと金額が出る');
      await ctx.close();
    }
  } finally {
    console.log(errs.length ? '\n' + errs.join('\n') : '\n（ページ内のJSエラーなし）');
    await browser.close(); srv.kill();
  }
  console.log(`\n結果: ✓ ${pass} / ✗ ${fail}${errs.length ? ` / JSエラー ${errs.length}` : ''}`);
  process.exit(fail || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
