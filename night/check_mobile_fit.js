#!/usr/bin/env node
/**
 * night/check_mobile_fit.js — **携帯の幅で門が画面に収まるかを実測する**（2026-08-08新設）
 *
 * なぜ要るか（ユーザーの画面写真「画面を常に合わせない」）:
 *   Ⅵ買付順位の注記に `white-space:nowrap` が掛かっていて、**幅576pxの一行**ができていた。
 *   文書幅が 605px へ広がり、**ブラウザがページ全体を 59% に縮めて表示**していた
 *   （＝内容が画面の左6割に寄り、右4割にブラウザの地色が出る）。
 *
 *   **この事故は「台帳が空のままでは絶対に見えない」。** 実際、私は先に9タブ全部を
 *   走査して「はみ出しゼロ」と報告したが、それは**データを入れていなかったから**だった。
 *   注記は投下可の行にしか出ないので、369銘柄を取り込んで初めて現れる。
 *   CLAUDE.md が既に同じ型を記録している——「行内の長い注記は nowrap がインラインで
 *   指定されていて縮まず、画面外へ出ていた（**データを入れて初めて出る**）」。
 *   同じ轍を三度踏まないための道具。
 *
 * 何をするか:
 *   1. ローカルに静的サーバを立て、実ブラウザ（Chromium）を **360px 幅**で開く
 *   2. **⭳全パック一括取込を実行**して台帳を実データで満たす
 *   3. 各タブで `documentElement.scrollWidth === clientWidth` を検査
 *   4. 破れたら**はみ出している要素を名指しで出す**（タグ・class・幅・本文の先頭）
 *
 * 前提: playwright と Chromium。この repo の CI には入れていない（ブラウザ依存が重いため）。
 *   手元で回すときは `npm i playwright`（Chromium は /opt/pw-browsers に同梱）。
 *
 * 使い方: node night/check_mobile_fit.js [--width 360] [--keep]
 *   終了コード 1 = はみ出しあり（＝ブラウザがページを縮めて表示する状態）
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
const argv = process.argv.slice(2);
const W = argv.includes('--width') ? Number(argv[argv.indexOf('--width') + 1]) : 360;
const PORT = 8971;
// ★タブの一覧は**決め打ちにしない**（2026-08-17 に構造で塞いだ）。
//   旧実装は配列に書き写しており、頭注自身が「足し忘れると新しいタブだけ検査されない」と
//   警告していた——**v9.9.140 の 📋今日 で実際に踏み、9本を検査して「全タブ✓」と出た**＝穴が緑に見える。
//   注意力に頼る限り必ず再発するので、**実ブラウザの nav から読む**形にした。
//   ⚠ 読めなければ 0本で「✓」と言わずに**落とす**（測っていないことを問題なしと言わない）。
//   ⚠**v9.9.171 でナビを 6群 + 章立てに分けた瞬間、この関数は 6本しか返さなくなった**——
//     `.pgnav` は群のボタン(grp1..6)で、**ページ(pg1..12)は #chapNav の側にある**。
//     気づかずに回すと「全タブ✓」と出るのに 6ページが一度も測られない＝**穴が緑に見える**。
//     ⇒ **ページの数(.pg)と突き合わせて、足りなければ落とす**（注意力ではなく構造で塞ぐ）。
async function tabsFromDom(p) {
  const r = await p.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('#chapNav button, .pgnav button'))
      .filter(b => /^tab\d+$/.test(b.id))
      .map(b => [b.id, (b.textContent || '').replace(/\s+/g, ' ').trim()]);
    return { btn, pages: document.querySelectorAll('div.pg').length };
  });
  if (!r.btn.length) throw new Error('nav からタブを1つも読めない——検査が成立しないので落とす');
  if (r.btn.length < r.pages)
    throw new Error(`nav から読めたタブ ${r.btn.length}本 < ページ ${r.pages}枚`
      + '——**測れていないページがある**。tabN のボタンを持つ nav を全部見ること');
  return r.btn;
}

(async () => {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch (e) { console.error('playwright が無い。`npm i playwright` を実行すること（Chromium は /opt/pw-browsers）'); process.exit(2); }

  const srv = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1500));
  let bad = 0;
  // v9.9.140: **/opt/pw-browsers はこの開発環境の同梱物で、GitHub Actions の ubuntu-latest には無い。**
  //   決め打ちだと CI では起動に失敗し、`continue-on-error` + `| tail` で緑のまま素通りしていた
  //   （実測: 唯一のCI実行で当該stepは5秒＝369件の取込が終わる時間ではない）。
  //   **在るときだけ使い、無ければ playwright の既定（npx playwright install で入る）に任せる。**
  const _EXE = '/opt/pw-browsers/chromium';
  const browser = await chromium.launch(fs.existsSync(_EXE) ? { executablePath: _EXE } : {});
  try {
    const p = await browser.newPage({ viewport: { width: W, height: 760 }, deviceScaleFactor: 2 });
    p.on('pageerror', e => { console.log('  PAGEERROR', e.message); bad++; });
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2500);

    // 台帳を実データで満たす——**これをやらないと注記の行が存在せず、検査が素通りする**
    await p.evaluate(() => document.getElementById('tab3').click());
    await p.waitForTimeout(600);
    await p.evaluate(() => ccfImportAllPacks({ textContent: '', disabled: false }));
    let n = 0;
    for (let i = 0; i < 40; i++) {
      await p.waitForTimeout(5000);
      n = await p.evaluate(() => Object.keys(localStorage).filter(k => k.startsWith('g7:')).length);
      if (n >= 300) break;
    }
    console.log(`■ 携帯幅 ${W}px で門が収まるか（台帳 ${n} 件を取り込んで実測）\n`);
    if (n < 100) { console.log('  ⚠ 取込が少ない——out/packs_index.json を確認すること'); }

    const TABS = await tabsFromDom(p);
    console.log(`  （タブ ${TABS.length}本を nav から読んだ: ${TABS.map(x => x[0]).join(' ')}）\n`);
    const sunkAll = new Set();
    for (const [id, label] of TABS) {
      await p.evaluate(i => { const e = document.getElementById(i); e && e.click(); }, id);
      await p.waitForTimeout(2200);
      const r = await p.evaluate(() => {
        const de = document.documentElement, out = [];
        document.querySelectorAll('*').forEach(el => {
          const s = getComputedStyle(el);
          if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'fixed') return;
          if (el.closest('.pgnav')) return;          // タブバーは overflow-x:auto で意図的に横スクロール
          const b = el.getBoundingClientRect();
          if (b.width > 0 && b.right > de.clientWidth + 2)
            out.push({ tag: el.tagName, cls: String(el.className || '').slice(0, 24),
                       w: Math.round(b.width), right: Math.round(b.right),
                       ws: s.whiteSpace, txt: (el.textContent || '').trim().slice(0, 44) });
        });
        out.sort((a, c) => c.right - a.right);
        return { sw: de.scrollWidth, cw: de.clientWidth, n: out.length, top: out.slice(0, 5) };
      });
      /* ★2026-08-24新設: **門の別ページへの導線が折り畳みの中に飲み込まれていないか**。
         v9.9.171/172 で説明を畳んだとき、chomirai/v10/portfolio/ami への
         **唯一の入口を5本まとめて「詳しく」の中へ隠した**——字を減らすつもりが機能を隠した
         （「成績はどこへ？」とまったく同じ形）。畳み器の側にも F.pressables() の検問を入れたが、
         **JS が実行時に組み立てる節はそこを通らない**ので、描いた後の DOM でも数える。
         ⚠ details の中でも **open なら見えている**ので、閉じているものだけを数える。 */
      const sunk = await p.evaluate(() => {
        const out = [];
        document.querySelectorAll('a[href$=".html"]').forEach(a => {
          const d = a.closest('details');
          if (d && !d.open) out.push(a.getAttribute('href') + ' ← 「'
            + (d.querySelector('summary') || {}).textContent + '」の中');
        });
        return out;
      });
      sunk.forEach(x => sunkAll.add(`${label}: ${x}`));
      const ok = r.sw <= r.cw + 1;
      if (!ok) bad++;
      console.log(`  ${ok ? '✓' : '✗'} ${label.padEnd(12)} scrollW=${r.sw} / 画面=${r.cw}`
        + (ok ? '' : `　→ **ブラウザは全体を ${(r.cw / r.sw * 100).toFixed(0)}% へ縮めて表示する**`));
      // 収まっている場合は要素を出さない——`table.dt{overflow-x:auto}` の中の行など、
      // **枠内で横スクロールする意図的なはみ出し**まで並べると、本物の事故が埋もれる
      if (!ok) r.top.forEach(x => console.log(`       ${x.tag}.${x.cls} 幅${x.w} 右端${x.right} white-space:${x.ws}\n         「${x.txt}」`));
    }
    console.log(bad ? `\n✗ ${bad}件。長い注記の white-space:nowrap を外し、割ってはいけない数字の対だけを守ること`
                    : '\n✓ 全タブで文書幅が画面幅に収まっている（ブラウザの縮小表示は起きない）');

    if (sunkAll.size) {
      bad += sunkAll.size;
      console.log(`\n✗ **門の別ページへの導線が畳みの中に沈んでいる ${sunkAll.size}件**`
        + '——字を減らすつもりが**機能を隠している**。<details> の**手前**へ出すこと');
      for (const x of sunkAll) console.log('     ' + x);
    } else {
      console.log('✓ 門の別ページへの導線は、どれも折り畳みの外にある');
    }

    // ── ★タブが全部見えているか（v9.9.157）──────────────────────────────
    //   ⚠**この検査が無かったせいで、Ⅵ買付順位とⅦ保有が画面外に出たまま出荷された**
    //     （ユーザー報告「買付順位などが消えてる」）。`.pgnav` は自分で overflow-x:auto を
    //     持つので**文書幅は広がらない**——上の検査は構造的に素通りする。
    //   「押せる場所にあるか」は幅とは別の問いなので、別に数える。
    console.log('\n■ タブが全部見えているか（ナビの折り返し）');
    for (const W2 of [360, 390, 430, 768, 980, 1280]) {
      const p2 = await browser.newPage({ viewport: { width: W2, height: 760 } });
      await p2.goto(`http://localhost:${PORT}/index.html`, { waitUntil: "domcontentloaded" });
      await p2.waitForTimeout(700);
      // ★**群を切り替えて章のナビも実際に出す**——既定の群（📋今日）は章が1本しかなく
      //   ナビ自体が display:none なので、切り替えないと**章のボタンを一度も測らない**。
      const r = await p2.evaluate(() => {
        const n = document.querySelector('.pgnav');
        if (!n) return { no: true };
        const nr = n.getBoundingClientRect(), hid = [];
        // ★群のナビ（.pgnav）と**章のナビ（#chapNav）の両方**を見る。
        //   章のナビは今の群のボタンだけを出すので、display:none のものは数えない。
        const boxes = [n, document.getElementById('chapNav')].filter(Boolean);
        boxes.forEach(box => {
          const br = box.getBoundingClientRect();
          [...box.querySelectorAll('button')].forEach(b => {
            if (b.offsetParent === null) return;      // その群でないタブは出ていなくて正しい
            const q = b.getBoundingClientRect();
            if (q.left < br.left - 1 || q.right > br.right + 1 || q.top < br.top - 1 || q.bottom > br.bottom + 1)
              hid.push(b.textContent.trim());
          });
        });
        // ★浮いているボタンがナビに重なっていないか。ナビの高さは折り返しで変わるので、
        //   固定値で逃がしていると必ずどこかの幅で重なる（実測: 74px 固定のまま2段=118pxになった）
        const t = document.getElementById('themeToggle');
        let ov = null;
        if (t) {
          const a = t.getBoundingClientRect();
          for (const box of boxes) {
            const br = box.getBoundingClientRect();
            if (br.height && !(a.right < br.left || a.left > br.right || a.bottom < br.top || a.top > br.bottom))
              ov = 'themeToggle';
          }
        }
        const shown = boxes.reduce((c, b) => c + [...b.querySelectorAll('button')].filter(x => x.offsetParent !== null).length, 0);
        const hh = boxes.reduce((c, b) => c + Math.round(b.getBoundingClientRect().height), 0);
        return { n: shown, hid, h: hh, ov, over: n.scrollWidth - n.clientWidth };
      });
      // 群を1つずつ開いて、章のボタンがナビの箱に収まっているか
      const gbad = [], gskip = [];
      let gok = 0;
      for (let g = 1; g <= 6; g++) {
        const q = await p2.evaluate(gg => {
          if (typeof showGroup !== 'function') return { skip: 'showGroup が無い' };
          showGroup(gg);
          const box = document.getElementById('chapNav');
          if (!box) return { skip: '#chapNav が無い' };
          /* ★2026-08-24 是正: ここは `box.offsetParent === null` で見えるかを判定していた。
             だが #chapNav は 640px 以下で position:fixed になり、
             **fixed の要素は（見えていても）offsetParent が null を返す**。
             ＝携帯の幅では6群ぜんぶが黙って skip され、それでも ✓ が出ていた。
             night/check_navstack.js の頭注が名指ししているのと同じ罠を、この道具が踏んでいた。
             見えているかは **computed の display/visibility/opacity と実寸**で見る。 */
          const cs = getComputedStyle(box);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0)
            return { skip: `章の帯が出ていない(${cs.display}/${cs.visibility}/${cs.opacity})` };
          const br = box.getBoundingClientRect();
          if (!br.width || !br.height) return { skip: '章の帯の実寸が 0' };
          const out = [];
          [...box.querySelectorAll('button')].forEach(b => {
            const bs = getComputedStyle(b);
            if (bs.display === 'none' || bs.visibility === 'hidden') return;
            const a = b.getBoundingClientRect();
            if (!a.width || !a.height) return;
            if (a.left < br.left - 1 || a.right > br.right + 1 || a.top < br.top - 1 || a.bottom > br.bottom + 1)
              out.push(b.textContent.trim());
          });
          return { hid: out, h: Math.round(br.height) };
        }, g);
        // ★測れなかったことを黙って飲み込まない（ルール7: 「測っていない」を「異常なし」と言わない）
        if (!q || q.skip) { gskip.push(`群${g}: ${(q && q.skip) || '評価できない'}`); continue; }
        gok++;
        if (q.hid.length) gbad.push(`群${g}: ${q.hid.join(' | ')}`);
      }
      if (gskip.length) {
        // 6群ぜんぶ測れなかった＝この幅の章の帯を一度も検査していない。✓ を出してはいけない
        if (gok === 0) { bad++; console.log(`  ✗ ${W2}px: **章の帯を6群とも測れなかった**——「異常なし」ではない（${gskip[0]}）`); }
        else console.log(`  ⚠ ${W2}px: 章の帯を測れなかった群 ${gskip.length}件（${gskip.join(' ／ ')}）`);
      }
      await p2.close();
      if (gbad.length) { bad++; console.log(`  ✗ ${W2}px: **章のタブが画面外**（${gbad.join(' ／ ')}）`); }
      if (r.no) { bad++; console.log(`  ✗ ${W2}px: .pgnav が無い`); }
      else if (r.hid.length) {
        bad++;
        console.log(`  ✗ ${W2}px: **${r.hid.length}本が画面外**（${r.hid.join(' | ')}）`
                  + ` ——横スクロールすれば届くが「消えた」と読まれる`);
      } else if (r.ov) {
        bad++;
        console.log(`  ✗ ${W2}px: **${r.ov} がナビに重なっている**（押せないタブができる）`);
      } else console.log(`  ✓ ${W2}px: ${r.n}本すべて見える（ナビの高さ ${r.h}px）・浮きボタンの重なりなし`
                       + `・章の帯 ${gok}/6群を実測`);
    }
  } finally {
    await browser.close();
    srv.kill();
  }
  process.exit(bad ? 1 : 0);
})();
