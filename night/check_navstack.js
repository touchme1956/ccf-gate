#!/usr/bin/env node
/**
 * night/check_navstack.js — **二段ナビ（群＋章）が壊れていないか**（v9.9.173新設）
 *
 * ■ なぜ要るか（実害が出たので作った）
 *   v9.9.171 で12タブを6群へ畳んだとき、章の帯（群の中の切替）を**本文の頭に静的に置いた**。
 *   ところが携帯では群ナビが position:fixed;bottom:0 になる。実測:
 *     **群ナビ y=742〜844（画面の下） / 章の帯 y=6（画面の最上部）**
 *   ＝**押す場所と、現れる場所が画面の反対側**。ユーザーの報告は「成績はどこへ？」だった。
 *   さらに既定の📋今日は章が1つなので帯ごと display:none で、
 *   **起動直後の画面に二段目が存在すること自体が一度も出なかった**。
 *
 *   なぜ既存の検査を素通りしたか:
 *    ・check_mobile_fit は「文書幅が画面に収まるか」と「ナビのボタンが見えるか」を見るが、
 *      **二段が隣り合っているか**は見ない（離れていても両方“見えて”はいる）
 *    ・check_html は構文と div 収支だけ。**位置は測らない**
 *    ・score_all は DOM シムなので、そもそも描画しない
 *   ＝**採点が合っていることは、門が使えることを意味しない。**
 *
 * ■ 何を測るか（6幅 × 3テーマ × 6群 ＝ 108通り）
 *   ① 章のボタンが全部**画面の中**にあるか（幅0・画面外を弾く）
 *   ② 二段が**隣り合っている**か（隙間 0〜3px。離れる＝押した場所と現れる場所がずれる）
 *   ③ テーマ切替ボタンが**どちらの帯にも重なっていない**か（v9.9.157 の再発）
 *   ④ 文書幅が画面幅を超えていないか（ブラウザの縮小表示）
 *   ⑤ **押した群と、開いたページ／並んでいる章が一致しているか**（2026-08-24追加）
 *   ⑥ pageerror
 *   ⚠ **色（コントラスト）は測っていない**——3テーマで回すが、見ているのは位置と可視だけ。
 *      「3テーマで通った」を「3テーマとも読める」と読まないこと（ルール7）。
 *   ⚠ **判定は作らない**——採点・関門・売却規律には一切触れない。表示だけを測る。
 *
 * ■ ⚠ 可視は display だけで決まらない
 *   visibility:hidden / opacity:0 はレイアウトを残すので**矩形は返る**。3つとも見る。
 *
 * ■ ⚠ 固定要素は offsetParent が null になる
 *   可視判定を offsetParent!==null でやると、**fixed にした瞬間に「見えない」と誤報する**。
 *   だから可視は**矩形**（幅>0 かつ画面内）で測る。
 *
 * ⚠ playwright が無い環境では skip（exit 0）し、**skipしたことを必ず印字する**
 *   ——「測っていない」と「測って問題なし」を取り違えないため（ルール7）。
 *
 * 使い方: node night/check_navstack.js   （終了コード1で不合格）
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
/* ★2026-08-24 是正: 8791 は night/check_state_banner.js が既に使っていた（決め打ちの衝突）。
   CIは順に回すので普通は当たらないが、前の検査のサーバが残ると
   **python の http.server は静かに死に、page.goto だけが落ちて「門が壊れた」に見える**。
   固定値をやめて**空きポートを実測**する（環境変数で固定もできる）。 */
async function freePort() {
  return await new Promise(res => {
    const srv = require('net').createServer();
    srv.listen(0, '127.0.0.1', () => { const p = srv.address().port; srv.close(() => res(p)); });
    srv.on('error', () => res(8794));
  });
}
const WIDTHS = [360, 390, 430, 768, 980, 1280];
const THEMES = ['light', 'dark', 'soft'];
const GROUPS = [1, 2, 3, 4, 5, 6];

