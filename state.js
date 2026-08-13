/* ============================================================================
   state.js — **人の決定を repo に置き、門はそれを読む**（v9.9.131・2026-08-10
   ユーザー明示指示「localStorage → repo これはなに？」→「repoに全部」）

   ■ 何を移すか（**localStorage が正本で repo にコピーが1バイトも無かった6つ**）
       pf:portfolio  … 何株持っているか（Ⅶ資産）
       pf:weights    … 目標ウェイト（配分の決定そのもの）
       pf:sold       … 売却記録
       pf:monthly    … 今月の個別枠
       g7ignite:map  … 点灯日（Ulysses契約の48時間冷却）
       g7log:…       … Ⅴ検証履歴（**記録であって決定ではない**。大半は⭳一括取込／↻全再採点が
                        自動で残すもので、赤い帯＝dirty は立てない。下の「dirty はどう立つか」）
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
     ⚠ ただし**立てるのは決定の5キーだけ**（decides()）。`g7log:`（検証履歴）は集めはするが
       旗は立てない——⭳全パック一括取込／↻全再採点 が最後に自動で1件書くので、
       **手順書どおりの運用で毎回 赤い帯が出ていた**（2026-08-12 実測・是正）。
     ⚠ そして**旗を信じない**。読み込みのたびに nothingPending() が中身を突き合わせ、
       決定が repo と一致していれば旗を落とす（2026-08-11 に stale を自分で治したのと同じ形）。
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

  /* ★**集める集合**と**警報を鳴らす集合**は別（2026-08-12・ユーザー「これがでないようにして」）。
     旧実装は watched() 一つで両方を兼ねていたので、**`g7log:`（検証履歴）を書いただけで
     「手元の決定が、まだ repo に入っていません」という赤い帯が出た**。
     ⚠ この帯は手順書どおりの運用で必ず出る——⭳全パック一括取込／↻全再採点 が最後に
        `saveLog({title:'一括再採点 369銘柄'})` を自動で呼び、それが `g7log:` を書くから
        （index.html:2820）。**人は決定を一つも触っていない**。実測: 決定5キーは1バイトも変わらず
        `ccf:stateDirty='1'` だけが立つ。applyDash と同じ「機械の書き戻しで警報が鳴りっぱなし」の型で、
        **鳴りすぎる警報は鳴らないのと同じ**。
     ⚠ そもそも旧実装は筋が通っていなかった——帯が第一に勧める「① 決定だけ（小）」は
        **設計上 `g7log:` を含まない**（collect(core) が外す）。つまり
        「検証履歴で鳴った帯を、検証履歴を含まない書き出しで消す」ことになっていた。
     ⇒ **dirty が守るのは決定（EXACT の5キー）だけ**とはっきりさせる。`g7log:` は記録であって
        決定ではない。書き出し（履歴も）と収集からは外していないので、repo へ入れる道は残る
        （鮮度は回転盤の `state`〔月次〕が測る）。 */
  function decides(k) { return !!k && EXACT.indexOf(k) >= 0; }

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
      if (decides(k) && !quietDepth) { try { _set(DIRTY, '1'); } catch (e) {} }
      return r;
    };
    localStorage.removeItem = function (k) {
      var r = _rm(k);
      if (decides(k) && !quietDepth) { try { _set(DIRTY, '1'); } catch (e) {} }
      return r;
    };
  } catch (e) {}

  /* collect(core) — core=true なら **検証履歴(g7log:)を外す**。
     ⚠ これは実害から来た分割（2026-08-10）。**貼り付けで渡すと必ず切れる**——
     `g7log:` は「一括再採点 362銘柄」の全文がそのまま入るので1件で数十KBあり、
     しかも localStorage の並び順でログが先に来るため、**株数(pf:portfolio)が本文に
     現れる前に切れた**（実測）。だから (a)小さい決定だけを別に出せるようにし、
     (b)出力の**並びを重要度順に固定**して、万一切れても先頭に大事なものが載るようにする。
     取り込み側は「data にあるキーだけ書く」ので、小さい方をコミットしても
     手元の検証履歴が消えることはない（**消す経路は無い**）。 */
  var ORDER = ['pf:portfolio', 'pf:sold', 'pf:weights', 'pf:monthly', 'g7ignite:map'];
  function collect(core) {
    var all = {}, keys = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var k = localStorage.key(i);
        if (!watched(k)) continue;
        if (core && k.indexOf('g7log:') === 0) continue;
        var v = localStorage.getItem(k);
        if (v != null) { all[k] = v; keys.push(k); }
      }
    } catch (e) {}
    keys.sort(function (a, b) {
      var ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
      if (ia < 0) ia = 99; if (ib < 0) ib = 99;
      return ia - ib || (a < b ? -1 : a > b ? 1 : 0);
    });
    var d = {};                                  // 重要度順に詰め直す（JSONはこの順で出る）
    keys.forEach(function (k) { d[k] = all[k]; });
    return { data: d, n: keys.length };
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

  /* nothingPending(repoData) — **旗を信じず、中身で確かめる**。
     手元の決定キーが repo の state.json と一つ残らず一致するなら、**書き出すものは定義上ゼロ**。
     ⚠ これは「危ないものを隠す」検査ではない——一つでも食い違えば false を返すので、
        本物の未書き出しは絶対に消えない（片側だけに倒れる）。
     なぜ要るか: 旗は一度立つと書き出すまで落ちないので、**上の欠陥で既に立ってしまった端末**は
     直しただけでは帯が消えない。2026-08-11 に stale を自分で治したのと同じ形で、旗の側も治す。 */
  /* ⚠ **素の文字列比較では一度も一致しない**。決定のファイルに機械の書き戻しが混ざっているから。
     推測せず実測した（2026-08-12・素の読み込み直後に state.json と突き合わせ）——食い違うのは
       pf:portfolio … `fx` と 各行の `npx` / `npxAuto` の**3項目だけ**（盤の現在株価とドル円・v9.9.87）
                      ※ `sh`(株数) `v`(金額) `bpx` は**1件も動かない**＝人の決定は無傷
       pf:weights   … `city`(浮動小数の誤差) と `total`＝**全部が P からの導出値**（portfolio.html:350）
       pf:sold / pf:monthly / g7ignite:map … **完全一致**
     ⇒ 落とすのはこの実測どおりの範囲だけにする。**広く落とすと本物の決定を隠す**ので、
        JSONとして読めなければ素の比較へ倒す（片側だけに倒れる）。 */
  var DERIVED_KEY = { 'pf:weights': 1 };                 // キーごと導出値（機械しか書かない）
  var MACHINE_FLD = { fx: 1, npx: 1, npxAuto: 1 };       // 盤から書き戻される欄
  function stripMachine(v) {
    var o = JSON.parse(v);
    if (o && typeof o === 'object') {
      for (var f in MACHINE_FLD) delete o[f];
      if (Array.isArray(o.positions)) {
        o.positions = o.positions.map(function (p) {
          if (!p || typeof p !== 'object') return p;
          var q = {}; for (var kk in p) if (!MACHINE_FLD[kk]) q[kk] = p[kk];
          return q;
        });
      }
    }
    return JSON.stringify(o);
  }
  function sameDecision(k, mine, theirs) {
    if (mine === theirs) return true;
    if (mine == null || theirs == null) return false;
    try { return stripMachine(mine) === stripMachine(theirs); } catch (e) { return false; }
  }
  function nothingPending(repoData) {
    try {
      for (var i = 0; i < EXACT.length; i++) {
        var k = EXACT[i];
        if (DERIVED_KEY[k]) continue;
        var mine = localStorage.getItem(k);
        var theirs = (repoData && Object.prototype.hasOwnProperty.call(repoData, k)) ? repoData[k] : null;
        if (mine == null && theirs == null) continue;
        if (!sameDecision(k, mine, theirs)) return false;   // 一つでも違えば「未書き出しがある」側へ
      }
      return true;
    } catch (e) { return false; }
  }

  var last = null;   // 最後の判定（バナー描画が読む）

  function load() {
    return fetch('state.json?_=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (s) {
        if (!s || s.fmt !== 'ccf-state') { last = { verdict: 'none' }; return last; }
        // 旗が立っていても、決定が repo と一致しているなら書き出すものは無い＝自分で落とす
        var healed = false;
        if (isDirty() && nothingPending(s.data || {})) {
          try { localStorage.removeItem(DIRTY); healed = true; } catch (e) {}
        }
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
        /* 2026-08-11: **stale は自分で治す**。
           decide() は dirty を stale より先に見るので、stale に来た時点で
           「手元に未書き出しの決定は無い」が確定している＝**人がやることは何も無い**。
           それでも印(savedAt)だけが repo より新しいままだと、以後ずっと帯が出続ける。
           ここで**印だけ repo に合わせる**（data は触らない＝上書きしない）。
           そうすれば次に repo が更新されたとき正しく adopt に入る。 */
        if (v === 'stale' && !isDirty() && s.savedAt) {
          try { localStorage.setItem(SAVED_AT, s.savedAt); } catch (e) {}
          v = 'same';
        }
        last = { verdict: v, savedAt: s.savedAt || null, applied: applied,
                 mine: localSavedAt(), dirty: isDirty(), healed: healed,
                 n: Object.keys(s.data || {}).length };
        return last;
      });
  }

  /* 書き出し: state.json をそのまま作って落とす。人がコミットすれば repo が正本になる。 */
  function exportFile(btn, core) {
    var c = collect(core);
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
      /* ⚠ クリップボードに**頼らない**（2026-08-10 実害）。Ⅶ資産は <iframe> の中にあり、
         `allow="clipboard-write"` が無いとブラウザが writeText を**黙って拒否**する。
         実測: 3回書き出しても savedAt が 17:29 のまま固定＝クリップボードが一度も更新されず、
         同じ古い中身が貼られ続けた（しかも大きい方なので毎回途中で切れた）。
         → **本文を画面に出して選択済みにする**。これはどのブラウザでも必ず動く。 */
      try { navigator.clipboard && navigator.clipboard.writeText(payload); } catch (e) {}
      showBox(payload, savedAt, c.n);
      // **落とした時点では repo にまだ無い**ので dirty は落とさない——
      // コミットして初めて正本になる。落とすのは「コミットした」を押したとき。
      // そのとき記録する savedAt は**この書き出しのもの**でなければならない（今の時刻ではない）
      last = last || {}; last.pendingSavedAt = savedAt;
      var kb = payload.length < 1024 ? '1KB未満' : Math.round(payload.length / 1024) + 'KB';
      if (btn) { btn.textContent = '✓ 書き出した（' + c.n + '件 / ' + kb + '・コピー済）→ ② へ';
                 setTimeout(function () { btn.textContent = o; }, 6000); }
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

  /* 書き出した中身をその場に出す（選択済み）。クリップボードが効かない環境でも渡せる。 */
  function showBox(payload, savedAt, n) {
    var host = document.getElementById('stateBox') || (function () {
      var d = document.createElement('div'); d.id = 'stateBox';
      var b = document.getElementById('stateBar');
      if (b && b.parentNode) b.parentNode.insertBefore(d, b.nextSibling);
      else document.body.appendChild(d);
      return d;
    })();
    var kb = payload.length < 1024 ? '1KB未満' : Math.round(payload.length / 1024) + 'KB';
    host.innerHTML =
      '<div style="border:1px solid ' + GREEN + ';border-left:5px solid ' + GREEN +
      ';border-radius:10px;padding:12px 14px;margin:10px 0;font-size:12.6px;line-height:1.7">' +
      '<div style="font-weight:700;color:' + GREEN + ';margin-bottom:4px">📋 ここの中身を全部コピーして貼ってください</div>' +
      '<div style="opacity:.85;margin-bottom:7px">' + n + '件 / ' + kb +
      '　savedAt ' + savedAt + '　<b>枠を長押し→全選択→コピー</b>（クリップボードが自動で入らない端末向け）</div>' +
      '<textarea id="stateBoxTa" readonly style="width:100%;height:150px;font-family:monospace;font-size:11px;' +
      'padding:8px;border:1px solid ' + GREEN + ';border-radius:7px;background:rgba(255,255,255,.6);color:#1b1610"></textarea>' +
      '<div style="margin-top:7px"><button onclick="ccfState.copyBox(this)" style="padding:7px 15px;border:1px solid ' +
      GREEN + ';background:' + GREEN + ';color:#fff;border-radius:7px;font-size:12.5px;font-weight:600;cursor:pointer;' +
      'font-family:inherit">📋 コピー</button></div></div>';
    var ta = document.getElementById('stateBoxTa');
    if (ta) { ta.value = payload; try { ta.focus(); ta.select(); } catch (e) {} }
  }

  /* execCommand は古いが、iframe でも file:// でも動く最後の砦 */
  function copyBox(btn) {
    var ta = document.getElementById('stateBoxTa'); if (!ta) return;
    var o = btn ? btn.textContent : '';
    var ok = false;
    try { ta.focus(); ta.select(); ta.setSelectionRange(0, ta.value.length); ok = document.execCommand('copy'); } catch (e) {}
    if (!ok) { try { navigator.clipboard.writeText(ta.value); ok = true; } catch (e) {} }
    if (btn) { btn.textContent = ok ? '✓ コピーした' : '手で選択してください';
               setTimeout(function () { btn.textContent = o; }, 2600); }
  }

  /* 帯の描画。**手順を4段の番号つきで出す**（v9.9.132・ユーザー「これをもっとわかるようにして」）。
     ここが単一実装で、index.html(門の頭) と portfolio.html(Ⅶ資産) の両方が同じものを描く。
     ⚠ 色は変数名で渡さない——index.html は --fail/--pass、portfolio.html は --rust/--jade と
        名前が違うので、変数名で書くと**片方のページだけ色が付かない**（v9.9.108 と同型の事故）。 */
  var RED = '#b04a2c', GREEN = '#2f7a53', DIM = 'rgba(128,120,105,.95)';

  function stepHTML(col) {
    var c = collect(), core = collect(true);
    var keys = Object.keys(core.data).map(function (k) {   // 見出しに出す品目は**決定だけ**の側
      return k.indexOf('g7log:') === 0 ? '検証履歴' : ({
        'pf:portfolio': '株数', 'pf:weights': '目標ウェイト', 'pf:sold': '売却記録',
        'pf:monthly': '今月の個別枠', 'g7ignite:map': '点灯日'
      }[k] || k);
    });
    var uniq = keys.filter(function (v, i) { return keys.indexOf(v) === i; });
    var b = function (label, fn) {
      return '<button onclick="' + fn + '" style="padding:8px 16px;border:1px solid ' + col +
        ';background:' + col + ';color:#fff;border-radius:8px;font-size:13px;font-weight:600;' +
        'cursor:pointer;font-family:inherit;white-space:nowrap">' + label + '</button>';
    };
    var li = function (n, t, extra) {
      return '<div style="display:flex;gap:10px;align-items:flex-start;margin:9px 0">' +
        '<span style="flex:0 0 auto;width:22px;height:22px;border-radius:50%;background:' + col +
        ';color:#fff;font-size:12px;font-weight:700;display:grid;place-items:center;margin-top:1px">' + n + '</span>' +
        '<span style="flex:1;min-width:0">' + t + (extra ? '<div style="margin-top:7px">' + extra + '</div>' : '') + '</span></div>';
    };
    var kb = function (o) { var n = JSON.stringify(o).length;
      return n < 1024 ? '1KB未満' : '約' + Math.round(n / 1024) + 'KB'; };
    var kbAll = kb(c.data), kbCore = kb(core.data);
    return li(1, '<b>書き出す</b>。<span style="opacity:.85">端末に落ち、<b>クリップボードにも入る</b>。</span>' +
                 '<div style="margin-top:5px;font-size:11.8px;opacity:.9">' +
                 '<b>決定だけ</b>＝' + core.n + '件 / <b>' + kbCore + '</b>（' + (uniq.join('・') || '—') + '）' +
                 '　／　<b>履歴も</b>＝' + c.n + '件 / ' + kbAll + '（＋検証履歴）</div>',
              b('📤 ① 決定だけ（小）', 'ccfState.export(this,true)') +
              ' <button onclick="ccfState.export(this)" style="margin-left:6px;padding:8px 14px;border:1px solid ' + col +
              ';background:transparent;color:' + col + ';border-radius:8px;font-size:12.5px;cursor:pointer;' +
              'font-family:inherit;white-space:nowrap">履歴も（大）</button>') +
           li(2, '<b>その中身を Claude に貼る</b>。<span style="opacity:.85">' +
                 '<b>貼るなら「決定だけ（小）」</b>——大きいほうは長すぎて<b>途中で切れます</b>（実測）。' +
                 '検証履歴ごと入れたいときは、落ちたファイルを repo 直下の ' +
                 '<code style="font-size:11.5px">state.json</code> に置いてコミット。</span>') +
           li(3, '<b>Claude が検査して commit・push する</b>。<span style="opacity:.85">' +
                 '<code style="font-size:11.5px">night/validate_state.py</code> で形を確かめてから入れる。</span>') +
           li(4, 'ここへ戻って <b>入れた</b> を押す。<span style="opacity:.85">この帯が消える。' +
                 '押し忘れても壊れない——帯が出続けるだけ。</span>',
              b('✓ ④ 入れた', 'ccfState.done(this)'));
  }

  function banner(elId) {
    var el = document.getElementById(elId); if (!el) return;
    var s = last;
    if (!s) { el.innerHTML = ''; return; }
    var head = '', col = RED, act = false;
    if (s.verdict === 'dirty') {
      head = '手元の決定が、<b>まだ repo に入っていません</b>';
      act = true;
    } else if (s.verdict === 'uninit') {
      head = 'repo の state.json は<b>まだ空</b>——株数も売却記録も<b>この端末にしかありません</b>';
      act = true;
    } else if (s.verdict === 'stale') {
      /* 2026-08-11: **赤い4手の帯を出さない**。
         decide() は dirty を stale より先に見るので、**stale は必ず「手元に未書き出しは無い」**
         の意味になる＝人がやることが何も無い。それを赤で出して4手を並べるのは、
         鳴りすぎる警報（＝鳴らないのと同じ）そのものだった。
         情報は消さない——**灰色の一行**にして、押すものは出さない。 */
      el.innerHTML = '<div style="border:1px dashed ' + DIM + ';border-radius:9px;padding:8px 12px;' +
        'margin:10px 0;font-size:12.2px;line-height:1.6;color:' + DIM + '">' +
        'repo の state.json（' + (s.savedAt || '').slice(0, 10) + '）は手元の記録（' +
        (s.mine || '').slice(0, 10) + '）より古いので<b>取り込みません</b>。' +
        '手元に未書き出しの決定はありません＝<b>やることはありません</b>。' +
        '入れ直すなら Ⅶ 保有 の「📤 決定だけ」から。</div>';
      return;
    } else if (s.verdict === 'adopt') {
      el.innerHTML = '<div style="border:1px solid ' + GREEN + ';border-left:5px solid ' + GREEN +
        ';border-radius:9px;padding:10px 14px;margin:10px 0;font-size:12.8px;line-height:1.7">' +
        '<b style="color:' + GREEN + '">✓ repo の state.json から ' + s.applied + '件を取り込みました</b>' +
        '<span style="opacity:.8">（' + (s.savedAt || '').slice(0, 10) + '）——この端末は repo に追いつきました。</span></div>';
      return;
    } else { el.innerHTML = ''; return; }   // same / none は黙る
    if (!act) { el.innerHTML = ''; return; }
    el.innerHTML = '<div style="border:1px solid ' + col + ';border-left:5px solid ' + col +
      ';border-radius:10px;padding:13px 16px;margin:10px 0;font-size:12.9px;line-height:1.75">' +
      '<div style="font-size:14px;font-weight:700;color:' + col + ';margin-bottom:3px">⚠ ' + head + '</div>' +
      '<div style="color:' + DIM + ';font-size:12.2px;margin-bottom:8px">' +
      '門は静的ページなので<b>ブラウザから repo へは書けません</b>（トークンを置かない設計）。' +
      'だから最後の一歩だけ人の手が要ります——<b>4手で終わります</b>。</div>' +
      stepHTML(col) + '</div>';
  }

  /* ④ 「入れた」。**押すのは人**＝嘘をつけば盤(ops_status)が古いままになるだけで、データは消えない。 */
  function done(btn) {
    var o = btn ? btn.textContent : '';
    /* 2026-08-11 是正: **押した時刻を書かない**。
       「入れた」は『repo が正本になった』の意味なので、**repo を読み直してそこに書いてある
       savedAt に合わせる**のが正しい。押した時刻を書くと repo より必ず新しくなり、以後ずっと
       『repo の state.json が手元より古い』と鳴り続ける（実害: 2026-08-11 の画面）。
       しかも**この帯自身が「④ ここへ戻って押す」と案内している**＝手順どおりにやると必ずこうなる
       ——戻ってきた時点で last.pendingSavedAt は失われており、fallback の new Date() が書かれていた。
       ⚠ GitHub Pages の反映待ちで古い state.json が返っても害はない——repo と手元が揃うだけで、
       新しいものが届いたら次回 adopt される。 */
    if (btn) btn.textContent = '確認中…';
    var fin = function (msg) {
      if (btn) btn.textContent = msg;
      setTimeout(function () {
        ['stateBar'].forEach(function (id) { try { banner(id); } catch (e) {} });
        if (btn) btn.textContent = o;
      }, 900);
    };
    load().then(function (s) {
      if (s && s.savedAt) { markCommitted(s.savedAt); last = { verdict: 'same', savedAt: s.savedAt, mine: s.savedAt }; }
      else { if (last && last.pendingSavedAt) markCommitted(last.pendingSavedAt); last = { verdict: 'same' }; }
      fin('✓ 記録した');
    }).catch(function () {
      if (last && last.pendingSavedAt) markCommitted(last.pendingSavedAt);
      last = { verdict: 'same' };
      fin('✓ 記録した');
    });
  }

  window.ccfState = { load: load, export: exportFile, banner: banner, quiet: quiet, done: done, copyBox: copyBox,
                      markCommitted: markCommitted, decide: decide, collect: collect,
                      isDirty: isDirty, keys: { exact: EXACT, prefix: PREFIX },
                      get last() { return last; } };
})();
