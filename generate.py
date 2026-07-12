#!/usr/bin/env python3
"""Generate a large JLPT N2 question bank from open-licensed datasets.

Sources:
- elzup/jlpt-word-list (N2 vocab CSV)
- jkindrix/japanese-language-data (CC-BY-SA 4.0): grammar-curated/n2.json,
  Tatoeba sentences (CC-BY 2.0 FR)
"""
import csv, json, random, re, unicodedata
from collections import defaultdict

random.seed(20260708)
BASE = "/home/claude/data/japanese-language-data-main"

# ---------- load vocab ----------
vocab = []
with open("/home/claude/data/n2.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        w = row["expression"].strip()
        r = row["reading"].strip()
        m = row["meaning"].strip()
        if w and r and m:
            vocab.append({"w": w, "r": r, "m": m})
# dedupe
seen = set(); vv = []
for v in vocab:
    if v["w"] not in seen:
        seen.add(v["w"]); vv.append(v)
vocab = vv
print("vocab:", len(vocab))

HAS_KANJI = lambda s: any("\u4e00" <= c <= "\u9fff" for c in s)
kanji_vocab = [v for v in vocab if HAS_KANJI(v["w"]) and re.fullmatch(r"[ぁ-ゖー]+", v["r"] or "")]
print("kanji vocab:", len(kanji_vocab))

# ---------- load sentences ----------
sents = json.load(open(f"{BASE}/data/corpus/sentences.json"))["sentences"]
sents = [s for s in sents if s.get("japanese") and s.get("english")]
print("sentences:", len(sents))
# index sentences by contained vocab word (limit sentence length for drill use)
sent_by_word = defaultdict(list)
short_sents = [s for s in sents if 8 <= len(s["japanese"]) <= 55]
for s in short_sents:
    jp = s["japanese"]
    # cheap containment check later per word (vocab is 1.7k, sents 20k+ -> do word loop)
word_set = {v["w"] for v in kanji_vocab}
for s in short_sents:
    jp = s["japanese"]
    for w in word_set:
        if w in jp:
            if len(sent_by_word[w]) < 4:
                sent_by_word[w].append(s)
print("words with sentences:", len(sent_by_word))

# ---------- reading distortion for 漢字読み distractors ----------
VOICING = {"か":"が","き":"ぎ","く":"ぐ","け":"げ","こ":"ご","さ":"ざ","し":"じ","す":"ず","せ":"ぜ","そ":"ぞ",
           "た":"だ","ち":"ぢ","つ":"づ","て":"で","と":"ど","は":"ば","ひ":"び","ふ":"ぶ","へ":"べ","ほ":"ぼ"}
UNVOICE = {v: k for k, v in VOICING.items()}
HANDAKU = {"は":"ぱ","ひ":"ぴ","ふ":"ぷ","へ":"ぺ","ほ":"ぽ","ば":"ぱ","び":"ぴ","ぶ":"ぷ","べ":"ぺ","ぼ":"ぽ"}

def distort(r):
    outs = set()
    chars = list(r)
    for i, c in enumerate(chars):
        for table in (VOICING, UNVOICE, HANDAKU):
            if c in table:
                x = chars.copy(); x[i] = table[c]; outs.add("".join(x))
    # long vowel add/remove
    if "ー" not in r:
        for i, c in enumerate(chars):
            if c in "ゅょ":
                x = chars.copy(); x.insert(i+1, "う"); outs.add("".join(x))
    if "う" in r:
        i = r.index("う")
        if i > 0: outs.add(r[:i] + r[i+1:])
    else:
        for i, c in enumerate(chars):
            if c in "おこそとのほもよろごぞどぼ":
                x = chars.copy(); x.insert(i+1, "う"); outs.add("".join(x))
    # small tsu toggle
    if "っ" in r:
        outs.add(r.replace("っ", "", 1))
        outs.add(r.replace("っ", "つ", 1))
    else:
        for i in range(1, len(chars)):
            if chars[i] in "かきくけこたちつてとぱぴぷぺぽさしすせそ":
                x = chars.copy(); x.insert(i, "っ"); outs.add("".join(x))
                break
    # ん toggle
    if "ん" in r:
        outs.add(r.replace("ん", "", 1))
    outs.discard(r)
    return [o for o in outs if 2 <= len(o) <= len(r) + 2]

# ---------- homophone / similar-kanji index for 表記 ----------
by_reading = defaultdict(list)
for v in kanji_vocab:
    by_reading[v["r"]].append(v)
kanji_chars = defaultdict(list)  # char -> words containing it
for v in kanji_vocab:
    for c in v["w"]:
        if "\u4e00" <= c <= "\u9fff":
            kanji_chars[c].append(v)

questions = []
def add(q): questions.append(q)

def esc(s): return s

# ============ 1. 漢字読み ============
n_kanji = 0
for v in kanji_vocab:
    ds = distort(v["r"])
    if len(ds) < 3:
        continue
    opts = random.sample(ds, 3)
    ss = sent_by_word.get(v["w"])
    if ss:
        s = random.choice(ss)
        qtext = s["japanese"].replace(v["w"], f"<u>{v['w']}</u>", 1)
        extra = {"en": s["english"]}
    else:
        qtext = f"<u>{v['w']}</u>"
        extra = {}
    add({"s": "kanji", "q": qtext, "opts": [v["r"]] + opts, "a": 0,
         "exp": f"{v['w']}（{v['r']}）= {v['m']}", **extra})
    n_kanji += 1
print("kanji questions:", n_kanji)

# ============ 2. 表記 (reading -> correct kanji) ============
n_hyoki = 0
for v in kanji_vocab:
    # distractors: homophones first, then words sharing a kanji char, then random
    cands = [x for x in by_reading[v["r"]] if x["w"] != v["w"]]
    pool = []
    for c in v["w"]:
        if c in kanji_chars:
            pool += [x for x in kanji_chars[c] if x["w"] != v["w"] and len(x["w"]) == len(v["w"])]
    random.shuffle(pool)
    distract = []
    for x in cands + pool:
        if x["w"] not in [d["w"] for d in distract] and x["w"] != v["w"]:
            distract.append(x)
        if len(distract) >= 3:
            break
    if len(distract) < 3:
        continue
    ss = sent_by_word.get(v["w"])
    if ss:
        s = random.choice(ss)
        qtext = s["japanese"].replace(v["w"], f"<u>{v['r']}</u>", 1)
        extra = {"en": s["english"]}
    else:
        qtext = f"<u>{v['r']}</u>（{v['m'].split(',')[0]}）"
        extra = {}
    add({"s": "hyoki", "q": qtext, "opts": [v["w"]] + [d["w"] for d in distract], "a": 0,
         "exp": f"{v['w']}（{v['r']}）= {v['m']}", **extra})
    n_hyoki += 1
print("hyoki questions:", n_hyoki)

# ============ 3. 言い換え/意味 (word -> meaning MCQ) ============
n_imi = 0
for v in vocab:
    others = random.sample(vocab, 6)
    distract = [o["m"] for o in others if o["w"] != v["w"] and o["m"] != v["m"]][:3]
    if len(distract) < 3:
        continue
    ss = sent_by_word.get(v["w"])
    if ss:
        s = random.choice(ss)
        qtext = s["japanese"].replace(v["w"], f"<u>{v['w']}</u>", 1)
    else:
        qtext = f"<u>{v['w']}</u>（{v['r']}）"
    add({"s": "iikae", "q": qtext, "opts": [v["m"]] + distract, "a": 0,
         "exp": f"{v['w']}（{v['r']}）= {v['m']}"})
    n_imi += 1
print("meaning questions:", n_imi)

# ============ 4. 文脈規定 (cloze from real sentences) ============
n_cloze = 0
for w, ss in sent_by_word.items():
    v = next(x for x in kanji_vocab if x["w"] == w)
    s = ss[0]
    jp = s["japanese"]
    if jp.count(w) != 1:
        continue
    qtext = jp.replace(w, "（　　）")
    # distractors: words of similar length, no meaning-word overlap with sentence english
    en_words = set(re.findall(r"[a-z']+", s["english"].lower()))
    distract = []
    tries = random.sample(kanji_vocab, min(60, len(kanji_vocab)))
    for o in tries:
        if o["w"] == w or abs(len(o["w"]) - len(w)) > 1:
            continue
        om = set(re.findall(r"[a-z']+", o["m"].lower()))
        if om & en_words:
            continue
        distract.append(o["w"])
        if len(distract) >= 3:
            break
    if len(distract) < 3:
        continue
    add({"s": "bunmyaku", "q": qtext, "opts": [w] + distract, "a": 0,
         "exp": f"{w}（{v['r']}）= {v['m']}　→ 「{jp}」", "en": s["english"]})
    n_cloze += 1
print("cloze questions:", n_cloze)

# ============ 5. 文法形式 (grammar pattern cloze) ============
grammar = json.load(open(f"{BASE}/grammar-curated/n2.json"))
print("grammar points:", len(grammar))

def pattern_variants(g):
    """Extract literal Japanese chunks that might appear in example sentences."""
    pats = set()
    for chunk in re.split(r"[/／,、]", g.get("pattern", "")):
        jp = "".join(re.findall(r"[ぁ-ゖァ-ヺー一-鿿]+", chunk))
        if 2 <= len(jp) <= 8:
            pats.add(jp)
    return sorted(pats, key=len, reverse=True)

all_patterns = []
for g in grammar:
    all_patterns += [(p, g["id"]) for p in pattern_variants(g)]

n_bunpo = 0
for g in grammar:
    pats = pattern_variants(g)
    for ex in g.get("examples", []):
        jp = ex.get("japanese", "")
        hit = next((p for p in pats if p in jp), None)
        if not hit or jp.count(hit) != 1:
            continue
        qtext = jp.replace(hit, "（　　）")
        # distractors: other grammar chunks of similar length not in sentence
        distract = []
        cands = [p for p, gid in all_patterns if gid != g["id"] and p not in jp and abs(len(p) - len(hit)) <= 2]
        random.shuffle(cands)
        for c in cands:
            if c not in distract:
                distract.append(c)
            if len(distract) >= 3:
                break
        if len(distract) < 3:
            continue
        add({"s": "bunpo", "q": qtext, "opts": [hit] + distract, "a": 0,
             "exp": f"〜{hit}：{g.get('meaning_en','')}。{(g.get('meaning_detailed') or '')[:120]}",
             "en": ex.get("english", "")})
        n_bunpo += 1
        break  # one per grammar point per pass
# second example pass for volume
for g in grammar:
    pats = pattern_variants(g)
    used = 0
    for ex in g.get("examples", [])[1:]:
        jp = ex.get("japanese", "")
        hit = next((p for p in pats if p in jp), None)
        if not hit or jp.count(hit) != 1:
            continue
        qtext = jp.replace(hit, "（　　）")
        distract = []
        cands = [p for p, gid in all_patterns if gid != g["id"] and p not in jp and abs(len(p) - len(hit)) <= 2]
        random.shuffle(cands)
        for c in cands:
            if c not in distract:
                distract.append(c)
            if len(distract) >= 3:
                break
        if len(distract) < 3:
            continue
        add({"s": "bunpo", "q": qtext, "opts": [hit] + distract, "a": 0,
             "exp": f"〜{hit}：{g.get('meaning_en','')}。{(g.get('meaning_detailed') or '')[:120]}",
             "en": ex.get("english", "")})
        n_bunpo += 1
        used += 1
        if used >= 2:
            break
print("grammar questions:", n_bunpo)

# ============ 6. 聴解 (sentence listening -> meaning) ============
n_lis = 0
lis_pool = [s for s in short_sents if 12 <= len(s["japanese"]) <= 45]
random.shuffle(lis_pool)
for s in lis_pool[:800]:
    others = random.sample(lis_pool, 5)
    distract = [o["english"] for o in others if o["english"] != s["english"]][:3]
    if len(distract) < 3:
        continue
    add({"s": "chokai", "audio": s["japanese"], "q": "音声の内容に合うものはどれか。",
         "opts": [s["english"]] + distract, "a": 0,
         "exp": f"「{s['japanese']}」"})
    n_lis += 1
print("listening questions:", n_lis)

# ---------- write ----------
print("TOTAL:", len(questions))
meta = {
    "generated": "2026-07-08",
    "attribution": [
        "Vocabulary: elzup/jlpt-word-list (JMdict/EDICT-derived, EDRDG licence)",
        "Grammar & meta: jkindrix/japanese-language-data (CC-BY-SA 4.0)",
        "Sentences: Tatoeba Project via jmdict-examples (CC-BY 2.0 FR)",
    ],
}
out = {"meta": meta, "questions": questions}
with open("/home/claude/questions.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
import os
print("size:", os.path.getsize("/home/claude/questions.json") // 1024, "KB")
