#!/usr/bin/env node
/* night/check_auto_import.js — 台帳が空の端末で🛒買付順位が空にならないかを実ブラウザで確かめる（v9.9.217）
 *
 * ■ なぜ要るか（実害から作った検査）
 *   2026-10-12、ユーザー「全然買付順位に出ない」。ホーム画面のアプリ（v9.9.216）は Safari と保存場所（localStorage）が別で、
 *   初めて開くと台帳(g7:)が0件＝🛒買付順位が「🟢投下可なし」だけになり、注文書も出なかった。
 *   未取込の案内は📚台帳のタブにしか無く、買付順位だけ見る人には理由が分からなかった。
 *
 * ■ 判定
 *   ① 台帳が空 → 起動時に全パックを自動で取り込む（ページは移動しない・取り込み中は買付順位に進み具合）
 *      → 終わると買付順位に注文書が出る・赤い帯（未書き出し）は立たない・検証履歴に「自動取込」
 *   ② 自動取込の最中に「⭳ 全パック一括取込」を押す → 2本目は始めずに待つ（パックの取得は1回）
 *      → 台帳の各社がパックの数字のまま（取り込みが重なって別の社の数字で保存されていない）
 *   ③ 台帳に1件でもある → 自動では取り込まない（人が直した値を巻き戻さない）・未取込の帯を🛒買付順位にも出す
 *      → 買付順位の帯から押した取り込みはページを移動しない
 *
 * playwright が要るので CI には入れていない（check_stale_bar.js / check_state_banner.js と同じ扱い）。
 *   使い方: NODE_PATH=$(npm root -g) node night/check_auto_import.js
 */
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');
const ROOT = path.dirname(__dirname), PORT = 8799;
const CHROME = process.env.CHROME_PATH || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome';
const TYPES = { '.js': 'text/javascript', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.svg': 'image/svg+xml', '.css': 'text/css' };

let PACK_DELAY = 0, packFetches = 0;          // パックの取得を遅らせて「取り込み中」の表示を読む・取得の回数を数える
const srv = http.createServer((q, r) => {
  let f = path.join(ROOT, decodeURIComponent(q.url.split('?')[0]));
  if (f.endsWith('/')) f += 'index.html';
  const isPack = /_gate_pack\.json$/.test(f);
  if (isPack) packFetches++;
  const send = () => {
    try { const b = fs.readFileSync(f); r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'text/html' }); r.end(b); }
    catch (e) { r.writeHead(404); r.end('x'); }
  };
  if (isPack && PACK_DELAY) setTimeout(send, PACK_DELAY); else send();
});

let ng = 0;
const ok = (c, m) => { console.log((c ? '  ✓ ' : '  ✗ ') + m); if (!c) ng++; };

