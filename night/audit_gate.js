#!/usr/bin/env node
/**
 * night/audit_gate.js — 門(index.html)の ccfAudit() をそのまま端末で全パックに掛ける
 *
 * 目的: Ⅳ台帳の「🔍 全件点検」と**同じ関数**の結果を、ブラウザを開かずに数える。
 *   バッジを潰す作業は「どの項目が何社に残っているか」を毎回数え直せないと進まない。
 *   score_all.js と同じく門の関数を eval で読むので、二重実装は作らない。
 *
 * 使い方:
 *   node night/audit_gate.js              項目別の残数＋Ω72+の一覧
 *   node night/audit_gate.js --all        Ω72未満も含める（門は未入力警告をΩ72+に絞る）
 *   node night/audit_gate.js --k acq5,per 項目を絞る
 *   node night/audit_gate.js --t MCO      銘柄の中身を全部出す
 *
 * 注意: ブラウザの台帳には _meta が入らないので、ccfAudit は「門が持つ情報だけで判る事故」しか見ない。
 *   根拠(_meta.evidence)の被覆は night/validate_packs.py / audit_evidence.py の担当＝二層で守る。
 */
'use strict';
const fs = require('fs');
const path = require('path');
const ROOT = path.dirname(__dirname);
const { scorePack, lastCoerce } = require('./score_all.js');

if (typeof ccfAudit !== 'function') {
  console.error('ccfAudit() を読み込めなかった。index.html の構造が変わった可能性がある');
  process.exit(1);
}

const argv = process.argv.slice(2);
const arg = n => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : null; };
const onlyK = (arg('--k') || '').split(',').filter(Boolean);
const onlyT = (arg('--t') || '').split(',').filter(Boolean).map(s => s.toUpperCase());
const showAll = argv.includes('--all');

const rows = [];
for (const f of fs.readdirSync(path.join(ROOT, 'out'))) {
  if (!f.endsWith('_gate_pack.json')) continue;
  let d; try { d = JSON.parse(fs.readFileSync(path.join(ROOT, 'out', f), 'utf8')); } catch { continue; }
  const t = f.split('_gate_pack')[0];
  if (onlyT.length && !onlyT.includes(t.toUpperCase())) continue;
  let r; try { r = scorePack(d); } catch (e) { continue; }
  // B4(2026-08-04): 門と同じく「取込で化けた」記録(coerce)を ccfAudit へ渡す。従来は常に [] で、
  //   err①「取込で化けた」が端末側で構造的に0件＝ブラウザと違うことを言っていた（v9.9.65違反）。
  const coerce = lastCoerce();
  const s = parseFloat(r.evalScore) || 0;
  if (!showAll && !onlyT.length && s < 72) continue;
  let W = []; try { W = ccfAudit(d, r, coerce) || []; } catch (e) { continue; }
  W = W.filter(w => !onlyK.length || onlyK.includes(w.k));
  // 門(ブラウザ)は _meta を持てないので「原本で検算して確定した欄」も鳴り続ける（TSM/SAPのper・
  // ADBE/MCOのroic乖離・CTAS/SAPのacq5='no' 等）。端末側は _meta を読めるので、
  // **未解決**と**検算済で仕様どおり鳴っているだけ**を分けて出す＝作業リストが本物だけになる。
  const M = d._meta || {};
  for (const w of W) w.ok = !!((M.evidence || {})[w.k] || (M.nulls || {})[w.k]);
  if (W.length) rows.push({ t, s, W });
}
rows.sort((a, b) => b.s - a.s);

if (onlyT.length) {                                  // 1社の中身を全部出す
  for (const r of rows) {
    console.log(`\n===== ${r.t}  Ω${r.s.toFixed(1)}`);
    for (const w of r.W) console.log(`  [${w.lv}]${w.ok ? '✓検算済' : '     '} ${w.k}: ${w.msg.replace(/<[^>]+>/g, '')}\n        直し方: ${w.fix}`);
  }
  process.exit(0);
}

const byK = {};
for (const r of rows) for (const w of r.W) (byK[w.k] || (byK[w.k] = { err: [], warn: [], info: [] }))[w.lv].push({ t: r.t, ok: w.ok });
const ks = Object.keys(byK).sort((a, b) =>
  (byK[b].err.length * 1000 + byK[b].warn.length) - (byK[a].err.length * 1000 + byK[a].warn.length));

const n = (lv, ok) => rows.reduce((a, r) => a + r.W.filter(w => w.lv === lv && (ok === undefined || !!w.ok === ok)).length, 0);
console.log(`対象 ${rows.length}社${showAll ? '（全件）' : '（Ω72+のみ＝門が未入力警告を出す範囲）'}`
  + `　要修正 ${n('err')}件 / 警告 ${n('warn')}件（うち ✓検算済 ${n('warn', true)}件・**未解決 ${n('warn', false)}件**）`
  + ` / 測定漏れ ${n('info')}件\n`);
console.log(`${'項目'.padEnd(10)} ${'要修正'.padStart(5)} ${'警告'.padStart(5)}  社（✓＝_metaに根拠あり＝門が_metaを読めないため仕様どおり鳴っているだけ）`);
for (const k of ks) {
  const g = byK[k];
  console.log(`${k.padEnd(12)} ${String(g.err.length).padStart(5)} ${String(g.warn.length).padStart(5)}  `
    + [...g.err.map(x => x.t + '!'), ...g.warn.map(x => x.t + (x.ok ? '✓' : ''))].join(' '));
}
console.log(`\n銘柄別（多い順）:`);
for (const r of rows.slice().sort((a, b) => b.W.length - a.W.length))
  console.log(`  ${r.t.padEnd(7)} Ω${r.s.toFixed(1).padStart(5)}  ⚠${String(r.W.length).padStart(2)}  ${r.W.map(w => w.k + (w.ok ? '✓' : '')).join(' ')}`);
