#!/usr/bin/env python3
"""night/angles_13f.py — 事前登録 out/angles4_prereg.json の B2（機関投資家の注目度）の採取

SEC Form 13F Data Sets（_angles_data/{Y}q1_form13f.zip・gitignore）の 13F-HR（前年末の保有）から、
CUSIP の先頭6桁（発行体）ごとに『保有している機関の数』を数え、発行体名を956社の会社名へ対応させる。
名前の出所は Form 4 データセットの ISSUERNAME（2012-2018 の歴代社名・CIK つき）と SEC の company_tickers.json。
★対応は『一意に決まったときだけ』。曖昧なものは捨てる（欠測は 0 と読まない）。

使い方: python3 night/angles_13f.py   出力: out/angles_13f.json
"""
import csv, io, json, os, re, sys, zipfile, datetime as dt, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(BASE, '_angles_data')
csv.field_size_limit(1 << 30)
STOP = {'INC', 'CORP', 'CORPORATION', 'CO', 'COMPANY', 'LTD', 'LIMITED', 'PLC', 'THE', 'NEW', 'DEL', 'COM', 'CL', 'A', 'B',
        'HLDGS', 'HOLDINGS', 'HLDG', 'HOLDING', 'GROUP', 'GRP', 'LP', 'LLC', 'NV', 'SA', 'AG', 'SE', 'INCORPORATED', 'DE', 'MD', 'NY'}

def tsv(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, 'utf-8', errors='ignore'), delimiter='\t', quoting=csv.QUOTE_NONE)

def toks(s):
    s = re.sub(r'&', ' AND ', (s or '').upper()); s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return [t for t in s.split() if t not in STOP]

def match(a, b):
    """a=13Fの発行体名（略称が多い）の各語が、b（会社名）の語の頭に順に一致するか。先頭語は4文字以上一致を要求。"""
    if not a or not b: return False
    if not (b[0] == a[0] or (len(a[0]) >= 4 and b[0].startswith(a[0]))): return False
    j = 1
    for t in a[1:]:
        while j < len(b) and not b[j].startswith(t[:max(3, min(len(t), 4))]): j += 1
        if j >= len(b): return False
        j += 1
    return True

def names_by_cik():
    nm = {}
    for q in ('2012q3', '2013q2', '2017q3', '2018q2'):
        z = zipfile.ZipFile(os.path.join(D, f'{q}_form345.zip'))
        for r in tsv(z, 'SUBMISSION.tsv'):
            nm.setdefault(int(r['ISSUERCIK']), set()).add(r['ISSUERNAME'])
    sys.argv = ['x']; sys.path.insert(0, BASE); import hachimon_fetch as h
    j = json.loads(urllib.request.urlopen(urllib.request.Request('https://www.sec.gov/files/company_tickers.json', headers=h.HDRS), timeout=60).read())
    for v in j.values(): nm.setdefault(int(v['cik_str']), set()).add(v['title'])
    return nm

def main():
    tick = [r['ticker'] for r in json.load(open(os.path.join(BASE, 'out', 'retro_features2_2018.json')))['rows']]
    cik = json.load(open(os.path.join(BASE, 'out', '_cik_tickers.json')))
    nm = names_by_cik()
    cands = {t: [toks(n) for n in nm.get(int(cik[t]), [])] for t in tick if t in cik}
    out = {}
    for Y in (2016, 2017, 2018):
        z = zipfile.ZipFile(os.path.join(D, f'{Y}q1_form13f.zip'))
        ok = {r['ACCESSION_NUMBER']: r['CIK'] for r in tsv(z, 'SUBMISSION.tsv')
              if r['SUBMISSIONTYPE'] == '13F-HR' and r['PERIODOFREPORT'] == f'31-DEC-{Y - 1}'}
        holders, names = {}, {}
        for r in tsv(z, 'INFOTABLE.tsv'):
            a = r['ACCESSION_NUMBER']
            if a not in ok or r['PUTCALL'] or r['SSHPRNAMTTYPE'] != 'SH': continue
            c6 = (r['CUSIP'] or '')[:6].upper()
            if len(c6) < 6: continue
            holders.setdefault(c6, set()).add(ok[a])
            names.setdefault(c6, {}); names[c6][r['NAMEOFISSUER']] = names[c6].get(r['NAMEOFISSUER'], 0) + 1
        # 発行体名（最頻）→ 956社への一意の対応
        t2c6, amb = {}, 0
        for c6, ns in names.items():
            if len(holders[c6]) < 3: continue
            a = toks(max(ns, key=ns.get))
            hit = [t for t, bs in cands.items() if any(match(a, b) for b in bs)]
            if len(hit) > 1:  # 別の会社どうしが当たった → 正規化した社名の完全一致が1社だけならそれ（例: APPLE INC と Apple Hospitality）
                ex = [t for t in hit if any(a == bb for bb in cands[t])]
                if len(ex) == 1: hit = ex
            if len(hit) == 1: t2c6.setdefault(hit[0], []).append(c6)
            elif len(hit) > 1: amb += 1
        rows = {}
        for t, cs in t2c6.items():
            # 同じ会社に複数のCUSIPが当たる（優先株・社債連動ETN・旧CUSIP）→ 保有機関の最も多いもの＝普通株を採る。
            # ⚠ これは『同じ会社の中での選択』。別の会社どうしの曖昧（hit が2社以上）は上で捨てている
            c = max(cs, key=lambda x: len(holders[x]))
            rows[t] = dict(holders=len(holders[c]), cusip6=c, name=max(names[c], key=names[c].get), n_cusip=len(cs))
        out[str(Y)] = rows
        print(Y, '13F-HR', len(ok), '件／発行体', len(names), '／956社へ一意に対応', len(rows), '（曖昧で捨てた', amb, '・同じ社に複数CUSIP', sum(len(c) > 1 for c in t2c6.values()), '）')
    json.dump(dict(generated=dt.date.today().isoformat(), tool='night/angles_13f.py', prereg='out/angles4_prereg.json', **out),
              open(os.path.join(BASE, 'out', 'angles_13f.json'), 'w'), ensure_ascii=False)

if __name__ == '__main__':
    main()