(async () => {
  await new Promise(s => srv.listen(PORT, s));
  const b = await chromium.launch({ executablePath: CHROME });
  const URL = 'http://localhost:' + PORT + '/index.html';
  const IDX = JSON.parse(fs.readFileSync(path.join(ROOT, 'out/packs_index.json'), 'utf8')).packs || [];
  const N = IDX.length;
  const waitAuto = async pg => {
    for (let i = 0; i < 120; i++) {
      const st = await pg.evaluate(() => window.__ccfAutoImp);
      if (st === 'done' || st === 'fail') return st;
      await pg.waitForTimeout(1000);
    }
    return 'timeout';
  };
  const ledgerN = pg => pg.evaluate(() => Object.keys(localStorage).filter(k => k.indexOf('g7:') === 0).length);
  console.log('■ 台帳が空の端末の自動取込（night/check_auto_import.js）');

  // ① 台帳が空 → 自動で取り込む
  {
    const pg = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 30; packFetches = 0;
    await pg.goto(URL); await pg.waitForTimeout(1500);
    const startPage = await pg.evaluate(() => window.__ccfPage);
    await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(1200);
    const mid = await pg.evaluate(() => ({ ai: window.__ccfAutoImp, pb: (document.getElementById('planBox') || {}).innerText || '',
      bar5: (document.getElementById('packFreshBar5') || {}).innerText || '' }));
    ok(mid.ai && typeof mid.ai === 'object', '① 台帳が空 → 起動時に自動取込が始まる（' + JSON.stringify(mid.ai) + '）');
    ok(/台帳がまだ空です/.test(mid.pb) && /自動で取り込んでいます/.test(mid.pb), '   取り込み中の🛒買付順位は理由と進み具合を出す（「投下可なし」だけにしない）');
    ok(/自動で取り込んでいます/.test(mid.bar5) && !/いま取り込む/.test(mid.bar5), '   🛒買付順位の帯も「取り込み中」（押すボタンは出さない）');
    const st = await waitAuto(pg);
    await pg.waitForTimeout(2500);
    const after = await pg.evaluate(() => {
      const t = (document.querySelector('#pg5') || {}).innerText || '';
      const sb = document.getElementById('stateBar');
      return { page: window.__ccfPage, order: /📋 今月の注文書/.test(t), empty: /台帳が空/.test(t),
        dirty: (window.ccfState && ccfState.isDirty) ? ccfState.isDirty() : null,
        sb: sb ? (sb.innerText || '').trim() : '',
        bar5: getComputedStyle(document.getElementById('packFreshBar5')).display,
        logs: Object.keys(localStorage).filter(k => k.indexOf('g7log:') === 0).map(k => JSON.parse(localStorage.getItem(k)).title) };
    });
    const n = await ledgerN(pg);
    ok(st === 'done' && n === N, '   取り込み終了 ' + st + '・台帳 ' + n + '/' + N + '社');
    ok(startPage === 10 && after.page === 5, '   ページは移動しない（起動 ' + startPage + '・人が開いた 5 のまま → ' + after.page + '）');
    ok(after.order && !after.empty, '   終わると🛒買付順位に今月の注文書が出る（作り直しは自動）');
    ok(after.bar5 === 'none', '   未取込の帯は消える');
    ok(after.dirty === false && !/書き出/.test(after.sb), '   赤い帯（未書き出し）は立たない（台帳と検証履歴は人の決定ではない）');
    ok(after.logs.length === 1 && /自動取込（台帳が空だった）/.test(after.logs[0]), '   検証履歴に「自動取込（台帳が空だった）」が1件');
    ok(packFetches === N, '   パックの取得は ' + packFetches + ' 件（各1回）');
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  // ② 自動取込の最中に一括取込を押す → 待つだけ・台帳は各社のパックの数字のまま
  {
    const pg = await (await b.newContext()).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 0; packFetches = 0;
    await pg.goto(URL); await pg.waitForTimeout(2500);
    const mid = await pg.evaluate(() => window.__ccfAutoImp);
    await pg.evaluate(() => ccfImportAllPacks());      // 人が📚台帳の「⭳ 全パック一括取込」を押したのと同じ
    const st = await waitAuto(pg);
    await pg.waitForTimeout(1500);
    const recs = await pg.evaluate(() => {
      const o = {};
      for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.indexOf('g7:') === 0) o[k] = JSON.parse(localStorage.getItem(k)); }
      return o;
    });
    const packByNm = {};
    for (const f of IDX) { const p = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); const d = p.data || p; if (d.nm) packByNm[String(d.nm).trim()] = d; }
    let checked = 0; const bad = [];
    for (const [k, rec] of Object.entries(recs)) {
      const d = rec.data || {}; const p = packByNm[String(d.nm || '').trim()]; if (!p) continue; checked++;
      for (const f of ['roic', 'irr', 'per', 'dom', 'moatW', 'nde']) {
        const a = d[f] == null ? '' : String(d[f]), e = p[f] == null ? '' : String(p[f]);
        if (e !== '' && a !== '' && parseFloat(a) !== parseFloat(e)) { bad.push(k + ' ' + f + ' ' + a + '≠' + e); break; }
      }
    }
    ok(mid && typeof mid === 'object', '② 自動取込の最中に一括取込を押す（' + JSON.stringify(mid) + '）');
    ok(st === 'done' && packFetches === N, '   2本目は始めずに待つ（パックの取得 ' + packFetches + ' 件＝1回分）');
    ok(Object.keys(recs).length === N && checked === N && bad.length === 0,
      '   台帳 ' + Object.keys(recs).length + '社・パックと突き合わせた ' + checked + '社で数字の食い違い ' + bad.length + '件' + (bad.length ? '（' + bad.slice(0, 3).join(' / ') + '）' : ''));
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  // ③ 台帳に1件でもある → 自動では取り込まない・帯を🛒買付順位にも出す・そこから押してもページは移動しない
  {
    const pg = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
    const errs = []; pg.on('pageerror', e => errs.push(String(e)));
    PACK_DELAY = 0;
    // 1社だけ入っている台帳を作る。⚠ 門を開くと（台帳が空なので）その場で自動取込が始まり前提が崩れる——
    //   門を開かずに同じ出所の JSON を開いて保存場所だけ触る（鍵は門の safeKey と同じ規則＝取り込むと同じ鍵を上書きする）
    const one = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', IDX[0]), 'utf8'));
    const od = one.data || one, nm = String(od.nm || IDX[0]);
    const data = {}; Object.keys(od).forEach(k => { const v = od[k]; if (v !== null && v !== undefined && typeof v !== 'object') data[k] = String(v); });
    data.nm = nm;
    await pg.goto('http://localhost:' + PORT + '/out/packs_index.json');
    await pg.evaluate(([k, data]) => { localStorage.clear(); localStorage.setItem(k, JSON.stringify({ data: data, r: {} })); },
      ['g7:' + nm.replace(/[\s\/\\'"]+/g, '_'), data]);
    packFetches = 0;
    await pg.goto(URL); await pg.waitForTimeout(3000);
    const n0 = await ledgerN(pg);
    const st0 = await pg.evaluate(() => window.__ccfAutoImp);
    await pg.evaluate(() => showPage(5)); await pg.waitForTimeout(2500);
    const bar5 = await pg.evaluate(() => { const e = document.getElementById('packFreshBar5'); return { shown: getComputedStyle(e).display !== 'none', t: e.innerText }; });
    ok(n0 === 1 && st0 === null && packFetches === 0, '③ 台帳に1件 → 自動では取り込まない（台帳 ' + n0 + '社・自動取込 ' + JSON.stringify(st0) + '・取得 ' + packFetches + '件）');
    ok(bar5.shown && /台帳に入っていないパックが/.test(bar5.t) && /いま取り込む/.test(bar5.t) && /買付順位にも出ない/.test(bar5.t),
      '   🛒買付順位にも未取込の帯（理由と「⭳ いま取り込む」）');
    await pg.evaluate(() => { const btn = document.querySelector('#packFreshBar5 button'); btn && btn.click(); });
    for (let i = 0; i < 120; i++) { await pg.waitForTimeout(1000); if ((await ledgerN(pg)) >= N && !(await pg.evaluate(() => window.__ccfImpRun))) break; }
    await pg.waitForTimeout(2500);
    const after = await pg.evaluate(() => ({ page: window.__ccfPage, order: /📋 今月の注文書/.test((document.querySelector('#pg5') || {}).innerText || ''),
      bar5: getComputedStyle(document.getElementById('packFreshBar5')).display }));
    ok((await ledgerN(pg)) === N && after.page === 5 && after.order && after.bar5 === 'none',
      '   帯から押すと全部取り込み、ページは🛒買付順位のまま・注文書が出て帯は消える（page ' + after.page + '）');
    ok(errs.length === 0, '   pageerror 0件' + (errs.length ? '（' + errs[0].slice(0, 120) + '）' : ''));
  }

  await b.close(); srv.close();
  console.log(ng ? '\n✗ ' + ng + '件 失敗' : '\n✓ 全項目 通過');
  process.exit(ng ? 1 : 0);
})();
