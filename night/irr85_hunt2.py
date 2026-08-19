#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
night/irr85_hunt2.py — **irr=85 の機構を「意味の語彙」で全母集団から掃く**（2026-08-19新設・第二次）

■ なぜ第二次が要るか（第一次 2026-08-08 の限界は、その日の記録が自分で書いている）
  第一次の語彙は24本で、**すべて確定済み85の実文から作った**（qualif / certif / design-in / supplier の派生）。
  だから記録はこう締めている——「フレーズは確定済み85の実文から作ったので、
  **まだ見たことのない言い回しの機構は原理的に拾えない**」。
  実際 403社を読んで85の提案は22社、**反証で22社とも潰れた**（精度0）。
  ⇒ 第二次は語彙を**機構の"意味"から**組み直す。同じ機構が、別の規制・別の産業では
     まったく違う単語で書かれる（PPAP / prior approval supplement / source approval request /
     ICC-ES evaluation report / statistical agent …）。そこを狙う。

■ 前回の網が構造的に持っていた穴を、この道具は3つ塞ぐ
  (1) **添付書類(exhibit)を採っていた可能性**を塞ぐ。EDGAR全文検索のヒットには
      EX-10.51（供給契約書）等が混ざる——契約書に "qualification process" が出るのは当たり前で、
      **機構の証拠にならない**。file_type が root form と一致する**本文だけ**を採る。
      実測: "prior approval supplement" は1ページ100件中 本文36件＝**64%が添付書類**だった
  (2) **特異性を自己申告で信じない**。語彙の出し手は specificity を申告するが、それは推測。
      `--stats` が**実測のヒット数**を測り、閾値を超えるフレーズは名指しで落とす（黙って落とさない）。
  (3) **順位を門0の機械スコアで付けない**。実測（out/irr_coverage.json の yield_by_score）——
      irr=85 が出た社の門0スコアは 7点3社 / 6点2 / 5点1 / **4点3 / 3点3 / 2点1** ＝**半分が4点以下**。
      LRCXの2012年は門0スコア2/7・営業利益率3.3%・ROIC3.7%からの13年で75倍だった。
      機械の質で並べると、機構を持つ社の半分を最後尾へ送ることになる。
      ⇒ 順位は**方向（dir）と反証語の差**だけで付ける。

■ 絶対のルールとの関係
  - この道具は**候補を出すだけで、刻みを一つも決めない**。判定は原本を読む審査官の仕事（ルール2）。
  - **切り捨てを黙ってやらない**（ページ上限に当たったフレーズ・除外した社は理由つきで出す）。
  - 空書き込みの検問つき（1件も取れていないのに在庫を上書きしない）。

■ 使い方
  python3 night/irr85_hunt2.py --stats          語彙の特異性を実測（ヒット数だけ・安い）
  python3 night/irr85_hunt2.py --screen         本スクリーン（全ヒットを集める）
  python3 night/irr85_hunt2.py --rank           読む順を作る
  オプション: --vocab <path> --window-start YYYY-MM-DD --max-hits N --only "phrase"

■ 在庫
  入力 night/irr85_vocab2.json    {phrases:[{p,dir,...}], anti:[{p,why}]}
  出力 out/irr85_hunt2_stats.json     フレーズごとの実測ヒット数（特異性の判定つき）
       out/irr85_hunt2_universe.json  CIKごとの全ヒット
       out/irr85_hunt2_readlist.json  読む順（審査へ渡す作業リスト）
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'out')
UA = {'User-Agent': 'ccf-gate fortis5280@gmail.com'}
EFTS = 'https://efts.sec.gov/LATEST/search-index?'
FORMS = '10-K,20-F,40-F'
ROOTSET = {'10-K', '20-F', '40-F'}

# フレーズ1本あたりのページ上限（1ページ100件）。超えたら truncated として名指しで出す
MAX_PAGES = 20
# 実測ヒット数がこれを超えるフレーズは「網を潰す」ので本スクリーンから外す（--stats が判定）
FLOOD = 1500
# ★語のAND検索（引用符つきが0件だった救済経路）は**別の閾値で裁く**。
#   完全一致のヒットは「その言い回しが在る」証拠だが、AND検索のヒットは
#   「その単語が200頁のどこかに在る」だけ——証拠の強さが違うものを同じ線で扱うのは
#   この台帳が11回踏んだ「基準の違う二つを並べる」型。実測でも
#   "require additional flight testing"(AND) は1425件＝ほぼ全部が無関係
FLOOD_TERMS = 250