(async () => {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch (e) {
    console.log('■ 二段ナビの検査: **skip**（playwright が無い）');
    console.log('  ⚠ これは「通った」ではなく「測っていない」。CIでは npx playwright install chromium で入る');
    process.exit(0);
  }

  const PORT = Number(process.env.CCF_PORT || await freePort());
  const srv = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1500));
  const EXE = '/opt/pw-browsers/chromium';
  const browser = await chromium.launch(fs.existsSync(EXE) ? { executablePath: EXE } : {});
  const bad = [];
  let cells = 0;
  try {
    console.log('■ 二段ナビ（群＋章）の検査 — 6幅 × 3テーマ × 6群');
    for (const w of WIDTHS) {
      const p = await browser.newPage({ viewport: { width: w, height: 844 } });
      const errs = [];
      p.on('pageerror', e => errs.push(e.message.slice(0, 120)));
      await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(2200);
      for (const th of THEMES) {
        await p.evaluate(t => document.documentElement.setAttribute('data-theme', t), th);
        for (const g of GROUPS) {
          await p.evaluate(gg => { const b = document.getElementById('grp' + gg); if (b) b.click(); }, g);
          await p.waitForTimeout(200);
          cells++;
          const r = await p.evaluate(gg => {
            const gn = document.getElementById('grpNav'), cn = document.getElementById('chapNav');
            if (!gn || !cn) return { fatal: 'grpNav / chapNav が無い' };
            const G = gn.getBoundingClientRect(), C = cn.getBoundingClientRect();
            /* ★2026-08-24 是正: display だけを見ていた。visibility:hidden / opacity:0 でも
               **押せないのに「出ている」と数えてしまう**（どちらもレイアウトは残るので矩形は返る）。 */
            const vis = e => { const c = getComputedStyle(e);
              return c.display !== 'none' && c.visibility !== 'hidden' && +c.opacity !== 0; };
            const chapHidden = !vis(cn);
            // ⚠ fixed の要素は offsetParent が null。**矩形**で可視を測る
            const chaps = Array.from(cn.querySelectorAll('button')).filter(vis);
            const off = chaps.filter(x => {
              const r = x.getBoundingClientRect();
              return r.width === 0 || r.top < 0 || r.bottom > window.innerHeight
                || r.left < 0 || r.right > window.innerWidth;
            }).map(x => x.textContent.trim());
            const fixed = getComputedStyle(gn).position === 'fixed';
            const gap = chapHidden ? 0
              : (fixed ? Math.round(G.top - C.bottom) : Math.round(C.top - G.bottom));
            const tt = document.getElementById('themeToggle');
            const T = tt ? tt.getBoundingClientRect() : null;
            const ov = (A, B) => A && B && !(A.right <= B.left || A.left >= B.right
              || A.bottom <= B.top || A.top >= B.bottom);
            /* ★2026-08-24 追加: **押した場所と、開いた場所が同じ群か**を初めて突き合わせる。
               それまでは「章のボタンが画面内か」しか見ておらず、
               群3を押して群4のページが開いても、チップが群2のまま並んでいても、全部 ✓ だった。
               ⚠ CCF_GROUP は const なので window に載らない（グローバル字句環境）。
                  だから JS の定数ではなく **DOM の data-g** で突き合わせる——
                  data-g と CCF_GROUP の一致そのものは check_html の検査6が別に見る。 */
            const pg = window.__ccfPage;
            const tab = document.getElementById('tab' + pg);
            const landedG = tab ? tab.dataset.g : null;
            const shownG = Array.from(new Set(chaps.map(x => x.dataset.g))).sort();
            const wantN = Array.from(cn.querySelectorAll('button[data-g="' + gg + '"]')).length;
            return {
              page: pg, chapN: chaps.length, chapHidden, off, gap, landedG, shownG, wantN,
              tOverG: ov(T, G), tOverC: !chapHidden && ov(T, C),
              docW: document.documentElement.scrollWidth, vw: window.innerWidth,
            };
          }, g);
          const why = [];
          if (r.fatal) why.push(r.fatal);
          else {
            if (r.chapHidden) why.push('章の帯が出ていない（二段目が画面に無い＝「タブが消えた」に見える）');
            if (r.chapN === 0) why.push('章のボタンが0本');
            // 押した群 ≠ 開いたページの群（チップは群Aに並ぶのに押すと群Bへ飛ぶ、の逆）
            if (r.landedG !== String(g))
              why.push(`群${g}を押したのに開いたのは pg${r.page}（その章は群${r.landedG || '不明'}）`);
            if (r.shownG.length !== 1 || r.shownG[0] !== String(g))
              why.push(`並んでいる章が群${g}のものだけではない: [${r.shownG.join(',')}]`);
            if (r.chapN !== r.wantN)
              why.push(`章の本数が合わない 見え${r.chapN} / この群の総数${r.wantN}`);
            if (r.off.length) why.push('章が画面の外: ' + r.off.join(' / '));
            if (r.gap < -1 || r.gap > 3) why.push('二段が離れている/重なっている ' + r.gap + 'px');
            if (r.tOverG || r.tOverC) why.push('テーマ切替ボタンがナビに重なる');
            if (r.docW > r.vw) why.push('文書幅 ' + r.docW + ' > 画面 ' + r.vw);
          }
          if (why.length) bad.push(`${w}px / ${th} / 群${g}(pg${r.page}): ` + why.join(' ／ '));
        }
      }
      if (errs.length) bad.push(`${w}px: pageerror ${errs.length}件 — ` + errs[0]);
      await p.close();
    }
  } finally {
    await browser.close();
    try { srv.kill(); } catch (e) {}
  }
  if (bad.length) {
    console.log(`✗ 二段ナビの検査に不合格（${cells}通り中 ${bad.length}件）`);
    for (const b of bad.slice(0, 25)) console.log('    FAIL ' + b);
    console.log('\n※ 章の帯は**群ナビに隣り合っていないと意味が無い**——'
      + '押す場所と現れる場所が離れると、押した本人の視線の外で起きる');
    process.exit(1);
  }
  console.log(`  ✓ ${cells}通り: 章は全部画面内・二段は隣り合う・テーマ切替の重なりなし・はみ出しなし・pageerror 0`);
  process.exit(0);
})();
