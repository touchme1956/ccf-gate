#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事業説明の日本語要約の在庫（表示専用・判定には一切使わない）。

【なぜ要るか】2026-08-18 ユーザー「事業説明が英語は分からない。何をしている会社などが
分かるようにしたい」。門は Ω・堀・E[r] という**評価**を全部出すのに、「この会社は何を
している会社か」を出していたのは **原本(10-K/20-F)の Item1 冒頭＝英文そのまま** だった
（out/profiles.json の biz・252社・各1600字）。読めなければ在っても無いのと同じ。

【なぜ第三者の要約を持って来ないか】fetch_profiles.py が既に決めている——第三者の要約は
**原本と食い違っても気づけない**。だからここでも外部の会社紹介は使わない。作るのは
**原本（または台帳の日本語根拠）そのものからの要約**で、**素材は必ず画面に併記する**
（食い違えば読み手が気づける＝ルール8「値を書くなら根拠も書く」の表示版）。

【なぜ profiles.json と別ファイルか】fetch_profiles.py は profiles.json を**毎回作り直す**。
同じファイルに書くと、次に採取器が回った瞬間に要約が消える——2026-08-17 に
fetch_logos が logo_colors の測定値を捨てた「作った答えを捨てる」型（5例目）と同じ穴。
**そもそも同じファイルに書かない**ことで構造的に踏まない（stale_bs / pending /
validate_fail と同じ「同一オリジンの独立JSON」の作法）。

【素材と指紋】素材は (a) profiles.json の biz＝原本の英文、無ければ
(b) seg+pos+dep＝台帳の _meta.evidence（審査官が原本から日本語で書いた事業の事実）。
指紋は素材の sha1 先頭12桁。**素材が変われば訳は自動で「古い」へ落ち**、作業リストに戻る
（logo_colors の b、パックの machine_check と同じ作法。手で上げる版番号は必ず忘れる）。
**素材がゼロの社は書き込みを拒否する**——原本の裏づけが無いところに要約を置かない（ルール7）。

【書き方の規約】（審査官＝読み手が守る。道具は形式しか見られない）
  ・**素材にあることだけ書く**。自分の知識で補わない。原文に無い数字・固有名詞は書かない
  ・何を作り／売り、誰に売り、どこで稼ぐか。3〜5文・200〜400字
  ・原文の固有名詞（製品名・セグメント名）は原文の綴りを残す
  ・断定できないものは書かない（「大手」「世界的な」等の評価語は素材にあるときだけ）

使い方:
  python3 night/profiles_ja.py --audit [--json]      # 未訳・古い・孤児を数える
                                                     # --json は out/profiles_ja_audit.json も書く
                                                     # （📋今日タブと CI が読む）
  python3 night/profiles_ja.py --add < patch.json    # {"MSFT":"…","V":"…"} をマージ
  python3 night/profiles_ja.py --show MSFT           # 素材と訳を並べて見る