TOOL_REV = 'r1 (2026-08-19)'


def get(url, tries=5):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                return json.loads(r.read())
        except Exception as e:          # 500 が散発する（実測）。指数バックオフで粘る
            last = e
            time.sleep(0.6 * (2 ** i))
    raise RuntimeError(f'EDGAR FTS 不通: {last}')


def fts(phrase, start, end, frm=0, quoted=True):
    """★引用符つき＝完全一致。引用符なし＝語のAND。**この二つは証拠の強さが違う**。

    ⚠ 私は最初「引用符つきは取りこぼす欠陥がある」と誤診した（"asme section iii" が0件なのに
      引用符なしは60件だったため）。**取ってきて確かめたら外れていた**——AND検索の60件は
      どれも "asme section iii" を literally 含まず、'asme' と 'section' と 'iii' が
      別々の場所に在るだけだった。⇒ **完全一致の検索は壊れていない。0件は本当に0件。**
      （"10 CFR 50.59" が0で "10 CFR Part 50" が6件なのも同じ——後者のほうが実際に使われる書き方）
      強い結論ほど先に道具を疑う、は正しい作法だが、**疑った結果が外れたらそれも書く**。

    それでもAND検索を残すのは、**近い変種**を拾う経路として使えるから
    （"witness and hold points" が0でも "witness and hold point inspections" は在りうる）。
    ただし証拠としては弱いので閾値を別に持ち（FLOOD_TERMS）、--material 段で
    「同じ段落に全部の語が在るか」の緩い照合をして初めて材料に載せる。
    """
    p = {'q': (f'"{phrase}"' if quoted else phrase), 'forms': FORMS, 'dateRange': 'custom',
         'startdt': start, 'enddt': end, 'from': str(frm)}
    return get(EFTS + urllib.parse.urlencode(p))


def hits_of(phrase, start, end, max_pages=MAX_PAGES, quoted=True):
    """本文だけを返す。(total, rows, truncated)"""
    d = fts(phrase, start, end, quoted=quoted)
    total = d['hits']['total']['value']
    rows, page = [], 0
    while True:
        for h in d['hits']['hits']:
            s = h['_source']
            # ★添付書類を落とす——契約書の "qualification" は機構の証拠にならない
            if s.get('file_type') not in ROOTSET:
                continue
            ciks = s.get('ciks') or []
            rows.append({
                'cik': (ciks[0] if ciks else '').lstrip('0').zfill(10),
                'name': (s.get('display_names') or [''])[0],
                'form': s.get('file_type'),
                'filed': s.get('file_date'),
                'sic': (s.get('sics') or [None])[0],
                'doc': h['_id'],
            })
        page += 1
        got = (page) * 100
        if got >= total or page >= max_pages:
            break
        time.sleep(0.13)
        d = fts(phrase, start, end, frm=got, quoted=quoted)
    return total, rows, (total > page * 100)


def load_vocab(path):
    v = json.load(open(path, encoding='utf-8'))
    ph = v.get('phrases') or []
    an = v.get('anti') or []
    # 同一フレーズは lens をまとめて1本に（同じ語を二度投げない）
    seen = {}
    for p in ph:
        k = p['p'].strip().lower()
        if not k:
            continue
        if k in seen:
            seen[k]['lens'] = sorted(set(seen[k].get('lens', '').split(',') + [p.get('lens', '')]))
            seen[k]['lens'] = ','.join(x for x in seen[k]['lens'] if x)
            # dir は強いほうを採る（customer_bears > lock_evidence > neutral）
            rank = {'customer_bears': 0, 'lock_evidence': 1, 'neutral': 2}
            if rank.get(p.get('dir'), 9) < rank.get(seen[k].get('dir'), 9):
                seen[k]['dir'] = p['dir']
            continue
        q = dict(p)
        q['p'] = k
        seen[k] = q
    aseen = {}
    for a in an:
        k = (a.get('p') or '').strip().lower()
        if k and k not in aseen:
            aseen[k] = dict(a, p=k)
    return list(seen.values()), list(aseen.values())


