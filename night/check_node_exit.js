#!/usr/bin/env node
/* night/check_node_exit.js — 採点の道具が「終わったらプロセスが抜ける」ことの検査（2026-11-23 新設）

なぜ要るか（実害）
  v9.9.224（2026-11-16）で門（index.html）に `setInterval(ccfMktWatch, …)`＝開いている間、数分ごとに株価の日付を見る
  見張りが入った。night/score_all.js は門のスクリプトを素の node で eval するので、node の本物の setInterval が張られ、
  **採点は数秒で終わるのにプロセスが終わらなくなった**。ci.yml の「全パック採点 score_all」は毎回、GitHub の上限の
  6時間まで止まって取り消され、11-16〜11-23 の間 CI は1度も最後まで走らなかった（毎日の検査・📋今日の集計・
  検査結果のコミットが全部止まった）。数字は合っているので、どの検査も赤くならなかった——止まっただけ。
  是正は score_all.js が setInterval を「張らない差し替え」にすること。この検査はその性質を見張る。

見るもの（どれも別のプロセスで・制限時間つき）
  ① score_all を require するだけで、プロセスが自分で抜ける
  ② score_all を端末から回して（--out で正本を書かない）、終わったら抜ける
  ③ score_all を require する道具（audit_gate）も抜ける
  制限時間は既定 120秒（ふつうは数秒）。環境変数 CCF_EXIT_LIMIT_MS で変えられる（注入検査用）。
  時間切れ＝「抜けない」＝✗（終了コード1）。

使い方: node night/check_node_exit.js
*/
const { spawnSync } = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');

const ROOT = path.resolve(__dirname, '..');
const LIMIT = Math.max(1000, parseInt(process.env.CCF_EXIT_LIMIT_MS || '120000', 10) || 120000);
const tmp = path.join(os.tmpdir(), `ccf_node_exit_${process.pid}.json`);
const CASES = [
  ['① score_all を require するだけ', ['-e', "require('./night/score_all.js')"]],
  ['② score_all を端末から回す（--out・正本は書かない）', ['night/score_all.js', '--out', tmp]],
  ['③ score_all を require する道具（audit_gate）', ['night/audit_gate.js']],
];

let bad = 0;
for (const [name, args] of CASES) {
  const t0 = Date.now();
  const r = spawnSync(process.execPath, args, { cwd: ROOT, timeout: LIMIT, killSignal: 'SIGKILL', stdio: ['ignore', 'ignore', 'pipe'], encoding: 'utf8' });
  const sec = ((Date.now() - t0) / 1000).toFixed(1);
  const timedOut = !!(r.error && r.error.code === 'ETIMEDOUT') || r.signal === 'SIGKILL';
  if (timedOut) {
    bad++;
    console.log(`✗ ${name}: ${sec}秒たっても抜けない（制限 ${LIMIT / 1000}秒）——門のスクリプトが素の node に繰り返しの見張り（setInterval ほか）を残している疑い。night/score_all.js の差し替えを確かめる`);
  } else if (r.status !== 0) {
    bad++;
    console.log(`✗ ${name}: 終了コード ${r.status}（${sec}秒）\n${String(r.stderr || '').split('\n').slice(-6).join('\n')}`);
  } else {
    console.log(`✓ ${name}: ${sec}秒で抜けた`);
  }
}
try { fs.unlinkSync(tmp); } catch (e) { /* 無ければよい */ }
if (bad) {
  console.log(`\n✗ ${bad}件——採点の道具が終わっても抜けない／落ちる。CI では「全パック採点」が上限まで止まる形になる`);
  process.exit(1);
}
console.log('\n✓ 採点の道具は終わったら抜ける');
