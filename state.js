/* ============================================================================
   state.js — **人の決定を repo に置き、門はそれを読む**（v9.9.131・2026-08-10
   ユーザー明示指示「localStorage → repo これはなに？」→「repoに全部」）

   ■ 何を移すか（**localStorage が正本で repo にコピーが1バイトも無かった6つ**）
       pf:portfolio  … 何株持っているか（Ⅶ資産）
       pf:weights    … 目標ウェイト（配分の決定そのもの）
       pf:sold       … 売却記録
       pf:monthly    … 今月の個別枠
       g7ignite:map  … 点灯日（Ulysses契約の48時間冷却）
       g7log:…       … Ⅴ検証履歴（**人が手で書いた記録**）
     台帳 g7: は out/*_gate_pack.json という repo の正本があるので**ここには含めない**
     （含めると「同じものが二箇所に正本を持つ」＝この台帳が最も嫌う型になる）。

   ■ なぜ「読むだけ」なのか（設計の制約を正直に書く）
     門は GitHub Pages の静的ページで、**ブラウザから repo へ書く手段が無い**。
     書けるようにするにはトークンをブラウザに置くことになり、それは絶対にしない。
     よって正本の向きはこうなる:
       repo → 門 … fetch で自動（out/dashboard.json と同じ「CIで作ってJSONで配る」作法）
       門 → repo … **人が書き出してコミットする**（gate_exceptions.json と同じ形）
     つまり「自動で守られる」のではなく「**書き出し忘れが見える**」ようになる。
     見えるようにするのが本体——回転盤(ops_status)が state.json の鮮度を測る。

   ■ 絶対に踏まない事故（この台帳が繰り返し記録している型）
     **新しいほうが古いほうを黙って上書きしてはいけない。**
     キーエンスの「Ⅵ一括取込が台帳のレコードを置き換え、Ⅲ採点機で直した値を無言で巻き戻す」
     とまったく同じ形が、ここでは「repoのstate.jsonが手元の未書き出しの株数を消す」になる。
     だから三重に縛る:
       (1) state.json の savedAt が **null なら何もしない**（未初期化のrepoが手元を消さない）
       (2) 手元に**未書き出しの変更(dirty)があれば採用しない**——警告だけ出す
       (3) 採用は **repo のほうが新しいときだけ**（savedAt を比較する）
     どの分岐でも**黙って消す経路が無い**ことがこの実装の全部。

   ■ dirty はどう立つか
     書き込み地点を一つずつ探して呼び出しを足すと**必ず取りこぼす**ので、
     `localStorage.setItem/removeItem` を包んで**対象キーが書かれたら自動で立てる**。
     `store`（claudeモード）も localStorage へミラーするので、これで全部拾える。
   ========================================================================== */