def ticker_cik_map():
    """ティッカー→CIK。SECの正本を1日キャッシュする（推測しない）"""
    cache = os.path.join(OUT, '_ticker_cik.json')
    if os.path.exists(cache) and (time.time() - os.path.getmtime(cache)) < 86400 * 7:
        return json.load(open(cache, encoding='utf-8'))
    try:
        j = get('https://www.sec.gov/files/company_tickers.json')
    except Exception as e:
        print(f'  （company_tickers.json 取得失敗: {e}）', file=sys.stderr)
        return json.load(open(cache, encoding='utf-8')) if os.path.exists(cache) else {}
    m = {v['ticker'].upper(): str(v['cik_str']).zfill(10) for v in j.values()}
    json.dump(m, open(cache, 'w', encoding='utf-8'))
    return m


def gate0_map():
    """門0の母集団（gate0_all.csv）をティッカーで引く。
    ★母集団に**無い**社は「門0の穴」として別立てで出す——RBC(irr=85・13年で年率+20.5%)は
      売上タグの決算日の錨のずれで母集団から丸ごと消えていた前例がある（HOYAも同型）。
      機構を持つ社が門0の外に居ることは実際に起きる。"""
    m = {}
    p = os.path.join(ROOT, 'gate0_all.csv')
    if not os.path.exists(p):
        return m
    import csv
    with open(p, encoding='utf-8-sig') as f:      # ⚠BOM付き。utf-8 で開くと ticker 列が空になり
        for r in csv.DictReader(f):               #   「漏れ0社」というもっともらしい嘘が出る（既記録）
            t = (r.get('ticker') or '').strip().upper()
            if t:
                m[t] = r
    return m


def ticker_of(display_name):
    m = re.search(r'\(([A-Z0-9.\-]{1,6})\)\s*\(CIK', display_name or '')
    return m.group(1) if m else None


def excluded_sets():
    """除外する社と理由。**黙って消さないため理由を持ち回す**"""
    ex = {}
    # ⚠ パックは cik 欄を持たない（実測: 369/369 で不在）。**推測せず _meta.source のURLから採る**
    #    ——SECの提出URLは /Archives/edgar/data/{cik}/… なので一意に決まる。
    #    取れない社（日本株の有報など）は除外できない＝**除外漏れは名指しで出す**（黙って落とさない）
    tmap = ticker_cik_map()
    miss = []
    for p in glob.glob(os.path.join(OUT, '*_gate_pack.json')):
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        t = os.path.basename(p).replace('_gate_pack.json', '')
        src = str((d.get('_meta') or {}).get('source') or '')
        m = re.search(r'/edgar/data/(\d+)', src)
        cik = None
        if m:
            cik = m.group(1).lstrip('0').zfill(10)
        elif t.upper() in tmap:
            cik = tmap[t.upper()]
        # ⚠ accession の頭10桁を CIK と読んではいけない——**代理提出者の番号のことがある**。
        #    実測: HXL の source は accession 0001193125-… で、0001193125 は Donnelley（提出代行）で
        #    Hexcel(0000717605) ではない。この読み方だと審査済みの社が除外を素通りして作業リストを汚す
        if cik:
            ex.setdefault(cik, ('パックがある（審査済み）', t))
        else:
            miss.append(t)
    if miss:
        print(f'  （CIKが引けず除外できないパック {len(miss)}社（大半は日本株＝SEC経路の外）: '
              f'{" ".join(sorted(miss)[:8])}{" …" if len(miss) > 8 else ""}）', file=sys.stderr)
    for f, why in (('irr85_hunt_readlist.json', '第一次(2026-08-08)で読了'),
                   ('irr85_hunt_20f_readlist.json', '第一次(20-F)で読了')):
        p = os.path.join(OUT, f)
        if not os.path.exists(p):
            continue
        for r in json.load(open(p, encoding='utf-8')):
            c = str(r.get('cik') or '').strip()
            if c:
                ex.setdefault(c.lstrip('0').zfill(10), (why, r.get('t')))
    return ex


