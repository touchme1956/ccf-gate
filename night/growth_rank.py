#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""night/growth_rank.py — 成長期待枠の候補を、SEC に報告する上場会社から広く探して並べる（読むだけ・判定に不使用）

ユーザー指示（2026-10-05）「成長期待枠を幅広く探してランク付けして」。
成長期待枠は**門の外**で決める（門の点数・四関門は使わない）。並べる物差しは VRT・ANET を選んだときの4条件と同じ
（正本は gate_exceptions.json の VRT/ANET の why・ここで新しい線は作らない）:
  ① アナリスト予想の来期の売上の伸び ≥ +20%（今の会計年度の次の年度 ÷ 今の年度 − 1・Alpha Vantage EARNINGS_ESTIMATES）
  ② 直近2年の売上の伸び ≥ 15%/年（年次報告の売上・2年前 → 最新）
  ③ ROIC ≥ 15%・純有利子負債/EBITDA < 2・株数を増やしていない（dilNet ≤ 1%）・時価総額 ≥ 200億ドル
  ④ ETF経由で総資産の1%以上を持っていない（目標の配分 target.ami_weights を ETF の中身へ分解して数える）
2026-10-05 の初回は「台帳の米国株」から13社だけ予想を取った。ここでは母集団を SEC に報告する会社へ広げる。

■ 段1（全社・SEC frames・鍵なし）
  公開浮動株時価（dei:EntityPublicFloat・各社の最新）≥ 30億ドル の社を母集団にする。
  ＝今の時価総額200億ドルの社が浮動株30億ドル未満になるのは、9割近くを内部者が持つ場合だけ。
  浮動株を報告しない社（20-F 等）は、米国基準・ドルの売上の年次 frames が CY2025 で20億ドル以上なら入れる。
  IFRS の会社は frames に無いので、大型の外国株を EXTRA に名指しで足す（⚠ 手書きの名簿＝網羅ではない）。
  売上の年次 frames（同じタグの組でだけ比べる＝industry_trends と同じ規約）で、CY2023→2025 ≥1.20倍・CY2022→2024 ≥1.20倍・
  CY2024→2025 ≥1.10倍 のどれにも当たらない社だけ外す（②の15%/年＝1.3225倍より緩い＝暦年への寄せのずれ・会計年度の違いで
  取りこぼさないため）。比べられる組が無い社は外さない。
■ 段2（候補・SEC companyfacts）
  採取器 hachimon_fetch.build_numbers をそのまま回す（二重実装しない）→ roic・nde・dilNet。
  ②は採取器と同じ売上の系列（hachimon_fetch.series・会計年度）で測る。株数は dei の表紙の最新。
  キャッシュ out/_growth_cache/{CIK}.json（gitignore・20日で取り直す）
■ 段3
  時価総額: out/growth_mcap.json（取得日つき）→ 無ければ out/dashboard.json の株価 × 表紙の株数。
  ETF経由の比率: out/etf_profiles.json の中身 × portfolio.json の target.ami_weights
  （IFREE-NDX は target.ami_same_index の QQQM で数える）。
■ 段4
  予想: out/growth_estimates.json（Alpha Vantage EARNINGS_ESTIMATES の要約・取得日つき）。
  AV_KEY があれば足りない社を取りに行く（無料枠 25回/日・1秒に1回）。来期の伸びの定義は
  night/watch_exceptions.py の rev_growth_from_estimates と同じ（同じ関数を使う＝出口条件と同じ物差し）。
  ★取れない予想・測れない数字は「満たさない」と読まない（ルール7）——『測れない』として名指しする。

並べ方: ②③④を全部満たし①が取れた社を①の大きい順（①≥20% が成長期待枠の候補）。
  外れた社は、外れた条件の名前つきで下に並べる（幅広く見るため・黙って消さない）。
⚠ 予想の売上の伸びが将来のリターンを上乗せする証拠は無い（門の歴史検証では過去の高成長はむしろ逆の信号だった）。
  これは候補の一覧で、買う判断は人がする。

使い方: python3 night/growth_rank.py [--no-fetch] [--refresh] [--need] [--quiet]
  --no-fetch  ネットに出ない（キャッシュだけで並べる）
  --refresh   段2のキャッシュを取り直す
  --need      予想・時価総額がまだ無い社を書き出す（out/growth_need.json）——取りに行く順の名簿