(function () {
  'use strict';

  var EXACT = ['pf:portfolio', 'pf:weights', 'pf:sold', 'pf:monthly', 'g7ignite:map'];
  var PREFIX = ['g7log:'];
  var SAVED_AT = 'ccf:stateSavedAt';   // 最後に採用/書き出しした state.json の savedAt
  var DIRTY = 'ccf:stateDirty';        // '1' = 手元に未書き出しの変更がある

  function watched(k) {
    if (!k) return false;
    if (EXACT.indexOf(k) >= 0) return true;
    for (var i = 0; i < PREFIX.length; i++) if (k.indexOf(PREFIX[i]) === 0) return true;
    return false;
  }

  /* ── 書き込みを包んで dirty を自動で立てる（呼び出し地点を探さない） ──
     ⚠ ただし**機械が書き戻す分は数えない**。Ⅶ資産の applyDash は盤(out/dashboard.json)の
     現在株価とドル円を pf:portfolio へ書き戻すので（v9.9.87）、素朴に包むと
     **人が何も触らなくても毎回 dirty が立ち、警告が鳴りっぱなしになる**——
     鳴りすぎる警報は鳴らないのと同じ。機械書き込みは quiet() で囲む。
     失われるのは npx/fx だけで、どちらも盤から再取得できる（人の決定ではない）。 */
  var quietDepth = 0;
  function quiet(fn) { quietDepth++; try { return fn(); } finally { quietDepth--; } }
  try {
    var _set = localStorage.setItem.bind(localStorage);
    var _rm = localStorage.removeItem.bind(localStorage);
    localStorage.setItem = function (k, v) {
      var r = _set(k, v);
      if (watched(k) && !quietDepth) { try { _set(DIRTY, '1'); } catch (e) {} }
      return r;
    };
    localStorage.removeItem = function (k) {
      var r = _rm(k);
      if (watched(k) && !quietDepth) { try { _set(DIRTY, '1'); } catch (e) {} }
      return r;
    };
  } catch (e) {}

  function collect() {
    var d = {}, n = 0;
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (!watched(k)) continue;
        var v = localStorage.getItem(k);
        if (v != null) { d[k] = v; n++; }
      }
    } catch (e) {}
    return { data: d, n: n };
  }

  function isDirty() { try { return localStorage.getItem(DIRTY) === '1'; } catch (e) { return false; } }
  function localSavedAt() { try { return localStorage.getItem(SAVED_AT) || null; } catch (e) { return null; } }

  /* 採用の判定だけを純関数にしておく（門と端末が同じ規則を言えるように）。
     戻り値: 'adopt' 採用する / 'dirty' 手元に未書き出しがあるので採用しない /
             'uninit' repoが未初期化 / 'stale' repoのほうが古い / 'same' 同じ */
  function decide(repoSavedAt, mySavedAt, dirty) {
    if (!repoSavedAt) return 'uninit';
    if (dirty) return 'dirty';
    if (!mySavedAt) return 'adopt';
    if (repoSavedAt > mySavedAt) return 'adopt';
    if (repoSavedAt === mySavedAt) return 'same';
    return 'stale';
  }

  var last = null;   // 最後の判定（バナー描画が読む）

  function load() {
    return fetch('state.json?_=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (s) {
        if (!s || s.fmt !== 'ccf-state') { last = { verdict: 'none' }; return last; }
        var v = decide(s.savedAt || null, localSavedAt(), isDirty());
        var applied = 0;
        if (v === 'adopt') {
          var d = s.data || {};
          quiet(function () {                             // 採用は機械の書き込み＝dirty を立てない
            for (var k in d) {
              if (!watched(k)) continue;                  // 想定外のキーは入れない
              try { localStorage.setItem(k, d[k]); applied++; } catch (e) {}
            }
          });
          // 採用は「書き出し済みの状態に追いついた」ことなので dirty は落とす
          try { localStorage.setItem(SAVED_AT, s.savedAt); localStorage.removeItem(DIRTY); } catch (e) {}
        }
        last = { verdict: v, savedAt: s.savedAt || null, applied: applied,
                 mine: localSavedAt(), dirty: isDirty(), n: Object.keys(s.data || {}).length };
        return last;
      });
  }

  /* 書き出し: state.json をそのまま作って落とす。人がコミットすれば repo が正本になる。 */
  function exportFile(btn) {
    var c = collect();
    var savedAt = new Date().toISOString();
    var payload = JSON.stringify({ fmt: 'ccf-state', ver: 1, savedAt: savedAt,
      note: '門の「人の決定」の正本。repo直下に置き、門が起動時に読む。' +
            'ブラウザからrepoへは書けないので、書き出してコミットするのが唯一の道（state.jsの頭注）。',
      data: c.data }, null, 1);
    var o = btn ? btn.textContent : '';
    try {
      var blob = new Blob([payload], { type: 'application/json' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = 'state.json';
      document.body.appendChild(a); a.click();
      setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1200);
      try { navigator.clipboard && navigator.clipboard.writeText(payload); } catch (e) {}
      // **落とした時点では repo にまだ無い**ので dirty は落とさない——
      // コミットして初めて正本になる。落とすのは「コミットした」を押したとき。
      // そのとき記録する savedAt は**この書き出しのもの**でなければならない（今の時刻ではない）
      last = last || {}; last.pendingSavedAt = savedAt;
      if (btn) { btn.textContent = '書き出した（' + c.n + '件）→ repo直下へ置いてコミット';
                 setTimeout(function () { btn.textContent = o; }, 5200); }
    } catch (e) {
      if (btn) { btn.textContent = '書き出せない'; setTimeout(function () { btn.textContent = o; }, 2000); }
    }
    return { savedAt: savedAt, n: c.n };
  }

  /* 「コミットした」の申告: dirty を落とす。**押すのは人**＝嘘をつけば盤が古いままになるだけ。 */
  function markCommitted(savedAt) {
    try {
      if (savedAt) localStorage.setItem(SAVED_AT, savedAt);
      localStorage.removeItem(DIRTY);
    } catch (e) {}
  }

  function banner(elId) {
    var el = document.getElementById(elId); if (!el) return;
    var s = last;
    if (!s) { el.innerHTML = ''; return; }
    var msg = '', col = '', act = false;
    if (s.verdict === 'dirty') {
      msg = '⚠ <b>手元に未書き出しの決定があります</b>（株数・目標ウェイト・売却記録・検証履歴・点灯日・個別枠）。' +
            'repo の state.json はまだ古いままです——<b>書き出してコミットするまで、この端末以外には存在しません</b>。';
      col = 'var(--fail,#9c3b22)'; act = true;
    } else if (s.verdict === 'uninit') {
      msg = '⚠ repo の <b>state.json がまだ空</b>です（savedAt が null）。' +
            '手元の決定は<b>この端末にしかありません</b>。書き出してコミットすると repo が正本になります。';
      col = 'var(--fail,#9c3b22)'; act = true;
    } else if (s.verdict === 'adopt') {
      msg = '✓ repo の state.json から <b>' + s.applied + '件</b>を取り込みました（' + (s.savedAt || '').slice(0, 10) + '）。';
      col = 'var(--pass,#26694a)';
    } else if (s.verdict === 'stale') {
      msg = '⚠ repo の state.json が<b>手元より古い</b>（repo ' + (s.savedAt || '').slice(0, 10) +
            ' / 手元 ' + (s.mine || '').slice(0, 10) + '）。取り込みません——書き出してコミットしてください。';
      col = 'var(--fail,#9c3b22)'; act = true;
    } else { el.innerHTML = ''; return; }   // same / none は黙る
    el.innerHTML = '<div style="border:1px solid ' + col + ';border-left:5px solid ' + col +
      ';background:rgba(0,0,0,.03);border-radius:9px;padding:11px 14px;margin:10px 0;font-size:12.8px;line-height:1.75">' +
      msg + (act ? ' <button onclick="ccfState.export(this)" style="margin-left:8px;padding:6px 13px;border:1px solid ' +
      col + ';background:transparent;color:' + col + ';border-radius:7px;font-size:12px;cursor:pointer;font-family:inherit">📤 書き出す</button>' : '') +
      '</div>';
  }

  window.ccfState = { load: load, export: exportFile, banner: banner, quiet: quiet,
                      markCommitted: markCommitted, decide: decide, collect: collect,
                      isDirty: isDirty, keys: { exact: EXACT, prefix: PREFIX },
                      get last() { return last; } };
})();