"""
import json, sys, os, re, hashlib, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'out', 'profiles.json')
DST = os.path.join(ROOT, 'out', 'profiles_ja.json')
JA = re.compile(r'[ぁ-んァ-ヶ一-龥]')
MINLEN, MAXLEN = 40, 900


# 原本の Item1 は冒頭が「SECへの提出書類はウェブで無料で読めます」「商標について」という
# 定型で埋まっている社がある（実測 HWM・LRCX は先頭900字がほぼ全部これ）。**素材そのものは
# 削らない**（画面に出すのは原文のまま）が、**読む窓**からは外す——でないと事業の記述に届かない。
BOILER = re.compile(r'(?i)(free of charge|Securities and Exchange Commission|Exchange Act of 1934'
                    r'|incorporated by reference|registered trademarks?|trademarks of'
                    r'|Internet address|on our website|our website at|www\.|http'
                    r'|Form 10-K, [Qq]uarterly [Rr]eports|proxy statements'
                    r'|as soon as reasonably practical)')


def readable(m):
    """定型の文だけ落とした読む窓。落としすぎたら元へ戻す（消して読めなくなっては本末転倒）。"""
    sents = re.split(r'(?<=[.;])\s+', m)
    keep = ' '.join(x for x in sents if not BOILER.search(x)).strip()
    return keep if len(keep) >= 300 else m


def material(p):
    """素材＝**原本由来のものは全部**。原本の英文(biz)と、台帳の _meta.evidence（審査官が
    原本から日本語で書いた事業の事実 seg/pos/dep）。**どちらも原本由来なので両方使う**——
    biz だけに絞ると、Item1 の冒頭が沿革と定型で埋まっていて事業の記述に届かない社
    （実測 HWM は1600字すべてが所在地・旧社名・分社の経緯）で何も書けなくなる。"""
    parts = []
    if p.get('biz'):
        parts.append(('biz', p['biz']))
    meta = '\n'.join(x for x in (p.get('seg'), p.get('pos'), p.get('dep')) if x)
    if meta:
        parts.append(('meta', meta))
    if not parts:
        return '', None
    return '\n'.join(t for _, t in parts), '+'.join(k for k, _ in parts)


def fp(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:12]


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def state():
    src = load(SRC, {}).get('items', {})
    cur = load(DST, {}).get('items', {})
    rows = []
    for t, p in src.items():
        m, kind = material(p)
        rec = cur.get(t)
        st = ('材料なし' if not kind else
              '未訳' if not rec else
              '素材が変わった' if rec.get('h') != fp(m) else '✓')
        rows.append({'t': t, 'nm': p.get('nm') or t, 'kind': kind,
                     'mlen': len(m), 'state': st,
                     'ja': (rec or {}).get('ja'), 'src': (rec or {}).get('src')})
    orphan = sorted(set(cur) - set(src))
    return src, cur, rows, orphan


def cmd_audit(as_json):
    src, cur, rows, orphan = state()
    by = {}
    for r in rows:
        by.setdefault(r['state'], []).append(r)
    if as_json:
        out = {'generated': time.strftime('%Y-%m-%d'),
               'total': len(rows),
               'counts': {k: len(v) for k, v in by.items()},
               'orphan': orphan,
               'todo': [{'t': r['t'], 'nm': r['nm'], 'state': r['state'],
                         'kind': r['kind']}
                        for r in rows if r['state'] in ('未訳', '素材が変わった')],
               'note': '事業説明の日本語要約の被覆。**表示専用・判定には一切使わない**。'
                       'todo=未訳＋素材が変わった社（📋今日タブが読む）。'
                       '材料なし＝原本の英文も台帳の日本語根拠も無い社＝穴として明示（憶測で書かない）'}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        # 空書き込みの検問（audit_stale_bs:243 と同じ言葉）——素材の目録(profiles.json)が
        # 読めていないのに 0 で上書きすると、📋今日タブが「未訳は無い」と嘘をつく。
        # ⚠ 錨は rows（母数）であって todo ではない（todo が 0 なのは正常な状態）。
        if not rows:
            print('⚠ profiles.json が読めない（0社）ので out/profiles_ja_audit.json は書かない',
                  file=sys.stderr)
            return 1
        with open(os.path.join(ROOT, 'out', 'profiles_ja_audit.json'), 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        return 0
    print(f"事業説明の日本語要約 — 全 {len(rows)} 社")
    for k in ('✓', '未訳', '素材が変わった', '材料なし'):
        v = by.get(k, [])
        print(f"  {k:8s} {len(v):4d}")
        if k in ('未訳', '素材が変わった') and v:
            for r in v[:40]:
                print(f"      {r['t']:8s} {r['nm'][:26]:28s} 素材={r['kind']}({r['mlen']}字)")
            if len(v) > 40:
                print(f"      … 他 {len(v)-40} 社")
        if k == '材料なし' and v:
            print('      ' + ' '.join(r['t'] for r in v)
                  + '  ← 原本の英文も台帳の日本語根拠も無い＝**穴として明示**（憶測で書かない）')
    if orphan:
        print(f"  孤児     {len(orphan)}  {' '.join(orphan)}  ← profiles.json に居ない")
    return 0


def cmd_add():
    """標準入力の {ticker: 日本語} をマージ。指紋は**道具が計算する**（手で書かせない）。"""
    patch = json.load(sys.stdin)
    src = load(SRC, {}).get('items', {})
    cur = load(DST, {'items': {}})
    items = cur.get('items', {})
    ok = rej = 0
    for t, ja in patch.items():
        p = src.get(t)
        if not p:
            print(f"  拒否 {t}: profiles.json に居ない"); rej += 1; continue
        m, kind = material(p)
        if not kind:
            print(f"  拒否 {t}: 素材が無い（原本の英文も台帳の日本語根拠も無い）"); rej += 1; continue
        ja = str(ja or '').strip()
        if not JA.search(ja):
            print(f"  拒否 {t}: 日本語が含まれていない"); rej += 1; continue
        if not (MINLEN <= len(ja) <= MAXLEN):
            print(f"  拒否 {t}: 長さ {len(ja)} 字（{MINLEN}〜{MAXLEN} 字）"); rej += 1; continue
        items[t] = {'ja': ja, 'src': kind, 'h': fp(m), 'mlen': len(m),
                    'date': time.strftime('%Y-%m-%d')}
        ok += 1
    if not ok:
        print(f"書き込まずに終了（採用0・拒否{rej}）"); return 1
    tmp = DST + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'generated': time.strftime('%Y-%m-%d'), 'n': len(items),
                   'note': ('事業説明の日本語要約。**表示専用・判定には一切使わない**。'
                            '素材は原本(10-K/20-F)の Item1 冒頭、無ければ台帳の _meta.evidence'
                            '（審査官が原本から日本語で書いた事業の事実）。要約は審査官が素材だけから書き、'
                            '素材は画面に必ず併記する（食い違えば読み手が気づける）。'
                            'h=素材の指紋／mlen=素材の文字数——どちらも端末（この道具・CI）が照合する。'
                            '**門(ブラウザ)は照合しない**（_meta を読めないのと同じ理由で素材の同一性を'
                            '検証できない）。門にできるのは素材を必ず併記して、食い違いを読み手が'
                            '見つけられる形にするところまで。'
                            '素材が変われば訳は自動で「古い」へ落ちて作業リストへ戻る'),
                   'items': dict(sorted(items.items()))}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DST)
    print(f"採用 {ok} 社・拒否 {rej} 社 → {os.path.relpath(DST, ROOT)}（在庫 {len(items)} 社）")
    return 0


def prio():
    """作業の順＝効く順。投下可 → 次点 → Ω降順。score_all の結果を**読むだけ**（判定は作らない）。"""
    sa = load(os.path.join(ROOT, 'out', 'score_all.json'), {})
    rows = sa.get('rows', sa) if isinstance(sa, dict) else sa
    r = {}
    if isinstance(rows, list):
        for x in rows:
            t = str(x.get('t') or x.get('nm', '')).split()[0].upper()
            if t:
                r[t] = (0 if x.get('buy') else 1 if x.get('quali') else 2, -(x.get('s') or 0))
    return lambda t: r.get(t.upper(), (3, 0))


def cmd_next(n, only=None):
    """未訳（または素材が変わった）社を n 社、**素材つき**で出す。これを読んで訳を書く。"""
    src, cur, rows, _ = state()
    k = prio()
    todo = [x for x in rows if x['state'] in ('未訳', '素材が変わった')]
    if only:
        want = {y.upper() for y in only}
        todo = [x for x in todo if x['t'].upper() in want]
    todo.sort(key=lambda x: k(x['t']))
    for x in todo[:n]:
        p = src[x['t']]
        m, kind = material(p)
        # 窓は「読むのに足りる最小」。biz があれば meta は補助なので短く、無ければ meta を厚く
        b = readable(p['biz'])[:900] if p.get('biz') else ''
        mt = '\n'.join(x for x in (p.get('seg'), p.get('pos'), p.get('dep')) if x)[:450 if b else 900]
        m = (b + ('\n〔台帳の審査根拠〕' + mt if mt else '')) if b else mt
        print(f"@@@ {x['t']} | {p.get('nm')} | {p.get('sic') or 'SIC不明'} | "
              f"素材={kind} | {p.get('form','')} {p.get('rdate','')}")
        print(re.sub(r"\s+", " ", m).strip())
        print()
    print(f"--- 残り {len(todo)} 社（この出力は先頭 {min(n,len(todo))} 社）")
    return 0


def cmd_reindex():
    """素材の定義を変えたときだけ使う。指紋と長さを振り直し、訳文には触らない。
    ⚠原本が変わったときに使ってはいけない——それは『素材が変わった＝訳し直し』の規律そのもの。"""
    src = load(SRC, {}).get('items', {})
    cur = load(DST, {'items': {}})
    items = cur.get('items', {})
    n = 0
    for t, rec in items.items():
        p = src.get(t)
        if not p:
            continue
        m, kind = material(p)
        if not kind:
            continue
        if rec.get('h') != fp(m) or rec.get('src') != kind:
            rec['h'], rec['mlen'], rec['src'] = fp(m), len(m), kind
            n += 1
    with open(DST, 'w', encoding='utf-8') as f:
        json.dump({**cur, 'items': dict(sorted(items.items()))}, f, ensure_ascii=False, indent=1)
    print(f'指紋を振り直した: {n} 社（訳文は触っていない）')
    return 0


def cmd_show(t):
    src, cur, _, _ = state()
    p = src.get(t)
    if not p:
        print('profiles.json に居ない'); return 1
    m, kind = material(p)
    print(f"=== {p.get('nm')}  素材={kind}  {len(m)}字  {p.get('form','')}  {p.get('rdate','')}")
    print(m[:1200])
    r = cur.get(t)
    print('\n--- 訳 ---')
    print((r or {}).get('ja') or '(未訳)')
    if r:
        print(f"  指紋 {r['h']} / 今の素材 {fp(m)} → " + ('✓一致' if r['h'] == fp(m) else '⚠素材が変わった'))
    return 0


if __name__ == '__main__':
    try:                       # head で切られても落ちない（落ちると検査が失敗したように見える）
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
    a = sys.argv[1:]
    if '--add' in a:
        sys.exit(cmd_add())
    if '--next' in a:
        i = a.index('--next')
        n = int(a[i + 1]) if len(a) > i + 1 and a[i + 1].isdigit() else 12
        only = None
        if '--only' in a:
            only = a[a.index('--only') + 1].split(',')
        sys.exit(cmd_next(n, only))
    if '--reindex' in a:
        sys.exit(cmd_reindex())
    if '--show' in a:
        sys.exit(cmd_show(a[a.index('--show') + 1].upper()))
    try:
        sys.exit(cmd_audit('--json' in a))
    except BrokenPipeError:
        try:
            os.close(1)
        except Exception:
            pass
        sys.exit(0)
