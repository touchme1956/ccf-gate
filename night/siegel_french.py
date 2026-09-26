#!/usr/bin/env python3
"""night/siegel_french.py — シーゲルの主張（高配当・低PER）を約100年の米国全株で見る（読むだけ）

「2013→2026 で再現しなかったのは最近の相場のせいか」を測る。データは Kenneth French Data Library の
Portfolios_Formed_on_D-P / E-P（CRSP 全上場・倒産した会社も含む＝生存バイアスが無い）。
差 = 高30% − 低30% の年率。時価加重と等加重。出力 out/siegel_french.json
"""
import io, json, os, urllib.request, zipfile, datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/{}_CSV.zip'

def load(name, block):
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(URL.format(name), timeout=60).read()))
    L = z.read(z.namelist()[0]).decode('latin-1').split('\n')
    i = [k for k, l in enumerate(L) if l.strip() == block][0]
    hdr = [h.strip() for h in L[i + 1].split(',')]; d = {}
    for l in L[i + 2:]:
        p = [x.strip() for x in l.split(',')]
        if len(p) < 2 or not (p[0].isdigit() and len(p[0]) == 6): break
        d[int(p[0])] = {h: float(v) for h, v in zip(hdr[1:], p[1:])}
    return d

def main():
    out = {'generated': datetime.date.today().isoformat(), 'source': 'Kenneth R. French Data Library（CRSP）', 'results': {}}
    for name, lab in (('Portfolios_Formed_on_D-P', '配当利回り'), ('Portfolios_Formed_on_E-P', '益回り（低PER）')):
        for blk, wl in (('Value Weight Returns -- Monthly', '時価加重'), ('Equal Weight Returns -- Monthly', '等加重')):
            d = load(name, blk); ms = sorted(d)
            def ann(a, b, c):
                g, n = 1.0, 0
                for m in ms:
                    if a <= m <= b: g *= 1 + d[m][c] / 100; n += 1
                return g ** (12 / n) - 1
            sp = lambda a, b: round((ann(a, b, 'Hi 30') - ann(a, b, 'Lo 30')) * 100, 2)
            per = {nm: sp(a, b) for a, b, nm in ((ms[0], ms[-1], f'全期間 {ms[0]}→{ms[-1]}'), (ms[0], 196212, '〜1962'),
                   (196301, 198912, '1963-1989'), (199001, 200612, '1990-2006'), (200701, ms[-1], '2007→'),
                   (201307, ms[-1], '2013-07→'), (201807, ms[-1], '2018-07→'))}
            roll = {}
            for Y in (10, 20):
                r = []
                for y0 in range(ms[0] // 100 + 1, 2100):
                    a, b = y0 * 100 + 7, (y0 + Y) * 100 + 6
                    if b > ms[-1]: break
                    r.append((y0, sp(a, b)))
                roll[f'{Y}年'] = {'窓': len(r), '高が勝った': sum(s > 0 for _, s in r), '負けた起点': {y: s for y, s in r if s < 0}}
            out['results'][f'{lab}・{wl}'] = {'期間別': per, '転がる窓（7月起点）': roll}
            print(lab, wl, per, {k: f"{v['高が勝った']}/{v['窓']}" for k, v in roll.items()})
    json.dump(out, open(os.path.join(BASE, 'out', 'siegel_french.json'), 'w'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    main()