def cmd_stats(a):
    ph, an = load_vocab(a.vocab)
    if a.only:
        ph = [p for p in ph if a.only.lower() in p['p']]
    rows = []
    for i, p in enumerate(ph, 1):
        try:
            d = fts(p['p'], a.window_start, a.window_end)
            tot = d['hits']['total']['value']
            body = sum(1 for h in d['hits']['hits'] if h['_source'].get('file_type') in ROOTSET)
            seen = len(d['hits']['hits']) or 1
            if tot == 0:
                # ★引用符つきの0件は測定の欠陥のことがある。語のAND検索へ落として拾い直す
                time.sleep(0.13)
                d2 = fts(p['p'], a.window_start, a.window_end, quoted=False)
                t2 = d2['hits']['total']['value']
                rows.append({**p, 'total': 0, 'total_terms': t2, 'mode': 'terms',
                             'verdict': ('flood_terms' if t2 > FLOOD_TERMS
                                         else ('dead' if t2 == 0 else 'ok_terms'))})
            else:
                rows.append({**p, 'total': tot, 'mode': 'phrase', 'body_ratio': round(body / seen, 3),
                             'verdict': 'flood' if tot > FLOOD else 'ok'})
        except Exception as e:
            rows.append({**p, 'total': None, 'verdict': 'error', 'err': str(e)[:120]})
        if i % 20 == 0:
            print(f'  … {i}/{len(ph)}', file=sys.stderr)
        time.sleep(0.13)
    ok = [r for r in rows if r['verdict'] == 'ok']
    okt = [r for r in rows if r['verdict'] == 'ok_terms']
    fl = [r for r in rows if r['verdict'] in ('flood', 'flood_terms')]
    dd = [r for r in rows if r['verdict'] == 'dead']
    er = [r for r in rows if r['verdict'] == 'error']
    out = {'generated': dt.date.today().isoformat(), 'tool': 'night/irr85_hunt2.py', 'tool_rev': TOOL_REV,
           'window': [a.window_start, a.window_end], 'flood_threshold': FLOOD, 'flood_threshold_terms': FLOOD_TERMS,
           'note': ('⚠ 引用符つきの0件は「使われていない」ではない——EDGAR全文検索の取りこぼし。'
                    '実測 "asme section iii" 0件 vs 引用符なし60件。0件は語のAND検索へ落として拾い、'
                    '文字列の実在は --material の全文走査が裁く'),
           'n': {'phrases': len(rows), 'ok': len(ok), 'ok_terms': len(okt),
                 'flood': len(fl), 'dead': len(dd), 'error': len(er)},
           'rows': sorted(rows, key=lambda r: -(r.get('total') or 0)), 'anti': an}
    if not rows:
        print('✗ 1本も測れていない＝在庫を上書きしない', file=sys.stderr)
        return 1
    json.dump(out, open(os.path.join(OUT, 'irr85_hunt2_stats.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"語彙 {len(rows)}本 → 完全一致で使える {len(ok)} / 語AND で拾える {len(okt)} / "
          f"洪水 {len(fl)} / 本当に0件 {len(dd)} / 失敗 {len(er)}")
    if fl:
        print('\n■ 洪水（>%d件・本スクリーンから外す）' % FLOOD)
        for r in fl[:30]:
            print(f"  {r['total']:>7}  {r['p']}")
    if dd:
        print('\n■ 0件（実在しない言い回しか、窓の外）')
        print('  ' + ' / '.join(r['p'] for r in dd[:40]))
    return 0


def cmd_screen(a):
    st_path = os.path.join(OUT, 'irr85_hunt2_stats.json')
    ph, an = load_vocab(a.vocab)
    keep = None
    if os.path.exists(st_path):
        s = json.load(open(st_path, encoding='utf-8'))
        keep = {r['p']: r.get('mode', 'phrase') for r in s['rows']
                if r['verdict'] in ('ok', 'ok_terms')}
        print(f"（--stats の実測に従い {len(keep)}本だけ投げる）")
    if a.only:
        ph = [p for p in ph if a.only.lower() in p['p']]
    elif keep is not None:
        ph = [dict(p, mode=keep[p['p']]) for p in ph if p['p'] in keep]

    ex = excluded_sets()
    g0 = gate0_map()
    uni, trunc, err = {}, [], []
    for i, p in enumerate(ph, 1):
        try:
            total, rows, tr = hits_of(p['p'], a.window_start, a.window_end,
                                      quoted=(p.get('mode', 'phrase') == 'phrase'))
        except Exception as e:
            err.append({'p': p['p'], 'err': str(e)[:140]})
            continue
        if tr:
            trunc.append({'p': p['p'], 'total': total, 'read': MAX_PAGES * 100})
        for r in rows:
            u = uni.setdefault(r['cik'], {'cik': r['cik'], 'name': r['name'], 'sic': r['sic'],
                                          'forms': set(), 'docs': {}, 'ph': {}, 'anti': {}})
            u['forms'].add(r['form'])
            u['ph'][p['p']] = u['ph'].get(p['p'], 0) + 1
            u['docs'][r['doc']] = r['filed']
        if i % 10 == 0:
            print(f'  … {i}/{len(ph)}  社数 {len(uni)}', file=sys.stderr)
        time.sleep(0.13)

    # ★反証語はここでは投げない。全文が手に入る --material 段で見る——
    #   (a) 安い（反証語は一般語が多く、FTSだと洪水になって網を潰す）
    #   (b) 正確（同じ文書に在るかだけでなく、**どのItem・どの見出しの下に在るか**まで判る。
    #       22件の失敗はどれも「置き場所」で決まっていた）
    if not uni:
        print('✗ 1社も当たっていない＝在庫を上書きしない', file=sys.stderr)
        return 1

    dirs = {p['p']: p.get('dir', 'neutral') for p in ph}
    rows = []
    for c, u in uni.items():
        hit = sorted(u['ph'].items(), key=lambda kv: -kv[1])
        cb = [k for k, _ in hit if dirs.get(k) == 'customer_bears']
        le = [k for k, _ in hit if dirs.get(k) == 'lock_evidence']
        ne = [k for k, _ in hit if dirs.get(k) == 'neutral']
        e = ex.get(c)
        tk = ticker_of(u['name'])
        g = g0.get(tk or '')
        rows.append({'cik': c, 'name': u['name'], 'ticker': tk, 'sic': u['sic'],
                     'in_gate0': bool(g), 'g0_score': (g or {}).get('score'),
                     'g0_fails': (g or {}).get('fails'), 'forms': sorted(u['forms']),
                     'doc': sorted(u['docs'].items(), key=lambda kv: kv[1])[-1][0] if u['docs'] else None,
                     'filed': max(u['docs'].values()) if u['docs'] else None,
                     'customer_bears': cb, 'lock_evidence': le, 'neutral': ne,
                     'anti': sorted(u['anti'].keys()),
                     'excluded': (e[0] if e else None), 'excluded_t': (e[1] if e else None)})
    out = {'generated': dt.date.today().isoformat(), 'tool': 'night/irr85_hunt2.py', 'tool_rev': TOOL_REV,
           'window': [a.window_start, a.window_end], 'forms': FORMS,
           'note': '本文のみ（添付書類は落とす）。除外した社も理由つきで残す＝黙って消さない',
           'n': {'phrases_sent': len(ph), 'anti_sent': 0, 'ciks': len(rows),
                 'excluded': sum(1 for r in rows if r['excluded']),
                 'outside_gate0': sum(1 for r in rows if not r['excluded'] and not r['in_gate0'])},
           'truncated': trunc, 'errors': err, 'rows': rows}
    json.dump(out, open(os.path.join(OUT, 'irr85_hunt2_universe.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"\n当たった社 {len(rows)}（うち審査済みで除外 {out['n']['excluded']} ／ "
          f"門0の母集団の外 {out['n']['outside_gate0']}）／投げたフレーズ {len(ph)}")
    if trunc:
        print(f"⚠ ページ上限に当たったフレーズ {len(trunc)}本（黙って切っていない）:")
        for t in trunc[:10]:
            print(f"   {t['p']}  total={t['total']} 読了={t['read']}")
    if err:
        print(f"⚠ 取得に失敗 {len(err)}本")
    return 0


def cmd_rank(a):
    u = json.load(open(os.path.join(OUT, 'irr85_hunt2_universe.json'), encoding='utf-8'))
    rows = [r for r in u['rows'] if not r['excluded']]
    def score(r):
        # ★門0スコアもΩも使わない（irr=85 の半分は門0スコア4点以下から出る）
        return (len(r['customer_bears']) * 5 + len(r['lock_evidence']) * 2
                + len(r['neutral']) * 0.4 - len(r['anti']) * 1.5)
    for r in rows:
        r['rank_score'] = round(score(r), 2)
    rows.sort(key=lambda r: -r['rank_score'])
    out = {'generated': dt.date.today().isoformat(), 'tool': 'night/irr85_hunt2.py', 'tool_rev': TOOL_REV,
           'note': ('読む順＝方向(customer_bears)×5 + 固着(lock_evidence)×2 + 機構語×0.4 − 反証語×1.5。'
                    '門0スコアもΩも使わない——実測で irr=85 の半分は門0スコア4点以下から出るため'),
           'n': {'total': len(u['rows']), 'excluded': len(u['rows']) - len(rows), 'readable': len(rows)},
           'rows': rows}
    json.dump(out, open(os.path.join(OUT, 'irr85_hunt2_readlist.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"読む候補 {len(rows)}社（除外 {out['n']['excluded']}社は理由つきで universe に残っている）\n")
    print(f"{'順':>3} {'T/社名':38}{'SIC':>6}{'門0':>5}{'点':>7}  顧客負担 / 固着")
    for i, r in enumerate(rows[:40], 1):
        nm = (r['name'] or '')[:36]
        g0 = (r.get('g0_score') if r.get('in_gate0') else '穴')
        print(f"{i:>3} {nm:38}{str(r['sic'] or ''):>6}{str(g0):>5}{r['rank_score']:7.1f}  "
              f"{len(r['customer_bears'])} / {len(r['lock_evidence'])}")
    return 0


def cmd_material(a):
    """★読み手へ配る材料を1回の取得で作る（v9.9.65: 同じ材料を全員が見る）

    readlist の上位を順に取り、night/irr85_section.py の scan をそのまま呼んで
    機構文の**置き場所**（Item・直前の見出し3つ・全文での出現回数）と反証語の同居を採る。
    判定は一切しない——判定は原本を読む審査官の仕事（絶対のルール2）。
    """
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location('_sec', os.path.join(HERE, 'irr85_section.py'))
    sec = _iu.module_from_spec(_sp)
    _sp.loader.exec_module(sec)

    rl = json.load(open(os.path.join(OUT, 'irr85_hunt2_readlist.json'), encoding='utf-8'))
    ph, an = load_vocab(a.vocab)
    dirs = {p['p']: p.get('dir', 'neutral') for p in ph}
    phrases = sorted(dirs)
    antis = sorted({x['p'] for x in an})

    # terms モードで拾ったフレーズ（完全一致では0件だったもの）を緩い照合へ回す
    loose_ph = []
    stp = os.path.join(OUT, 'irr85_hunt2_stats.json')
    if os.path.exists(stp):
        loose_ph = [x['p'] for x in json.load(open(stp, encoding='utf-8'))['rows']
                    if x.get('verdict') == 'ok_terms']
    rows = rl['rows'][:a.limit]
    out_path = os.path.join(OUT, 'irr85_hunt2_material.json')
    done = {}
    if os.path.exists(out_path) and not a.fresh:
        done = {r['cik']: r for r in json.load(open(out_path, encoding='utf-8'))['rows']}
        print(f'  既存 {len(done)}社は再取得しない')

    res, fail = [], []
    for i, r in enumerate(rows, 1):
        if r['cik'] in done:
            res.append(done[r['cik']])
            continue
        try:
            adsh, fn = r['doc'].split(':', 1)
            url = f"https://www.sec.gov/Archives/edgar/data/{int(r['cik'])}/{adsh.replace('-', '')}/{fn}"
            lines = sec.fetch_text(url)
            hits, counts, items, toc = sec.scan(lines, phrases + antis, maxn=40)
            # ★terms モードで見つけた社は完全一致では当たらないことがある。
            #   「同じ段落に全部の語が在る」まで緩めて拾い直す（近い変種のため）。
            #   ⚠ 緩い照合は別の欄に入れる——完全一致と混ぜると証拠の強さが判らなくなる
            loose = []
            if loose_ph:
                for ln in lines:
                    if not (60 <= len(ln) <= 2400):
                        continue
                    low = ln.lower()
                    for lp in loose_ph:
                        toks = [t for t in lp.split() if len(t) > 2]
                        if toks and all(t in low for t in toks) and lp not in low:
                            loose.append({'phrase': lp, 'text': ln[:900]})
                            break
                    if len(loose) >= 8:
                        break
            for h in hits:
                h['dir'] = sorted({dirs.get(p, 'ANTI' if p in antis else 'neutral') for p in h['phrases']})
            # ★反証語は「文書のどこかに在る」では減点にならない。
            #   実測: LOAR（3ビンテージ確定の85）は 'barriers to entry' が6回出る——航空防衛の10-Kでは常態。
            #   22件の失敗の型(4)は「**機構文そのものが**参入障壁の記述だった」であって、
            #   語が別の場所に在ることではない。⇒ **同じ段落に同居しているか**だけを数える
            nAdoc = sum(1 for h in hits if 'ANTI' in h['dir'])
            nA = sum(1 for h in hits if 'ANTI' in h['dir']
                     and ('customer_bears' in h['dir'] or 'lock_evidence' in h['dir']))
            nC = sum(1 for h in hits if 'customer_bears' in h['dir'])
            res.append({**{k: r[k] for k in ('cik', 'name', 'sic', 'filed', 'doc', 'rank_score')},
                        'url': url, 'items': items[:30], 'n_lines': len(lines),
                        'n_hits': len(hits), 'n_customer_bears': nC,
                        'n_anti': nA, 'n_anti_doc': nAdoc,
                        'counts': {p: c for p, c in counts.items() if c},
                        'loose': loose, 'hits': hits})
        except Exception as e:
            fail.append({'cik': r['cik'], 'name': r['name'], 'err': str(e)[:160]})
        if i % 10 == 0:
            print(f'  … {i}/{len(rows)}  取得済 {len(res)} 失敗 {len(fail)}', file=sys.stderr)
        time.sleep(0.15)

    if not res:
        print('✗ 1社も取れていない＝在庫を上書きしない', file=sys.stderr)
        return 1
    # 材料が揃ったので順位を作り直す（置き場所を織り込む）
    for r in res:
        body = sum(1 for h in r['hits'] if 'customer_bears' in h['dir'] and not h['cust'] is False)
        risk = sum(1 for h in r['hits']
                   if 'customer_bears' in h['dir'] and (h['item'] or '').lower().startswith('item 1a'))
        r['refined'] = round(r['n_customer_bears'] * 5 + body * 1.5 - risk * 1.0
                             - r['n_anti'] * 3.0, 2)   # 同居する反証語だけを、強く引く
    res.sort(key=lambda r: -r['refined'])
    json.dump({'generated': dt.date.today().isoformat(), 'tool': 'night/irr85_hunt2.py --material',
               'tool_rev': TOOL_REV,
               'note': ('読み手へ配る材料。判定は一切していない。refined は読む順のためだけの数で、'
                        'Item 1A のリスク見出しの下にある顧客負担文は**減点**する'
                        '（22件の失敗はどれも置き場所で決まった＝ACMR/SPR/TGI型）'),
               'n': {'asked': len(rows), 'got': len(res), 'failed': len(fail)},
               'failures': fail, 'rows': res},
              open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n材料 {len(res)}社（失敗 {len(fail)}）→ out/irr85_hunt2_material.json')
    print(f"{'順':>3} {'社名':40}{'点':>7}{'顧客負担':>9}{'同居反証':>9}{'文書内反証':>11}")
    for i, r in enumerate(res[:30], 1):
        print(f"{i:>3} {(r['name'] or '')[:38]:40}{r['refined']:7.1f}{r['n_customer_bears']:9}"
              f"{r['n_anti']:9}{r.get('n_anti_doc', 0):11}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--screen', action='store_true')
    ap.add_argument('--rank', action='store_true')
    ap.add_argument('--material', action='store_true')
    ap.add_argument('--limit', type=int, default=200)
    ap.add_argument('--fresh', action='store_true')
    ap.add_argument('--vocab', default=os.path.join(HERE, 'irr85_vocab2.json'))
    ap.add_argument('--window-start', default='2024-01-01')
    ap.add_argument('--window-end', default=dt.date.today().isoformat())
    ap.add_argument('--only', default=None)
    a = ap.parse_args()
    if a.stats:
        return cmd_stats(a)
    if a.screen:
        return cmd_screen(a)
    if a.rank:
        return cmd_rank(a)
    if a.material:
        return cmd_material(a)
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
