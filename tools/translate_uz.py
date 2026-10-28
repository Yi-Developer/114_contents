#!/usr/bin/env python3
"""Перевод слов Корана на узбекский (латиница) → words/uz/NNN.json

Источник: words/ar (толкование автора, как в книге «معاني كلمات القرآن»)
+ words/ru (готовый русский перевод) как подсказка. Стиль и термины
берутся из уже готовых сур words/uz (1, 93–114) — они идут в промпт как образец.

Запуск (из корня репозитория):
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 tools/translate_uz.py            # все недостающие суры
    python3 tools/translate_uz.py 2 3 18     # только указанные
    python3 tools/translate_uz.py --model claude-opus-5-5 --workers 4

Скрипт докачивает: готовые суры пропускает, промежуточный прогресс
хранит в tools/.uz_cache/. Число и порядок слов проверяются по words/ru.
"""
import json, os, re, sys, time, urllib.request, concurrent.futures as cf

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f'{REPO}/words/uz'; CACHE = f'{REPO}/tools/.uz_cache'
MODEL = 'claude-sonnet-5-5'; WORKERS = 3; BATCH = 35  # слов на запрос

SYSTEM = """Siz Qurʼon soʻzlarini arab tilidan oʻzbek tiliga (lotin yozuvi) tarjima qiluvchi mutaxassissiz.
Har bir soʻz uchun ikki narsa berasiz:
1) "q" — qisqa tarjima: soʻzning oyatdagi maʼnosi, 1–4 soʻz.
2) "t" — batafsil izoh: muallif (Bashir Ahmad Sulaymon Yunus) arabcha tafsirining TOʻLIQ va aniq tarjimasi. Hech narsani tashlab ketmang, oʻzingizdan qoʻshmang.
Qoidalar:
- Rasmiy oʻzbek lotin imlosi: oʻ, gʻ (U+02BB), tutuq belgisi ʼ (U+02BC). Kirill harflari ishlatilmaydi.
- Iqtiboslar «…» qavslarida. Arabcha atamalar transliteratsiyada: «Inna», «Lam», «Mo», «Kana».
- Atamalar: Alloh, Robb, Rasul, Paygʻambar, oxirat, Jahannam, Jannat, namoz, zakot, taqvo, iymon, kufr, mushrik, ahli kitob, jor harfi, taʼkid va nasb harfi, ism mavsul, ishora ismi, zamir, zarf, muzoriʼ feʼl, noqis feʼl, jazm, nahy harfi, istisno harfi, atf harfi, sollallohu alayhi va sallam, alayhissalom.
- Takrorlanuvchi izohlarni namunadagidek bir xil soʻzlar bilan bering.
- Rus tarjimasi faqat yordamchi; asos — arabcha izoh.
Javob: faqat JSON massiv, kirishdagi tartibda: [{"i":1,"q":"...","t":"..."}, ...]. Boshqa hech narsa yozmang."""

def load(p): return json.load(open(p, encoding='utf-8'))

def examples():
    ex = []
    for s in (93, 96, 112):
        p = f'{OUT}/{s:03d}.json'
        if not os.path.exists(p): continue
        uz = load(p)['a']
        ar, ru = load(f'{REPO}/words/ar/{s:03d}.json')['a'], load(f'{REPO}/words/ru/{s:03d}.json')['a']
        for a in range(min(4, len(uz))):
            for w in range(len(uz[a])):
                ex.append({'ar': ar[a][w], 'ru': ru[a][w][0] + ' | ' + ru[a][w][1], 'q': uz[a][w][0], 't': uz[a][w][1]})
    return ex

