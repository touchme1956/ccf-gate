#!/usr/bin/env node
/**
 * night/check_gate_parity.js — **門(ブラウザ)と端末(score_all.js)が同じことを言うか**（2026-08-11新設・v9.9.140）
 *
 * ■ なぜ要るか
 *   この台帳の掟 v9.9.65「**同じ台帳を見る二つの検査器が違うことを言ってはいけない**」は、
 *   実際に何度も破れている——盤とⅥで APH が 🟢/⛔ に割れた(v9.9.94→95)／explain_score が
 *   判定式を書き写して3版ぶん取り残された(2026-08-11)／台帳の旧レコードが買付の席を奪った(v9.9.102)。
 *   ところが **その一致を機械で測る仕組みが一つも無かった**。CIの実ブラウザ検査は
 *   check_mobile_fit（はみ出しと pageerror だけ）で、Ωも buy も見ていない。
 *
 * ■ 何を測るか（3つだけ）
 *   ① 台帳の Ω（compute() がブラウザで出した値） vs out/score_all.json の s
 *   ② Ⅵ買付順位の🟢投下可の顔ぶれ vs score_all の buy
 *   ③ pageerror
 *   **判定は作らない**——両者の食い違いを出すだけ。Ω・四関門・売却規律・配分には触れない。
 *
 * ■ ⚠この検査は落とす側（continue-on-error を付けない）
 *   一致していないのに緑にすると、この道具は居ないのと同じ。
 *   ⚠ただし**ブラウザが起動できない環境では skip（exit 0）**する——
 *     playwright が無いことと「門と端末が食い違っている」ことは別物なので、
 *     前者で赤くすると本物の不一致がその中に埋もれる（鳴りすぎる警報は鳴らないのと同じ）。
 *     skip したことは必ず印字する＝**「測っていない」と「測って一致」を取り違えない**（ルール7）。
 *
 * 使い方: node night/check_gate_parity.js
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(__dirname);
const PORT = 8722;
const TOL = 0.05;                       // Ωの許容差（表示は小数1桁なので丸め分だけ許す）

(async () => {
  let chromium;
  try { ({ chromium } = require('playwright')); }
  catch (e) {
    console.log('■ 門と端末の一致検査: **skip**（playwright が無い）');
    console.log('  ⚠これは「一致した」ではなく「測っていない」。CIでは npx playwright install chromium で入る');
    process.exit(0);
  }

  let term;
  try { term = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', 'score_all.json'), 'utf8')); }
  catch (e) { console.log('⚠ out/score_all.json が読めない＝比較の錨が無い。**一致とは言えない**'); process.exit(1); }
  const T = {}; for (const r of term) T[String(r.t).toUpperCase()] = r;
  const termBuy = term.filter(r => r.buy).map(r => String(r.t).toUpperCase()).sort();

  const srv = spawn('python3', ['-m', 'http.server', String(PORT)], { cwd: ROOT, stdio: 'ignore' });
  await new Promise(r => setTimeout(r, 1500));
  const EXE = '/opt/pw-browsers/chromium';
  const browser = await chromium.launch(fs.existsSync(EXE) ? { executablePath: EXE } : {});
  let bad = 0, _nLed = 0, _gateBuy = null;
  try {
    const p = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errs = [];
    p.on('pageerror', e => errs.push(e.message.slice(0, 140)));
    await p.goto(`http://localhost:${PORT}/index.html`, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(2500);

    // ⭳ 全パック一括取込（本番と同じ状態にする）
    await p.evaluate(() => { const t = document.getElementById('tab3'); if (t) t.click(); });
    await p.waitForTimeout(600);
    await p.evaluate(() => (typeof ccfImportAllPacks === 'function' ? ccfImportAllPacks() : null));
    // 取り込みは 369件で60秒超かかる。件数が増えなくなるまで待つ
    let prev = -1, stable = 0;
    for (let i = 0; i < 90; i++) {
      await p.waitForTimeout(2000);
      const n = await p.evaluate(() => { let c = 0; for (let i = 0; i < localStorage.length; i++) if (localStorage.key(i).startsWith('g7:')) c++; return c; });
      if (n === prev) { if (++stable >= 3) break; } else { stable = 0; prev = n; }
    }

    // ① 台帳のΩ
    const led = await p.evaluate(async () => {
      const o = {};
      try {
        const r = await store.list('g7:');
        for (const k of (r && r.keys) || []) {
          const v = await store.get(k); if (!v) continue;
          const j = JSON.parse(v.value); if (!j || !j.r) continue;
          o[String(j.data && j.data.nm || k.slice(3)).trim().split(/\s/)[0].toUpperCase()] = j.r.evalScore;
        }
      } catch (e) {}
      return o;
    });
    const keys = Object.keys(led); _nLed = keys.length;
    const diff = keys.filter(t => T[t] && typeof T[t].s === 'number' && Math.abs(led[t] - T[t].s) > TOL);
    console.log('■ 門と端末の一致検査（v9.9.65の掟を機械で測る）');
    console.log(`  台帳 ${keys.length}件 / score_all ${term.length}件`);
    if (diff.length) {
      bad++;
      console.log(`  ✗ **Ωが食い違う ${diff.length}社**`);
      for (const t of diff.slice(0, 15)) console.log(`      ${t}: 門 ${led[t]} vs 端末 ${T[t].s}`);
    } else {
      console.log(`  ✓ Ω ${keys.length}/${keys.length} 一致`);
    }

    // ② Ⅵ買付順位の🟢投下可
    await p.evaluate(() => { const t = document.getElementById('tab5'); if (t) t.click(); });
    await p.waitForTimeout(6000);
    // ⚠**描画ではなく判断そのものを測る。** 画面の文字列を解析する形にしたら誤検出した
    //   （説明文の「🟢投下可」を拾い、さらに買付の行に印が無いので10社すべてを不一致と報告した）。
    //   Ⅵは v9.9.140 から window.__ccfBuyList に**自分が投下可と判断した集合**を公開する。
    const gateBuy = await p.evaluate(() => (window.__ccfBuyList || null)); _gateBuy = gateBuy;
    if (gateBuy == null) {
      bad++;
      console.log('  ✗ Ⅵ買付順位が判断を公開していない（window.__ccfBuyList が無い＝描けていないか版が古い）');
    } else {
      const g = gateBuy.slice().sort();
      if (g.join() === termBuy.join()) console.log(`  ✓ 🟢投下可 ${termBuy.length}社が門と端末で一致（${g.join(' ')}）`);
      else {
        bad++;
        console.log('  ✗ **🟢投下可が食い違う**');
        console.log('      門  : ' + g.join(' '));
        console.log('      端末: ' + termBuy.join(' '));
        console.log('      門にだけ: ' + g.filter(t => !termBuy.includes(t)).join(' ')
          + ' ／ 端末にだけ: ' + termBuy.filter(t => !g.includes(t)).join(' '));
      }
    }

    // ③ pageerror
    if (errs.length) { bad++; console.log(`  ✗ pageerror ${errs.length}件: ` + errs.slice(0, 3).join(' | ')); }
    else console.log('  ✓ pageerror 0');
  } finally {
    await browser.close();
    try { srv.kill(); } catch (e) {}
  }
  // 回転盤(ops_status)が鮮度を測れるように結果を残す。**判定には使わない**（表示と停止検出だけ）
  try {
    fs.writeFileSync(path.join(ROOT, 'out', 'gate_parity.json'),
      JSON.stringify({ generated: new Date().toISOString().slice(0, 10), ok: bad === 0, bad: bad,
        n_ledger: _nLed, n_term: term.length, buy_term: termBuy, buy_gate: _gateBuy,
        note: '門(ブラウザ)と端末(score_all.js)が同じことを言うかの実測。**判定には使わない**。'
            + 'bad>0 は v9.9.65 の破れ＝どちらが正しいかはこの道具では判らない。' }, null, 1), 'utf8');
  } catch (e) {}
  if (bad) {
    console.log('\n✗ **門と端末が違うことを言っています**（v9.9.65の破れ）。');
    console.log('  ⚠ 買付の判断はこれが解消するまで保留すること——どちらが正しいかはこの道具では判らない。');
    process.exit(1);
  }
  console.log('\n✓ 門と端末は同じことを言っている');
  process.exit(0);
})();
