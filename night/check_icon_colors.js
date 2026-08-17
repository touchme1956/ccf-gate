#!/usr/bin/env node
/**
 * night/check_icon_colors.js — **全タブの行に、目録どおりの色が乗っているか**（2026-08-17新設・v9.9.152）
 *
 * ■ なぜ要るか（ユーザー報告「新しく入った銘柄に色がない。追加した場合でも全タブで色が変わるようにして」）
 *   色が出ない事故は二つの経路で起きた。**どちらもコードを読んでも見つからない種類**:
 *    ① 採取の側: fetch_logos が index.json を作り直して logo_colors の測定値を捨て、
 *       さらに Pillow 不在で PNG が測れず「測れなかった」を「色なし」として上書きしていた
 *       （実測 2026-08-17: 色あり 318 → 104）。→ night/logo_colors.py 側の検問で塞いだ。
 *    ② 表示の側: 目録は fetch で**後から**届くのに、起動時に描かれるタブ（Ⅳ台帳など）は
 *       描き直されないので、**間に合ったタブだけ色が付く**。＝「タブによって色がある/ない」。
 *   ②は「たまたま間に合えば緑になる」ので、**目録の到着を意図的に遅らせて測る**しかない。
 *
 * ■ 何を測るか
 *   ① 目録に色がある銘柄の行に、実際に光（.tgrad の background）が乗っているか——**全タブ**
 *   ② 目録を3秒遅らせても①が成り立つか（＝ccfIconRepaint が塗り直しているか）
 *   ③ Ⅶ資産（iframe・portfolio.html）でも成り立つか——**両ページが同じ実装を読んでいるか**の実測
 *   ④ pageerror
 *   **判定は作らない**（Ω・関門・売却規律・配分には触れない）。表示だけを見る。
 *
 * ■ ブラウザが無ければ skip（exit 0）。**skipしたことは必ず印字する**
 *   ——playwright が無いことと「色が付いている」ことは別物（ルール7）。
 *
 * 使い方: node night/check_icon_colors.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
const PORT = 8731;

// 各タブ: [id, 名前]。ここに無いタブは測らないので、タブを増やしたら足すこと
const TABS = [[10, '今日'], [6, '盤'], [9, '自動化'], [11, '点検'], [1, '解説'], [8, '実行手順'],
  [2, '採点機'], [3, '台帳'], [4, '検証履歴'], [5, '買付順位'], [7, '保有']];

const probe = () => {
  // 行の光は「.tico[data-ic] の直前の .tgrad の background」。
  // 目録に色がある銘柄でここが空なら、それが**色が乗っていない行**。
  // ⚠ **`window.CCF_LOGO` では読めない**——トップレベルの let はグローバル**オブジェクト**の
  //   プロパティにならない（グローバル字句環境に入る）。初版はこれで undefined を掴み、
  //   「色があるのに乗っていない行」を数える分母が空になって**空虚な合格**を出した
  //   ＝この台帳が繰り返し戒めている「0は測定ではないことがある」。読めなければ失格にする。
  let have = null;
  try { have = (typeof CCF_LOGO !== 'undefined' && CCF_LOGO) ? CCF_LOGO : null; } catch (e) { have = null; }
  const out = { tabs: {}, noIdx: !have, nIdx: have ? Object.keys(have).length : 0 };
  have = have || {};
  for (const pg of document.querySelectorAll('.pg')) {
    const id = pg.id.replace('pg', '');
    let n = 0, lit = 0, miss = [];
    for (const sp of pg.querySelectorAll('.tico[data-ic]')) {
      const t = sp.getAttribute('data-ic'); const m = have[t] || {};
      const g = sp.previousElementSibling;
      const bg = (g && g.classList && g.classList.contains('tgrad')) ? (g.style.background || '') : '';
      n++;
      if (bg) lit++;
      if (m.c && !bg && miss.length < 6) miss.push(t);
    }
    if (n) out.tabs[id] = { n, lit, miss };
  }
  return out;
};

(async () => {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch (e) {
    console.log('■ 行の彩色の検査: **skip**（playwright が無い）');
    console.log('  ⚠これは「色が付いている」ではなく「測っていない」。CIでは npx playwright install chromium で入る');
    process.exit(0);
  }
  let idx;
  try { idx = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'logos', 'index.json'), 'utf8')).have || {}; }
  catch (e) { console.log('⚠ out/logos/index.json が読めない＝比較の錨が無い'); process.exit(1); }
  const nColor = Object.values(idx).filter(v => v && v.c).length;

  const srv = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1500));
  const EXE = '/opt/pw-browsers/chromium';
  const browser = await chromium.launch(fs.existsSync(EXE) ? { executablePath: EXE } : {});
  let bad = 0;
  try {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const errs = [];
    const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(e.message.slice(0, 140)));
    console.log(`■ 行の彩色の検査（目録: 色あり ${nColor}/${Object.keys(idx).length}銘柄）`);

    // ── 準備: 台帳を本番と同じ状態にする（⭳全パック一括取込）
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2500);
    await p.evaluate(() => { const t = document.getElementById('tab3'); if (t) t.click(); });
    await p.waitForTimeout(500);
    await p.evaluate(() => (typeof ccfImportAllPacks === 'function' ? ccfImportAllPacks() : null));
    let prev = -1, stable = 0;
    for (let i = 0; i < 90; i++) {
      await p.waitForTimeout(2000);
      const n = await p.evaluate(() => { let c = 0; for (let i = 0; i < localStorage.length; i++) if (localStorage.key(i).startsWith('g7:')) c++; return c; });
      if (n === prev) { if (++stable >= 3) break; } else { stable = 0; prev = n; }
    }
    console.log(`  台帳 ${prev}件を取り込んだ`);

    // ── ①②: **目録を3秒遅らせて**読み込み直す＝起動時に描かれるタブが間に合わない状況を作る
    await p.route('**/out/logos/index.json', async route => {
      await new Promise(r => setTimeout(r, 3000));
      await route.continue();
    });
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(1200);
    const early = await p.evaluate(probe);
    console.log(`  目録の到着前: 光っている行 ${Object.values(early.tabs).reduce((a, b) => a + b.lit, 0)}件`
      + `（**ここが0なのは正常**——まだ目録が無い）`);
    await p.waitForTimeout(4000);            // 目録が届く＋塗り直し
    for (const [id, nm] of TABS) {
      await p.evaluate(i => { const t = document.getElementById('tab' + i); if (t) t.click(); }, id);
      await p.waitForTimeout(id === 5 ? 5000 : 900);
    }
    await p.waitForTimeout(800);
    const late = await p.evaluate(probe);
    if (late.noIdx) {
      bad++;
      console.log('  ✗ **目録を読めていない**（CCF_LOGO が空）——この検査は何も証明していない。'
        + 'out/logos/index.json が配信されているか確認せよ');
    } else {
      console.log(`  目録を読めた: ${late.nIdx}銘柄（＝「色があるのに乗っていない」を数える分母がある）`);
    }
    let tot = 0, lit = 0, badTabs = [];
    for (const [id, nm] of TABS) {
      const r = late.tabs[id]; if (!r) continue;
      tot += r.n; lit += r.lit;
      if (r.miss.length) { badTabs.push(`${nm}(pg${id}): ${r.miss.join(' ')}`); }
      console.log(`    ${nm.padEnd(6)} 行 ${String(r.n).padStart(4)} / 光 ${String(r.lit).padStart(4)}`
        + (r.miss.length ? `  ✗ 色があるのに乗っていない: ${r.miss.join(' ')}` : ''));
    }
    if (badTabs.length) { bad++; console.log(`  ✗ **目録の色が行に届いていないタブ ${badTabs.length}**`); }
    else console.log(`  ✓ 全タブ: 目録に色がある行はすべて光っている（合計 行${tot} / 光${lit}）`);
    if (lit === 0) { bad++; console.log('  ✗ 光っている行が0件＝塗り直しが働いていない'); }

    // ── ③ Ⅶ資産（iframe・portfolio.html）——両ページが同じ実装を読んでいるか
    await p.evaluate(() => { const t = document.getElementById('tab7'); if (t) t.click(); });
    await p.waitForTimeout(3500);
    // ⚠ pfShow() が iframe を読み直すので、**掴んだ frame が入れ替わる**。
    //   落ち着くまで待って取り直す（初版はここで detached な frame を測り「未定義」と誤報した）。
    let fr = null;
    for (let i = 0; i < 25; i++) {
      fr = p.frames().find(f => /portfolio\.html/.test(f.url()));
      // ⚠ 待つのは「関数が在る」ではなく「**目録を読み終えた**」まで。
      //   pfShow() が毎回 iframe を読み直すので、関数の存在だけで測ると
      //   読み直し直後（fetch がまだ返っていない）を掴んで「目録を読めていない」と誤報する。
      // ⚠ readyState は待たない——portfolio.html は Google Fonts を読むので、
      //   外へ出られない環境では 'loading' のまま9秒ほど留まる（実測）。門の表示には関係ない。
      if (fr) {
        try {
          if (await fr.evaluate(() => typeof ccfIcon === 'function'
            && typeof CCF_LOGO !== 'undefined' && CCF_LOGO && Object.keys(CCF_LOGO).length > 0)) break;
        } catch (e) { fr = null; }
      }
      await p.waitForTimeout(1000);
    }
    if (!fr) { bad++; console.log('  ✗ Ⅶ資産の iframe を測れなかった（＝色が付いている証拠が無い）'); }
    else {
      const pf = await fr.evaluate(() => {
        let have = null;
        try { have = (typeof CCF_LOGO !== 'undefined' && CCF_LOGO) ? CCF_LOGO : null; } catch (e) { have = null; }
        const noIdx = !have; have = have || {};
        let n = 0, lit = 0, miss = [];
        for (const sp of document.querySelectorAll('.tico[data-ic]')) {
          const m = have[sp.getAttribute('data-ic')] || {};
          const g = sp.previousElementSibling;
          const bg = (g && g.classList && g.classList.contains('tgrad')) ? (g.style.background || '') : '';
          n++; if (bg) lit++;
          if (m.c && !bg && miss.length < 6) miss.push(sp.getAttribute('data-ic'));
        }
        return { n, lit, miss, noIdx, fn: typeof ccfIcon === 'function', rp: typeof ccfIconRepaint === 'function' };
      });
      if (!pf.fn || !pf.rp) { bad++; console.log('  ✗ Ⅶ資産で ccfIcon / ccfIconRepaint が未定義（icon.js を読めていない）'); }
      else if (pf.noIdx) { bad++; console.log('  ✗ Ⅶ資産が目録を読めていない（この行の合否は証明できない）'); }
      else if (pf.miss.length) { bad++; console.log(`  ✗ Ⅶ資産: 色があるのに乗っていない ${pf.miss.join(' ')}`); }
      else console.log(`  ✓ Ⅶ資産（別ページ・同じ icon.js）: 行 ${pf.n} / 光 ${pf.lit}`);
    }

    // ── ④ pageerror
    if (errs.length) { bad++; console.log(`  ✗ pageerror ${errs.length}件: ` + errs.slice(0, 3).join(' | ')); }
    else console.log('  ✓ pageerror 0');
  } finally {
    await browser.close();
    try { srv.kill(); } catch (e) {}
  }
  process.exit(bad ? 1 : 0);
})();