EX = None
def call(items, model):
    global EX
    if EX is None: EX = json.dumps(examples(), ensure_ascii=False)
    user = ('Namuna (tayyor tarjimalar, uslub va atamalar uchun):\n' + EX +
            '\n\nEndi quyidagilarni tarjima qiling. "oyat" — oyat raqami, "ar" — arabcha izoh, "ru" — ruscha qisqa | batafsil:\n' +
            json.dumps(items, ensure_ascii=False))
    body = json.dumps({'model': model, 'max_tokens': 16000, 'system': SYSTEM,
                       'messages': [{'role': 'user', 'content': user}]}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request('https://api.anthropic.com/v1/messages', body, {
                'content-type': 'application/json', 'x-api-key': os.environ['ANTHROPIC_API_KEY'],
                'anthropic-version': '2023-06-01'})
            r = json.load(urllib.request.urlopen(req, timeout=600))
            txt = ''.join(b.get('text', '') for b in r['content'])
            txt = re.sub(r'^```(json)?|```$', '', txt.strip()).strip()
            out = json.loads(txt)
            if [o['i'] for o in out] != [it['i'] for it in items]: raise ValueError('index mismatch')
            return out
        except Exception as e:
            print(f'  retry {attempt + 1}: {e}', flush=True); time.sleep(5 * (attempt + 1))
    raise RuntimeError('API failed')

def norm(t):
    t = t.replace('‘', 'ʻ').replace('’', 'ʼ')
    t = re.sub(r"([OoGg])['ʼ`]", r"\1ʻ", t)
    return t.replace("'", 'ʼ').strip()

def surah(s, model):
    dst = f'{OUT}/{s:03d}.json'
    if os.path.exists(dst): return f'{s}: уже есть'
    ar, ru = load(f'{REPO}/words/ar/{s:03d}.json')['a'], load(f'{REPO}/words/ru/{s:03d}.json')['a']
    flat = [(a, w) for a in range(len(ru)) for w in range(len(ru[a]))]
    cp = f'{CACHE}/{s:03d}.json'; done = load(cp) if os.path.exists(cp) else {}
    for b in range(0, len(flat), BATCH):
        chunk = flat[b:b + BATCH]
        if str(b) in done: continue
        items = [{'i': k + 1, 'oyat': a + 1, 'ar': ar[a][w], 'ru': ru[a][w][0] + ' | ' + ru[a][w][1]}
                 for k, (a, w) in enumerate(chunk)]
        done[str(b)] = [[norm(o['q']), norm(o['t'])] for o in call(items, model)]
        os.makedirs(CACHE, exist_ok=True); json.dump(done, open(cp, 'w', encoding='utf-8'), ensure_ascii=False)
    words = [x for b in sorted(done, key=int) for x in done[b]]
    assert len(words) == len(flat)
    res = [[] for _ in ru]
    for (a, w), x in zip(flat, words): res[a].append(x)
    json.dump({'s': s, 'l': 'uz', 'a': res}, open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    return f'{s}: готово ({len(flat)} слов)'

def main():
    global WORKERS
    args = sys.argv[1:]; model = MODEL
    if '--model' in args: i = args.index('--model'); model = args[i + 1]; del args[i:i + 2]
    if '--workers' in args: i = args.index('--workers'); WORKERS = int(args[i + 1]); del args[i:i + 2]
    todo = [int(a) for a in args] or list(range(1, 115))
    os.makedirs(OUT, exist_ok=True)
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for r in ex.map(lambda s: surah(s, model), todo): print(r, flush=True)
    manifest()

def manifest():
    import hashlib
    files = sorted(f for f in os.listdir(OUT) if f.endswith('.json'))
    if len(files) < 114:
        print(f'words/uz: {len(files)}/114 — manifest.json не трогаю, пока не готовы все суры'); return
    h = hashlib.sha1()
    for f in files: h.update(hashlib.sha1(open(f'{OUT}/{f}', 'rb').read()).hexdigest().encode())
    mp = f'{REPO}/manifest.json'; man = load(mp); cur = man['words'].get('uz', {})
    if cur.get('sha') != h.hexdigest(): cur = {'v': cur.get('v', 0) + 1, 'sha': h.hexdigest()}
    cur.update(files=114, bytes=sum(os.path.getsize(f'{OUT}/{f}') for f in files))
    man['words']['uz'] = cur; json.dump(man, open(mp, 'w'), indent=1)
    print(f'manifest.json: words/uz v{cur["v"]}')

if __name__ == '__main__':
    main()
