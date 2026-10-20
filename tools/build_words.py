#!/usr/bin/env python3
"""Сборка файлов переводов для GitHub из исходных файлов сур (surah_XXX.dart).

Запуск:
    python3 tools/build_words.py /путь/к/Quran_114  [--app /путь/к/flutter-проекту]

Что делает:
  • words/<язык>/NNN.json  — краткий и подробный перевод слов (ru, en, tr, kk, ky);
  • words/ar/NNN.json      — арабское толкование автора (fullAr);
  • manifest.json          — у изменившихся пакетов (words, ui, privacy, terms)
                             повышает версию "v",
                             чтобы приложения скачали обновление;
  • --app: заодно обновляет assets/quran/quran.json (арабский Коран в приложении).
Названия сур для языков интерфейса берутся из nameLoc/meaningLoc и
записываются в ui/<язык>.json (поле "surahs").
"""
import bisect, glob, hashlib, json, os, re, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGS = ['ru', 'en', 'tr', 'kk', 'ky']
S = r"'((?:[^'\\]|\\.)*)'"
AYAH = re.compile(r'// ---- Аят (\d+) ----')
WE = re.compile(r"WordEntry\(\s*" + S + r",\s*" + S + r",\s*" + S + r",\s*\{(.*?)\},\s*\{(.*?)\},\s*\)", re.S)
KV = re.compile(r"'(ru|en|tr|kk|ky)':\s*" + S)

def unesc(s): return s.replace("\\'", "'").replace('\\$', '$').replace('\\\\', '\\')

def parse(path):
    txt = open(path, encoding='utf-8').read()
    ay = [(m.start(), int(m.group(1))) for m in AYAH.finditer(txt)]
    pos = [a[0] for a in ay]; out = []
    for m in WE.finditer(txt):
        i = bisect.bisect(pos, m.start()) - 1
        out.append(dict(ayah=ay[i][1], ar=unesc(m.group(1)), tr=unesc(m.group(2)), fullAr=unesc(m.group(3)),
                        short={k: unesc(v) for k, v in KV.findall(m.group(4))},
                        full={k: unesc(v) for k, v in KV.findall(m.group(5))}))
    return txt, out

def locmap(txt, field):
    m = re.search(field + r":\s*\{(.*?)\n\s*\}", txt, re.S); d = {}
    if m:
        for k, v in re.findall(r"'(\w+)':\s*" + S, m.group(1)): d[k] = unesc(v)
    return d

def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    old = open(path, 'rb').read() if os.path.exists(path) else None
    if old != data:
        open(path, 'wb').write(data)
    return hashlib.sha1(data).hexdigest()

def main():
    if len(sys.argv) < 2: print(__doc__); sys.exit(1)
    src = sys.argv[1]
    app = sys.argv[sys.argv.index('--app') + 1] if '--app' in sys.argv else None
    hashes = {p: hashlib.sha1() for p in LANGS + ['ar']}
    core = []; names = {l: {} for l in LANGS + ['ar']}
    for s in range(1, 115):
        txt, es = parse(f'{src}/surah_{s:03d}.dart')
        n = int(re.search(r'ayahCount:\s*(\d+)', txt).group(1))
        ay = [[] for _ in range(n)]
        for e in es: ay[e['ayah'] - 1].append(e)
        nl, ml = locmap(txt, 'nameLoc'), locmap(txt, 'meaningLoc')
        for l in names: names[l][str(s)] = [nl.get(l) or nl.get('ru'), ml.get(l) or ml.get('ru')]
        b = re.search(r"bismillah:\s*" + S, txt)
        core.append({'n': s, 'b': unesc(b.group(1)) if b else None, 'a': [[[e['ar'], e['tr']] for e in a] for a in ay]})
        for l in LANGS:
            h = dump(f'{REPO}/words/{l}/{s:03d}.json',
                     {'s': s, 'l': l, 'a': [[[e['short'][l], e['full'][l]] for e in a] for a in ay]})
            hashes[l].update(h.encode())
        h = dump(f'{REPO}/words/ar/{s:03d}.json', {'s': s, 'l': 'ar', 'a': [[e['fullAr'] for e in a] for a in ay]})
        hashes['ar'].update(h.encode())
    # названия сур в языковых пакетах интерфейса
    for l in names:
        p = f'{REPO}/ui/{l}.json'
        if os.path.exists(p):
            ui = json.load(open(p, encoding='utf-8'))
            if ui.get('surahs') != names[l]:
                ui['surahs'] = names[l]
                json.dump(ui, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    # версии в manifest.json
    mp = f'{REPO}/manifest.json'
    man = json.load(open(mp)) if os.path.exists(mp) else {'v': 1, 'ui': {}, 'words': {}}
    for p, h in hashes.items():
        d = f'{REPO}/words/{p}'
        cur = man['words'].get(p, {})
        dig = h.hexdigest()
        if cur.get('sha') != dig:
            cur = {'v': cur.get('v', 0) + 1, 'sha': dig}
            print(f'words/{p}: новая версия {cur["v"]}')
        cur['files'] = 114
        cur['bytes'] = sum(os.path.getsize(f'{d}/{f}') for f in os.listdir(d))
        man['words'][p] = cur
    for f in glob.glob(f'{REPO}/ui/*.json'):
        l = os.path.basename(f)[:-5]
        dig = hashlib.sha1(open(f, 'rb').read()).hexdigest()
        cur = man['ui'].get(l, {})
        if cur.get('sha') != dig:
            cur = {'v': cur.get('v', 0) + 1, 'sha': dig}
            print(f'ui/{l}: новая версия {cur["v"]}')
        cur['bytes'] = os.path.getsize(f)
        man['ui'][l] = cur
    # конфиденциальность и условия: privacy/<язык>.md, terms/<язык>.md
    for kind in ('privacy', 'terms'):
        man.setdefault(kind, {})
        for f in glob.glob(f'{REPO}/{kind}/*.md'):
            l = os.path.basename(f)[:-3]
            dig = hashlib.sha1(open(f, 'rb').read()).hexdigest()
            cur = man[kind].get(l, {})
            if cur.get('sha') != dig:
                cur = {'v': cur.get('v', 0) + 1, 'sha': dig}
                print(f'{kind}/{l}: новая версия {cur["v"]}')
            cur['bytes'] = os.path.getsize(f)
            man[kind][l] = cur
    json.dump(man, open(mp, 'w'), indent=1)
    if app:
        dump(f'{app}/assets/quran/quran.json', {'v': 1, 's': core})
        print('assets/quran/quran.json обновлён')
    print('Готово.')

if __name__ == '__main__':
    main()