"""
import datetime
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, 'night'))
import hachimon_fetch as H                                  # noqa: E402  門の採取器そのもの
from industry_trends import frame as us_frame, REV_TAGS     # noqa: E402  SEC frames の取り方とキャッシュ
from watch_exceptions import rev_growth_from_estimates      # noqa: E402  出口条件と同じ「来期の伸び」

TODAY = datetime.date.today().isoformat()
OUT = 'out/growth_rank.json'
EST = 'out/growth_estimates.json'
MCAP = 'out/growth_mcap.json'
NEED = 'out/growth_need.json'
CACHE = 'out/_growth_cache'
FCACHE = 'out/_frames_cache'

FLOAT_MIN = 3e9          # 段1: 公開浮動株時価
REV_MIN_NOFLOAT = 2e9    # 段1: 浮動株を報告しない社の売上
STAGE1_MIN_RATIO = 1.20  # 段1: 2年で1.20倍未満だけ外す（②より緩い）
# 選び方の線（gate_exceptions.json の VRT/ANET の why と同じ。ここで新しい線は作らない）
G_FWD, G_2Y, ROIC_MIN, NDE_MAX, DIL_MAX, MCAP_MIN, ETF_MAX = 20.0, 15.0, 15.0, 2.0, 1.0, 20e9, 1.0
# IFRS の会社は SEC frames に無い——大型の外国株を名指しで足す（⚠ 網羅ではない。足したら理由を書く）
EXTRA = ['TSM', 'ASML', 'SAP', 'ARM', 'SPOT', 'SE', 'NU', 'SHOP', 'NVO', 'RACE', 'CLS', 'NBIS', 'BABA', 'PDD', 'TCOM']

FLAGS = set(sys.argv[1:])
FETCH = '--no-fetch' not in FLAGS
REFRESH = '--refresh' in FLAGS
QUIET = '--quiet' in FLAGS
_AV_DONE = False
_Y_DONE = False

_lock = threading.Lock()
_last = [0.0]


def get_json(url, tries=4):
    """SEC へ 1秒に8回まで（門の採取器と同じ User-Agent）。404 は None（無い＝0 と読まない）"""
    for i in range(tries):
        with _lock:
            w = _last[0] + 0.125 - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H.HDRS), timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** i)
        except Exception:
            time.sleep(2 ** i)
    return None


def fresh(fn, days):
    return os.path.exists(fn) and time.time() - os.path.getmtime(fn) < days * 86400


def jload(p, d=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


def dei_frame(tag, unit, period):
    os.makedirs(FCACHE, exist_ok=True)
    fn = os.path.join(FCACHE, f'dei_{tag}_{period}.json')
    if fresh(fn, 20) or (not FETCH and os.path.exists(fn)):
        return json.load(open(fn))
    if not FETCH:
        return []
    j = get_json(f'https://data.sec.gov/api/xbrl/frames/dei/{tag}/{unit}/{period}.json')
    data = [{'cik': e['cik'], 'name': e.get('entityName', ''), 'val': e['val'], 'end': e.get('end')}
            for e in (j or {}).get('data', [])]
    json.dump(data, open(fn, 'w'))
    return data


def ticker_maps():
    """SEC のティッカー表。cik→最初のティッカー（表は時価の大きい順なので、複数の株式の種類があれば先頭を採る）"""
    fn = os.path.join(FCACHE, 'company_tickers.json')
    j = None
    if fresh(fn, 7) or (not FETCH and os.path.exists(fn)):
        j = json.load(open(fn))
    elif FETCH:
        j = get_json('https://www.sec.gov/files/company_tickers.json')
        if j:
            os.makedirs(FCACHE, exist_ok=True)
            json.dump(j, open(fn, 'w'))
    c2t, t2c = {}, {}
    for v in (j or {}).values():
        c, t = int(v['cik_str']), str(v['ticker']).upper()
        c2t.setdefault(c, t)
        t2c.setdefault(t, c)
    return c2t, t2c


def ratio_check(tags):
    """どれか1本でも伸びていれば残す——同じタグで CY2023→CY2025 ≥1.20倍 / CY2022→CY2024 ≥1.20倍 / CY2024→CY2025 ≥1.10倍。
    frames は会計年度を暦年へ寄せるので、6月決算などはタグによって寄せ先の年がずれる（実測 STX: 同じ年度が
    タグにより CY2023 と CY2024 に割れる）。1組だけで外すと取りこぼすので、外すのは「比べられる組が全部伸びていない」ときだけ。
    比べられる組が1つも無ければ None（＝外さない。段2で会計年度の系列から測る）"""
    if not tags:
        return None
    seen = False
    for a, b, th in ((2023, 2025, STAGE1_MIN_RATIO), (2022, 2024, STAGE1_MIN_RATIO), (2024, 2025, 1.10)):
        for v in tags.values():
            if v.get(a) and v.get(b) and v[a] > 0:
                seen = True
                if v[b] / v[a] >= th:
                    return True
    return False if seen else None


def stage1(c2t, t2c):
    fl = {}
    for per in ('CY2024Q3I', 'CY2024Q4I', 'CY2025Q1I', 'CY2025Q2I', 'CY2025Q3I', 'CY2025Q4I', 'CY2026Q1I', 'CY2026Q2I'):
        for e in dei_frame('EntityPublicFloat', 'USD', per):
            c = e['cik']
            if c not in fl or (e.get('end') or '') > (fl[c].get('end') or ''):
                fl[c] = {'val': e['val'], 'end': e.get('end'), 'name': e.get('name')}
    rev = {}
    for tag in REV_TAGS:
        for y in range(2022, 2026):
            for e in us_frame(tag, f'CY{y}', fetch=FETCH):
                rev.setdefault(e['cik'], {}).setdefault(tag, {})[y] = e['val']
    cands, dropped = {}, {'浮動株30億ドル未満': 0, '売上が2年で1.20倍未満': 0, 'ティッカーなし': 0}
    for c, f in fl.items():
        if f['val'] < FLOAT_MIN:
            dropped['浮動株30億ドル未満'] += 1
            continue
        if c not in c2t:
            dropped['ティッカーなし'] += 1
            continue
        if ratio_check(rev.get(c)) is False:
            dropped['売上が2年で1.20倍未満'] += 1
            continue
        cands[c] = {'src': f"浮動株 {f['val'] / 1e9:.1f}十億$（{f.get('end')}）", 'float': f['val']}
    nf = 0
    for c, tags in rev.items():
        if c in fl or c not in c2t:
            continue
        r25 = max(max(v.get(2025) or 0, v.get(2024) or 0) for v in tags.values())
        if r25 >= REV_MIN_NOFLOAT and ratio_check(tags) is not False:
            cands[c] = {'src': f'浮動株の報告なし・売上 {r25 / 1e9:.1f}十億$（CY2024/2025 の大きいほう）', 'float': None}
            nf += 1
    ex = 0
    for t in EXTRA:
        c = t2c.get(t)
        if c and c not in cands:
            cands[c] = {'src': '外国株の名簿（IFRS は frames に無い）', 'float': None}
            ex += 1
    return cands, {'浮動株の報告社': len(fl), '外した': dropped, '浮動株なしで売上から入れた': nf,
                   '外国株の名簿から': ex, '段2へ': len(cands)}


def latest_dei_shares(facts):
    sh = (((facts.get('facts') or {}).get('dei') or {}).get('EntityCommonStockSharesOutstanding') or {}).get('units', {}).get('shares') or []
    if not sh:
        return None, None
    end = max(x.get('end') or '' for x in sh)
    # 同じ日に複数の値（株式の種類ごと）があれば足す——companyfacts は種類の内訳を持たないことが多い
    vals = {}
    for x in sh:
        if (x.get('end') or '') == end:
            vals[x.get('accn')] = vals.get(x.get('accn'), 0) + (x.get('val') or 0)
    return (max(vals.values()) if vals else None), end


def _days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def dil_alt(facts):
    """株数の伸び（年率%）を**最新の年次報告の比較の列**から測る——比較の列は株式分割を遡って調整済みなので、
    分割をまたいでも割れない（採取器の dilNet は分割の不連続で空欄になる＝NFLX・NOW）。
    基本の加重平均株数を先に、無ければ希薄化後。同じ提出（accn）の列だけを使う＝基準の違う二つを割らない。"""
    us = (facts.get('facts') or {}).get('us-gaap') or {}
    for tag in ('WeightedAverageNumberOfSharesOutstandingBasic', 'WeightedAverageNumberOfDilutedSharesOutstanding'):
        units = ((us.get(tag) or {}).get('units') or {}).get('shares') or []
        ann = [x for x in units if x.get('form') in ('10-K', '10-K/A', '20-F', '40-F') and x.get('start') and x.get('end')
               and 330 <= _days(x['start'], x['end']) <= 380 and (x.get('val') or 0) > 0]
        if not ann:
            continue
        last = max(ann, key=lambda x: (x.get('filed') or '', x.get('end') or ''))
        cols = sorted({x['end']: x['val'] for x in ann if x.get('accn') == last.get('accn')}.items())
        if len(cols) < 2:
            continue
        (e0, v0), (e1, v1) = cols[max(0, len(cols) - 3)], cols[-1]
        yrs = _days(e0, e1) / 365.25
        if yrs < 0.9:
            continue
        g = ((v1 / v0) ** (1 / yrs) - 1) * 100
        return round(g, 2), (f"{tag}（{last.get('form')} {last.get('filed')}・{e0} {v0 / 1e6:,.1f}百万株 → "
                             f"{e1} {v1 / 1e6:,.1f}百万株・{yrs:.1f}年の年率・比較の列は分割を遡って調整済み）")
    return None, '加重平均株数が年次報告に無い（IFRS の会社など）'


def rev_alt(facts):
    """売上の2年の伸び（年率%）を**最新の年次報告の比較の列**（同じ提出の3年分）から測る——会計基準の切替
    （IFRS→米国基準）や分社で採取器の系列が2年しか無い社の代わり（実測 CLS・SNDK）。ドル建ての米国基準のタグだけ。"""
    us = (facts.get('facts') or {}).get('us-gaap') or {}
    for tag in H.TAGS['rev']:
        units = ((us.get(tag) or {}).get('units') or {}).get('USD') or []
        ann = [x for x in units if x.get('form') in ('10-K', '10-K/A', '20-F', '40-F') and x.get('start') and x.get('end')
               and 330 <= _days(x['start'], x['end']) <= 380 and (x.get('val') or 0) > 0]
        if not ann:
            continue
        last = max(ann, key=lambda x: (x.get('filed') or '', x.get('end') or ''))
        cols = sorted({x['end']: x['val'] for x in ann if x.get('accn') == last.get('accn')}.items())
        if len(cols) < 3:
            continue
        (e0, v0), (e1, v1) = cols[-3], cols[-1]
        yrs = _days(e0, e1) / 365.25
        if yrs < 1.8:
            continue
        return round(((v1 / v0) ** (1 / yrs) - 1) * 100, 1), (f"{tag}（{last.get('form')} {last.get('filed')}・{e0} {v0 / 1e9:,.2f}十億$ → "
                                                              f"{e1} {v1 / 1e9:,.2f}十億$・同じ提出の比較の列）"), int(e1[:4])
    return None, '年次報告の比較の列が3年そろわない', None


def stage2_one(c):
    os.makedirs(CACHE, exist_ok=True)
    fn = os.path.join(CACHE, f'{c}.json')
    if os.path.exists(fn) and (not FETCH or (fresh(fn, 20) and not REFRESH)):
        old = json.load(open(fn))
        # 2026-10-05 に足した欄（加重平均株数の伸び）を持たない古いキャッシュは取り直す
        need_dil = 'dil_alt' not in old and old.get('dilNet') is None
        need_g2 = 'g2_alt' not in old and old.get('g2') is None and old.get('rev0')
        if not (need_dil or need_g2) or not FETCH or old.get('err'):
            return old
    if not FETCH:
        return {'cik': c, 'err': 'キャッシュ無し（--no-fetch）'}
    rec = {'cik': c, 'asof': TODAY}
    facts = get_json(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{c:010d}.json')
    if not facts:
        rec['err'] = 'companyfacts が無い'
        json.dump(rec, open(fn, 'w'), ensure_ascii=False)
        return rec
    rec['name'] = facts.get('entityName')
    try:
        ev = H.build_numbers(facts)
    except Exception as e:
        ev = {}
        rec['err'] = f'build_numbers 例外: {type(e).__name__}: {str(e)[:120]}'
    for k in ('roic', 'roicg', 'nde', 'dilNet', 'cagr5', 'eqSign', 'conv'):
        rec[k] = ev.get(k)
    rec['unit'] = ev.get('_unit')
    rec['notes'] = [str(x)[:160] for x in (ev.get('_note') or []) if any(w in str(x) for w in ('roic', 'nde', 'dilNet', 'cagr', 'ROIC'))][:4]
    try:
        rs, unit = H.series(facts, H.TAGS['rev'])
    except Exception:
        rs, unit = {}, None
    if rs:
        y0 = max(rs)
        rec['rev_y0'], rec['rev0'], rec['rev_unit'] = y0, rs[y0], unit
        if rs.get(y0 - 1):
            rec['g1'] = round((rs[y0] / rs[y0 - 1] - 1) * 100, 1)
        if rs.get(y0 - 2) and rs[y0 - 2] > 0 and rs[y0] > 0:
            rec['g2'] = round(((rs[y0] / rs[y0 - 2]) ** 0.5 - 1) * 100, 1)
            rec['rev_m2'] = rs[y0 - 2]
    sh, end = latest_dei_shares(facts)
    rec['shares'], rec['shares_end'] = sh, end
    rec['dil_alt'], rec['dil_alt_src'] = dil_alt(facts)
    if rec.get('g2') is None:
        rec['g2_alt'], rec['g2_alt_src'], rec['g2_alt_y'] = rev_alt(facts)
    json.dump(rec, open(fn, 'w'), ensure_ascii=False)
    return rec


def etf_exposure():
    """目標の配分で、ETF経由で総資産の何%を各社に持つか（{ticker: %}）"""
    prof = (jload('out/etf_profiles.json', {}) or {}).get('etfs') or {}
    tgt = (jload('portfolio.json', {}) or {}).get('target') or {}
    w = tgt.get('ami_weights') or {}
    same = tgt.get('ami_same_index') or {}
    out, used = {}, []
    for etf, pct in w.items():
        if not pct:
            continue
        src = etf if (prof.get(etf) or {}).get('h') else next((s for s in (same.get(etf) or []) if (prof.get(s) or {}).get('h')), None)
        if not src:
            used.append(f'{etf} {pct}%: 中身が無い（数えていない）')
            continue
        used.append(f'{etf} {pct}%（中身は {src}）')
        for t, wt in prof[src]['h']:
            out[t.upper()] = out.get(t.upper(), 0) + pct * wt
    return out, used, (jload('out/etf_profiles.json', {}) or {}).get('asof')


def fetch_estimates_av(tickers, est):
    """AV_KEY があれば足りない社の予想を取る（無料枠 25回/日・1秒に1回）。取れた分だけ est に足す。
    20日以内に取った社は取り直さない。1日の上限の返事が来たらそこで止める（残りは次の日）"""
    key = os.environ.get('AV_KEY') or ''
    if not key or not FETCH:
        return 0
    n = 0
    for t in tickers:
        e = est.get(t) or {}
        if e.get('asof') and _days(e['asof'], TODAY) < 20:
            continue
        if n >= 24:
            break
        url = f'https://www.alphavantage.co/query?function=EARNINGS_ESTIMATES&symbol={t}&apikey={key}'
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'ccf-gate'}), timeout=60) as r:
                j = json.loads(r.read())
        except Exception:
            j = None
        time.sleep(1.2)
        n += 1
        if isinstance(j, dict) and not isinstance(j.get('estimates'), list):
            msg = str(j.get('Information') or j.get('Note') or '')
            if 'per day' in msg or 'daily' in msg:
                print(f'  Alpha Vantage の1日の上限に達した（{t} の手前まで）')
                break
            continue
        if isinstance((j or {}).get('estimates'), list):
            est[t] = summarize_estimates(j)
    return n


def fetch_estimates_yahoo(tickers, est):
    """Yahoo Finance の earningsTrend から売上の予想（0y・+1y）を取る（Alpha Vantage の無料枠 25回/日で取り切れない社の代わり）。
    Cookie と crumb は night/fetch_dashboard._yahoo_ctx をそのまま使う（二重実装しない）。1秒に1回。
    値は est[t]['yahoo'] に入れる——Alpha Vantage の値がある社では物差しに使わず、突き合わせ（xcheck）にだけ使う。"""
    if not FETCH or not tickers:
        return 0
    from fetch_dashboard import _yahoo_ctx
    op, crumb = _yahoo_ctx()
    if not crumb:
        print('  Yahoo: crumb が取れない＝予想を取れない（429 のことが多い・時間をおいて）')
        return 0
    n = 0
    for t in tickers:
        y = (est.get(t) or {}).get('yahoo') or {}
        if y.get('asof') and _days(y['asof'], TODAY) < 20:
            continue
        url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{t}?modules=earningsTrend&crumb={crumb}'
        try:
            with op.open(url, timeout=20) as r:
                j = json.loads(r.read().decode('utf-8', 'ignore'))
        except Exception as e:
            print(f'  Yahoo {t}: {type(e).__name__} {str(e)[:60]}')
            time.sleep(1.0)
            continue
        time.sleep(1.0)
        n += 1
        res = ((j.get('quoteSummary') or {}).get('result') or [None])[0] or {}
        fy = []
        for x in (res.get('earningsTrend') or {}).get('trend') or []:
            if x.get('period') not in ('0y', '+1y'):
                continue
            rv = x.get('revenueEstimate') or {}
            avg, na = (rv.get('avg') or {}).get('raw'), (rv.get('numberOfAnalysts') or {}).get('raw')
            if avg and x.get('endDate'):
                fy.append({'period': x['period'], 'date': x['endDate'], 'rev': avg, 'n': na,
                           'ccy': rv.get('revenueCurrency') or (x.get('earningsEstimate') or {}).get('earningsCurrency')})
        est.setdefault(t, {})['yahoo'] = {'asof': TODAY, 'src': 'Yahoo Finance quoteSummary earningsTrend（0y/+1y）', 'fy': fy}
    return n


def summarize_estimates(j):
    """Alpha Vantage の EARNINGS_ESTIMATES を、年度の売上と人数だけに縮める（キャッシュに残す形）"""
    fy = []
    for x in j.get('estimates') or []:
        if x.get('horizon') != 'fiscal year':
            continue
        fy.append({'date': x.get('date'), 'rev': x.get('revenue_estimate_average'),
                   'n': x.get('revenue_estimate_analyst_count'), 'eps': x.get('eps_estimate_average'),
                   'up30': x.get('eps_estimate_revision_up_trailing_30_days'),
                   'down30': x.get('eps_estimate_revision_down_trailing_30_days')})
    return {'asof': TODAY, 'src': 'Alpha Vantage EARNINGS_ESTIMATES', 'fy': fy}


def fwd_growth(e):
    """来期の売上の伸び（%）。Alpha Vantage の要約（出口条件と同じ物差し・watch_exceptions と同じ関数）を先に使い、
    無ければ Yahoo の earningsTrend（0y＝今の会計年度・+1y＝次の年度）。どちらから来たかを info に名乗る"""
    if e and e.get('fy'):
        j = {'estimates': [{'horizon': 'fiscal year', 'date': x['date'], 'revenue_estimate_average': x.get('rev'),
                            'revenue_estimate_analyst_count': x.get('n')} for x in e['fy'] if x.get('date')]}
        g, info = rev_growth_from_estimates(j, today=e.get('asof') or TODAY)
        if g is not None:
            return g, info
    y = (e or {}).get('yahoo') or {}
    f0 = next((x for x in y.get('fy') or [] if x.get('period') == '0y'), None)
    f1 = next((x for x in y.get('fy') or [] if x.get('period') == '+1y'), None)
    if f0 and f1 and (f0.get('rev') or 0) > 0 and (f1.get('rev') or 0) > 0:
        cur = f" {f0['ccy']}" if f0.get('ccy') and f0.get('ccy') != 'USD' else '$'
        n = f"{f1['n']:.0f}名" if isinstance(f1.get('n'), (int, float)) else '人数不明'
        return ((f1['rev'] / f0['rev'] - 1) * 100,
                f"{f0['date']} {f0['rev'] / 1e9:.2f}十億{cur} → {f1['date']} {f1['rev'] / 1e9:.2f}十億{cur}（{n}・Yahoo {y.get('asof')}）")
    return None, '予想なし'


def mcap_of(t, rec, mc, dash):
    m = (mc or {}).get(t)
    if m and m.get('mcap'):
        return m['mcap'], f"{m.get('src', '')} {m.get('asof', '')}".strip()
    q = ((dash or {}).get('quotes') or {}).get(t)
    if q and q.get('px') and rec.get('shares') and (q.get('ccy') or 'USD') == 'USD':
        return q['px'] * rec['shares'], f"盤の株価 ${q['px']} × 表紙の株数（{rec.get('shares_end')}）"
    return None, '時価総額が無い'


def main():
    c2t, t2c = ticker_maps()
    if not c2t:
        print('✗ SEC のティッカー表が読めない（--no-fetch でキャッシュも無い）')
        return 1
    cands, s1 = stage1(c2t, t2c)
    if not QUIET:
        print(f"■ 段1（SEC frames）: {json.dumps(s1, ensure_ascii=False)}")
    ciks = sorted(cands)
    with ThreadPoolExecutor(4) as ex:
        recs = list(ex.map(stage2_one, ciks))
    est = jload(EST, {}) or {}
    mc = jload(MCAP, {}) or {}
    dash = jload('out/dashboard.json', {}) or {}
    etf, etf_used, etf_asof = etf_exposure()
    gx = {str(it.get('t') or '').upper(): it.get('kind') for it in (jload('gate_exceptions.json', {}) or {}).get('items', [])}
    packs = {}
    for t in set(c2t.values()):
        pk = jload(f'out/{t}_gate_pack.json')
        if pk:
            packs[t] = pk.get('data') or pk
    sicm = jload('out/sic_by_cik.json', {}) or {}

    rows = []
    for c, rec in zip(ciks, recs):
        t = c2t.get(c) or '?'
        r = {'t': t, 'cik': c, 'name': rec.get('name'), 'src': cands[c]['src']}
        # 採取器が測れなかった欄は、門の台帳のパック（審査官が原本で確定した値）へ倒す——どこから来たかを書く
        rec = dict(rec)
        pk = packs.get(t) or {}
        r['fill'] = {}
        for k in ('roic', 'nde', 'dilNet'):
            if rec.get(k) is None and isinstance(pk.get(k), (int, float)):
                rec[k] = pk[k]
                r['fill'][k] = f"パック（審査で確定・{((pk.get('_meta') or {}).get('reportDate')) or '期不明'}）"
        if rec.get('g2') is None and isinstance(rec.get('g2_alt'), (int, float)):
            rec['g2'] = rec['g2_alt']
            rec['rev_y0'] = rec.get('g2_alt_y') or rec.get('rev_y0')
            r['fill']['g2'] = '売上 ' + str(rec.get('g2_alt_src') or '')
        if rec.get('dilNet') is None and isinstance(rec.get('dil_alt'), (int, float)):
            rec['dilNet'] = rec['dil_alt']
            r['fill']['dilNet'] = '加重平均株数 ' + str(rec.get('dil_alt_src') or '')
        if not r['fill']:
            del r['fill']
        sic = str(sicm.get(str(c)) or '')
        if sic.isdigit() and 6000 <= int(sic) <= 6999:
            r['fin'] = f'金融（SIC {sic}）＝ROIC・nde の物差しが合わない'
        for k in ('g2', 'g1', 'rev_y0', 'roic', 'roicg', 'nde', 'dilNet', 'eqSign', 'err'):
            if rec.get(k) not in (None, [], ''):
                r[k] = rec[k]
        if rec.get('rev0'):
            r['rev0'] = round(rec['rev0'] / 1e9, 2)
            r['rev_unit'] = rec.get('rev_unit')
        mcap, msrc = mcap_of(t, rec, mc, dash)
        r['mcap'] = round(mcap / 1e9, 1) if mcap else None
        r['mcap_src'] = msrc
        r['etf_pct'] = round(etf.get(t, 0.0), 2)
        g, ginfo = fwd_growth(est.get(t))
        r['fwd'] = round(g, 1) if isinstance(g, (int, float)) else None
        r['fwd_src'] = ginfo
        if gx.get(t):
            r['now'] = gx[t]
        # 条件ごとの合否（None＝測れない。測れないことを「満たさない」と読まない）
        y_ok = rec.get('rev_y0') is not None and rec['rev_y0'] >= int(TODAY[:4]) - 1
        chk = {
            '②直近2年の売上 ≥15%/年': (None if rec.get('g2') is None or not y_ok else rec['g2'] >= G_2Y),
            '③ROIC ≥15%': (None if rec.get('roic') is None else rec['roic'] >= ROIC_MIN),
            '③純有利子負債/EBITDA <2': (None if rec.get('nde') is None else rec['nde'] < NDE_MAX),
            '③株数を増やしていない（≤1%）': (None if rec.get('dilNet') is None else rec['dilNet'] <= DIL_MAX),
            '③時価総額 ≥200億ドル': (None if not mcap else mcap >= MCAP_MIN),
            '④ETF経由 <1%': r['etf_pct'] < ETF_MAX,
            '①来期の売上の伸び ≥20%': (None if r['fwd'] is None else r['fwd'] >= G_FWD),
        }
        if rec.get('g2') is not None and not y_ok:
            r['g2_stale'] = f"売上の系列が {rec.get('rev_y0')} 年で止まっている（タグの改称の疑い）"
        r['fail'] = [k for k, v in chk.items() if v is False]
        r['unk'] = [k for k, v in chk.items() if v is None]
        if r.get('mcap_src', '').startswith('FMP profile-symbol'):
            r['mcap_src'] = 'FMP ' + r['mcap_src'].split()[-1]
        rows.append(r)

    # 並べ方: (a) ②③④を全部満たし①も満たす → ①の大きい順 (b) ②③④は満たすが①が足りない/無い (c) ②③④の1つだけ外れ (d) その他
    def k234(r):
        return [k for k in r['fail'] if not k.startswith('①')]
    def u234(r):
        return [k for k in r['unk'] if not k.startswith('①')]
    A = sorted([r for r in rows if not k234(r) and not u234(r) and r['fwd'] is not None and r['fwd'] >= G_FWD], key=lambda r: -r['fwd'])
    B = sorted([r for r in rows if not k234(r) and not u234(r) and r not in A], key=lambda r: -(r['fwd'] if r['fwd'] is not None else -999))
    # C: ②（成長している）は満たし、③④の1つだけ外れる・測れない社（②だけ外れる社＝成長していない社は成長期待枠の候補ではないので入れない）
    g2ok = lambda r: r.get('g2') is not None and r['g2'] >= G_2Y and 'g2_stale' not in r
    C = sorted([r for r in rows if g2ok(r) and len(k234(r)) + len(u234(r)) == 1 and r not in A and r not in B],
               key=lambda r: (-(r['fwd'] if r['fwd'] is not None else -999), -(r.get('g2') or -999)))
    gate2 = [r for r in rows if r.get('g2') is not None and r['g2'] >= G_2Y]
    # D（参考）: ②を満たし時価総額200億ドル以上だが、③④の2つ以上で外れる大型の高成長株——規則の外。幅広く見るためだけに並べる
    D = sorted([r for r in rows if r.get('g2') is not None and r['g2'] >= G_2Y and 'g2_stale' not in r
                and r['mcap'] and r['mcap'] * 1e9 >= MCAP_MIN and len(k234(r)) + len(u234(r)) >= 2],
               key=lambda r: -(r.get('g2') or 0))
    # 予想を取りに行く順: A/B の候補（②③④を満たす）→ C（1つだけ外れる）——どちらも時価総額200億ドル以上で予想がまだ無い社
    av_next = [r['t'] for r in B if r['fwd'] is None and r['mcap']] + \
              [r['t'] for r in C if r['fwd'] is None and r['mcap'] and r['mcap'] * 1e9 >= MCAP_MIN
               and (r.get('g2') or 0) >= G_2Y and 'g2_stale' not in r]
    # --yahoo: 予想の無い候補（av_next）と参考の大型（D）を Yahoo で取り、Alpha Vantage を持つ社も突き合わせ用に取る（1回だけ）
    global _Y_DONE
    if not _Y_DONE and FETCH and '--yahoo' in FLAGS:
        _Y_DONE = True
        want = av_next + [r['t'] for r in D if r['fwd'] is None] + [t for t in est if (est.get(t) or {}).get('fy')]
        n = fetch_estimates_yahoo(list(dict.fromkeys(want)), est)
        if n:
            json.dump(est, open(EST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print(f'■ Yahoo へ {n}回問い合わせた → 並べ直す')
            return main()
    # AV_KEY があれば、予想の無い社を順に取りに行き（無料枠 25回/日）、取れたら並べ直す（1回だけ）
    global _AV_DONE
    if not _AV_DONE and FETCH and os.environ.get('AV_KEY') and av_next:
        _AV_DONE = True
        n = fetch_estimates_av(av_next, est)
        if n:
            json.dump(est, open(EST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            print(f'■ Alpha Vantage へ {n}回問い合わせた → 並べ直す')
            return main()
    xcheck = []
    for t, e in sorted(est.items()):
        if not (isinstance(e, dict) and e.get('fy') and e.get('yahoo')):
            continue
        ga, _ = fwd_growth({'fy': e['fy'], 'asof': e.get('asof')})
        gy, _ = fwd_growth({'yahoo': e['yahoo']})
        if ga is not None and gy is not None:
            xcheck.append({'t': t, 'av': round(ga, 1), 'yahoo': round(gy, 1), 'diff': round(gy - ga, 1)})
    out = {
        'asof': TODAY,
        'tool': 'night/growth_rank.py',
        'note': ('成長期待枠の候補（門の外・表示だけ・判定に不使用）。線は gate_exceptions.json の VRT/ANET の why と同じ'
                 '（①来期の売上の伸び≥20%・②直近2年≥15%/年・③ROIC≥15%・nde<2・dilNet≤1%・時価総額≥200億ドル・④ETF経由<1%）。'
                 '測れない数字は「満たさない」と読まず unk に名指し。⚠予想の伸びがリターンを上乗せする証拠は無い'),
        'stage1': s1,
        'xcheck': xcheck,
        'etf': {'asof': etf_asof, 'used': etf_used},
        'counts': {'段2で測った社': len(rows), '②を満たす': len(gate2), 'A 全条件': len(A), 'B ②③④は満たす（①が足りない・予想なし）': len(B),
                   'C ②③④の1つだけ外れる・測れない': len(C), 'D 参考（大型の高成長・③④の2つ以上で外れる）': len(D)},
        'A': [r['t'] for r in A], 'B': [r['t'] for r in B], 'C': [r['t'] for r in C], 'D': [r['t'] for r in D], 'av_next': av_next,
        # 一本の並び（A→B→C→D の順・各段の中は来期の売上の伸びの予想の大きい順、予想が無い社は直近2年の伸びの順で後ろ）
        'ranking': [dict(rank=i + 1, tier=tier, t=r['t'], name=r.get('name'), fwd=r['fwd'], g2=r.get('g2'), roic=r.get('roic'),
                         nde=r.get('nde'), dilNet=r.get('dilNet'), mcap=r['mcap'], etf_pct=r['etf_pct'],
                         out=k234(r), unk=u234(r), now=r.get('now'), fin=r.get('fin'))
                    for i, (tier, r) in enumerate([('A', x) for x in A] + [('B', x) for x in B] + [('C', x) for x in C] + [('D', x) for x in D])],
        # rows は②（直近2年の売上 ≥15%/年）を満たす社だけ——全社の測定値は out/_growth_cache/（gitignore）にある
        'rows': sorted([r for r in rows if g2ok(r)], key=lambda r: (-(r.get('g2') or -999))),
    }
    # 条件の長い名前は凡例へ（JSON を軽くする）
    SHORT = {'②直近2年の売上 ≥15%/年': '②', '③ROIC ≥15%': '③ROIC', '③純有利子負債/EBITDA <2': '③nde',
             '③株数を増やしていない（≤1%）': '③株数', '③時価総額 ≥200億ドル': '③時価', '④ETF経由 <1%': '④', '①来期の売上の伸び ≥20%': '①'}
    out['legend'] = {v: k for k, v in SHORT.items()}
    for coll in (out['rows'], out['ranking']):
        for x in coll:
            for k in ('fail', 'unk', 'out'):
                if k in x:
                    x[k] = [SHORT.get(y, y) for y in x[k]]
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if '--need' in FLAGS:
        # 予想・時価総額がまだ無い社のうち、②③（時価総額以外）④を満たす or 1つだけ外れる社——取りに行く順
        def score(r):
            k = [x for x in k234(r) + u234(r) if not x.startswith('③時価総額')]
            return (len(k), -(r.get('g2') or 0))
        need = sorted([r for r in rows if (r['fwd'] is None or r['mcap'] is None)
                       and len([x for x in k234(r) + u234(r) if not x.startswith('③時価総額')]) <= 1
                       and (r.get('g2') or 0) >= G_2Y], key=score)
        json.dump([{'t': r['t'], 'name': r.get('name'), 'g2': r.get('g2'), 'need_fwd': r['fwd'] is None, 'need_mcap': r['mcap'] is None,
                    'miss': [x for x in k234(r) + u234(r) if not x.startswith('③時価総額')]} for r in need],
                  open(NEED, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'→ {NEED}（{len(need)}社）')
    if not QUIET:
        def line(r):
            return (f"{r['t']:<6} {str(r.get('name') or '')[:26]:<26} 予想{('%+.1f%%' % r['fwd']) if r['fwd'] is not None else '  —  ':>8} "
                    f"2年{('%.1f%%' % r['g2']) if r.get('g2') is not None else '—':>7} ROIC{r.get('roic', '—')!s:>6} nde{r.get('nde', '—')!s:>6} "
                    f"株数{r.get('dilNet', '—')!s:>6} 時価{('%.0f' % r['mcap']) if r['mcap'] else '—':>6} ETF{r['etf_pct']:>5.2f}"
                    + (f"  外れ: {'・'.join(k234(r))}" if k234(r) else '') + (f"  測れない: {'・'.join(u234(r))}" if u234(r) else '')
                    + (f"  [今: {r['now']}]" if r.get('now') else ''))
        print(f"\n■ {json.dumps(out['counts'], ensure_ascii=False)}")
        print('\n■ A 全条件（①の大きい順）'); [print('  ' + line(r)) for r in A]
        print('\n■ B ②③④は満たす（①が20%未満・予想なし）'); [print('  ' + line(r)) for r in B[:40]]
        print('\n■ C ②③④の1つだけ外れる・測れない（上位40）'); [print('  ' + line(r)) for r in C[:40]]
        print('\n■ D 参考: 大型の高成長だが③④の2つ以上で外れる'); [print('  ' + line(r)) for r in D[:60]]
        print(f"\n■ 予想を取りに行く順（{len(av_next)}社）: {' '.join(av_next)}")
        print(f'\n→ {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
