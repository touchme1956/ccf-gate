#!/usr/bin/env node
/* night/check_fund_cap.js — 注文書の「つみたて投資枠の上限」を実ブラウザで確かめる
 *
 * ■ なぜ要るか
 *   2026-09-28 ユーザー明示指示「つみたて枠を超えた分はQQQMにして」。
 *   注文書は投資信託（iFreeNEXT NASDAQ100）を portfolio.json の
 *   target.ami_funds[本].tsumitate_monthly_cap_jpy（月の上限）までにし、超えた分は overflow_to（QQQM）を丸株で買う。
 *   根拠は歴史検証の穴⑤（out/gaps_cost.json）——つみたて枠の外は iFreeNEXT 0.495% より QQQM 0.15% が安い。
 *
 * ■ 判定
 *   ① 上限を超える月: 投資信託の行はちょうど上限・QQQM の行が出る（株数＝超えた額÷1株の円 の切り捨て）
 *   ② お金が消えない: ETF の行の合計＋残り が ETF の取り分（＋個別の残枠）と100円未満の差で一致する
 *   ③ ◈ ETF の節の QQQM が「今月なし」でなく「つみたて枠を超えた分」と出る（注文書と同じ数字を読む）
 *   ④ 上限に届かない月: QQQM の行は出ない（投資信託の行は按分どおり）
 *   ⑤ overflow_to を消すと上限なしの旧挙動へ戻る＝1語で可逆
 *   ⚠ どの場面も全パックを取り込んで測る（台帳が空だと買付順位は ETF の行を描かない既存の早い道を通る）
 *   ⑥ 携帯の幅（320/360/390px）で注文書がはみ出さない（check_mobile_fit は入金額を入れないので注文書を見ていない）
 *   ⑦ pageerror が出ない
 *   ★上限の額・QQQM の価格は**正本から読む**（書き写さない）。
 *
 * playwright が要るので CI には入れていない。使い方: NODE_PATH=$(npm root -g) node night/check_fund_cap.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8796;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';

let OVER = null;                      // portfolio.json を差し替えて配る（正本は触らない）
const srv = http.createServer((q, r) => {
  const rel = decodeURIComponent(q.url.split('?')[0]);
  if (OVER && rel.endsWith('/portfolio.json')) {
    r.writeHead(200, { 'Content-Type': 'application/json' }); r.end(JSON.stringify(OVER)); return;
  }
  let f = path.join(ROOT, rel);
  if (f.endsWith('/')) f += 'index.html';
  try {
    const b = fs.readFileSync(f);
    r.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'text/javascript'
      : f.endsWith('.json') ? 'application/json' : f.endsWith('.css') ? 'text/css' : 'text/html' });
    r.end(b);
  } catch (e) { r.writeHead(404); r.end('x'); }
});

const yenOf = s => +String(s).replace(/[¥,\s]/g, '');

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const base = JSON.parse(fs.readFileSync(path.join(ROOT, 'portfolio.json'), 'utf8'));
  const FKEY = Object.keys(base.target.ami_funds || {})[0];
  const FUND = (base.target.ami_funds || {})[FKEY] || {};
  const CAP = +FUND.tsumitate_monthly_cap_jpy || 0, OVT = String(FUND.overflow_to || '').toUpperCase();
  const b = await chromium.launch({ executablePath: CHROME });
  const pg = await b.newPage();
  const errs = []; pg.on('pageerror', e => errs.push(String(e)));
  let ng = 0;
  const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

  const load = async (over, packs) => {
    OVER = over;
    await pg.goto('http://localhost:' + PORT + '/index.html');
    await pg.waitForTimeout(1200);
    if (packs) { await pg.evaluate(() => ccfImportAllPacks()); await pg.waitForTimeout(1500); }
  };
  // 入金額を入れて買付順位を描き直し、注文書の数字を読む（表示層の数字＝人が見て発注する数字）
  const plan = async (yen) => pg.evaluate(async ([y, ovt]) => {
    localStorage.setItem('pf:monthly_total', String(y));
    showPage(5);
    await new Promise(r => setTimeout(r, 2600));
    const sp = ccfSleeveSplit();
    const txt = (document.getElementById('pg5') || document.body).innerText;
    // ◈ ETF の節の、その本の行だけ（「ETFの門」の札があるのは節の行だけ）。2026-10-05: 旧の正規表現は 400字の窓で
    //   iFreeNEXT の行の「うち QQQM 15.6%」と「今月 買う」をつないで、QQQM が買われていなくても通っていた
    const sec = [...document.querySelectorAll('#pg5 .led.planrow')].filter(e => { const c = e.querySelector('.bctl');
      return c && c.dataset.t === ovt && /ETFの門/.test(e.innerText); });
    return { net: sp ? sp.net : null, castle: sp ? sp.castle : null, over: JSON.parse(JSON.stringify(window.__ccfNetOver || {})),
             txt, secBuy: sec.length ? /今月 買う/.test(sec[0].innerText) : null };
  }, [yen, OVT]);
  // 注文書の ETF の部分だけを切り出す（見出しだけの行「◈ ETF」から、行頭が「合計」の行まで）
  //   ⚠ 「◈ ETFの門 ↗」（ページ上部のリンク）や割り方の行の「袖の合計で測るなら」に引っかからないよう、行単位で探す
  const etfBlock = t => { const m = t.match(/\n◈ ETF\n([\s\S]*?\n合計[^\n]*)/); return m ? m[1] : ''; };
  // ★v9.9.207: 「金額で買う」の行は暗号資産（BTC・ETH）にもある——投資信託の行（基準価額を出す行）だけを読む
  const fundYen = blk => { const m = blk.match(/¥([\d,]+) 金額で買う\n[^\n]*基準価額/); return m ? yenOf(m[1]) : null; };
  const ovRow = blk => { const m = blk.match(new RegExp(OVT + '[\\s\\S]{0,40}?(\\d+)株[\\s\\S]{0,40}?¥([\\d,]+)[\\s\\S]{0,80}?上限を超えた ¥([\\d,]+)')); return m ? { sh: +m[1], cost: yenOf(m[2]), over: yenOf(m[3]) } : null; };

  console.log('■ つみたて投資枠の上限（night/check_fund_cap.js）');
  console.log(`   正本: ${FKEY} 月の上限 ${CAP.toLocaleString('ja-JP')}円 → 超えた分は ${OVT || '(なし)'}`);
  ok(CAP > 0 && OVT, '正本に上限と超えた分の行き先がある（無ければ以下は旧挙動の検査になる）');

  // ⚠ 台帳が空だと買付順位は早い道（ccfMonthPlanBox([])・ETF の行なし）を通るので、**全部の場面で全パックを取り込む**
  //   （実際の門は台帳が入っている。空の台帳で ETF の注文書が出ないのは今回の変更と無関係の既存の挙動）
  // ★割り方 'cat'（2026-10-05〜・区分の比率が最優先）の合計の行は「（個別株 ¥…／ETF ¥…／投資信託 ¥…）」——3区分の形も読む
  const total = t => { const c = t.match(/合計 約¥([\d,]+)（個別株 ¥([\d,]+)／ETF ¥([\d,]+)／投資信託 ¥([\d,]+)）(?:／残り¥([\d,]+))?/);
    if (c) return { all: yenOf(c[1]), rest: c[5] ? yenOf(c[5]) : 0, line: c[0] };
    const m = t.match(/合計 約¥([\d,]+)（個別 ¥([\d,]+)／ETF ¥([\d,]+)）(?:／残り¥([\d,]+))?/)
                       || t.match(/合計 ¥([\d,]+)(?:／残り¥([\d,]+))?/);
    if (!m) return null; return m.length > 4 ? { all: yenOf(m[1]), rest: m[4] ? yenOf(m[4]) : 0, line: m[0] } : { all: yenOf(m[1]), rest: m[2] ? yenOf(m[2]) : 0, line: m[0] }; };

  // ①②③ 上限を超える月（100万）
  await load(null, true);
  let p = await plan(1000000);
  let blk = etfBlock(p.txt);
  let fy = fundYen(blk), orow = ovRow(blk), tt = total(p.txt);
  console.log(`   100万: 個別 ${Math.round(p.castle)} / ETF ${Math.round(p.net)} → 投資信託 ${fy} / ${OVT} ${orow ? orow.sh + '株 ' + orow.cost + '円（超えた ' + orow.over + '円）' : '(行なし)'} / ${tt ? tt.line : '(合計が読めない)'}`);
  ok(fy === CAP, `① 投資信託の行はちょうど上限（${fy} = ${CAP}）`);
  ok(!!orow && orow.sh >= 1, `① ${OVT} の行が出て1株以上`);
  const pm = blk.match(/上限を超えた ¥[\d,]+[\s\S]{0,80}?1株 \$[\d.,]+≒¥([\d,]+)/), qq = pm ? yenOf(pm[1]) : null;   // 行に出ている1株の円（四捨五入済み）
  ok(!!orow && qq > 0 && Math.abs(orow.sh - orow.over / qq) < 1 && orow.cost <= orow.over && orow.over - orow.cost < qq + 1, `① 株数＝超えた額÷1株の円 の切り捨て（${orow ? orow.over : '?'}÷${qq ? Math.round(qq) : '?'}）`);
  const ov = p.over[OVT];
  ok(!!ov && orow && ov.sh === orow.sh && Math.abs(ov.cost - orow.cost) <= 1, '③ 注文書の数字と window.__ccfNetOver が一致');
  ok(p.secBuy === true && !/つみたて枠/.test(p.txt), `③ ◈ ETF の節の ${OVT} の行が「今月 買う」と出る（${p.secBuy === null ? '行が無い' : p.secBuy ? '今月 買う' : '今月なし'}・つみたて枠の文言は 2026-09-29 に撤去）`);
  ok(!!tt && Math.abs(tt.all + tt.rest - 1000000) < 300, '② お金が消えない（合計＋残り ≒ 入金額・丸めの差 <300円）');

  // ④ 上限に届かない月（5万）
  p = await plan(50000);
  blk = etfBlock(p.txt); fy = fundYen(blk); tt = total(p.txt);
  console.log(`   5万: 投資信託 ${fy} / ${OVT}の行 ${ovRow(blk) ? 'あり' : 'なし'} / ${tt ? tt.line : '(合計が読めない)'}`);
  ok(fy != null && fy <= CAP, '④ 投資信託の行は上限以下');
  ok(!ovRow(blk) && !p.over[OVT], `④ 上限に届かない月は ${OVT} の行が出ない`);
  ok(!!tt && Math.abs(tt.all + tt.rest - 50000) < 300, '④ お金が消えない（5万）');

  // ⑤ overflow_to を消すと旧挙動（上限なし）
  { const o = JSON.parse(JSON.stringify(base)); delete o.target.ami_funds[FKEY].overflow_to;
    await load(o, true); p = await plan(1000000); blk = etfBlock(p.txt); fy = fundYen(blk); tt = total(p.txt);
    console.log(`   overflow_to なし・100万: 投資信託 ${fy} / ${tt ? tt.line : '(合計が読めない)'}`);
    ok(fy != null && fy > CAP && !ovRow(blk), '⑤ overflow_to を消すと上限なし（旧挙動）へ戻る'); }

  // ⑥ 携帯の幅で注文書（上限の注記・QQQM の行）が横にはみ出さない
  //   ⚠ check_mobile_fit.js は入金額を入れないので注文書が描かれず、この行はそちらの視野の外
  for (const W of [320, 360, 390]) {
    const mp = await b.newPage({ viewport: { width: W, height: 760 }, deviceScaleFactor: 2 });
    mp.on('pageerror', e => errs.push(String(e)));
    OVER = null;
    await mp.goto('http://localhost:' + PORT + '/index.html'); await mp.waitForTimeout(1200);
    await mp.evaluate(() => ccfImportAllPacks()); await mp.waitForTimeout(1500);
    const r = await mp.evaluate(async () => {
      localStorage.setItem('pf:monthly_total', '1000000'); showPage(5);
      await new Promise(res => setTimeout(res, 2600));
      const de = document.documentElement, out = [];
      document.querySelectorAll('#pg5 *').forEach(el => {
        const s = getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'fixed') return;
        const bb = el.getBoundingClientRect();
        if (bb.width > 0 && bb.right > de.clientWidth + 2) out.push(`${el.tagName} right${Math.round(bb.right)} 「${(el.textContent || '').trim().slice(0, 30)}」`);
      });
      return { sw: de.scrollWidth, cw: de.clientWidth, has: /上限を超えた/.test(document.getElementById('pg5').innerText), top: out.slice(0, 3) };
    });
    ok(r.has && r.sw <= r.cw + 1 && !r.top.length, `⑥ 幅${W}px で注文書がはみ出さない（scroll ${r.sw} / client ${r.cw}）` + (r.top.length ? ' ' + r.top.join(' ／ ') : ''));
    await mp.close();
  }

  ok(!errs.length, '⑦ pageerror なし' + (errs.length ? '（' + errs.slice(0, 2).join(' / ') + '）' : ''));
  await b.close(); srv.close();
  console.log(ng ? `✗ ${ng}件` : '✓ すべて通過');
  process.exit(ng ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
