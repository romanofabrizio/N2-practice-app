# JLPT N2 演習アプリ

Static app — no build step, no backend. 5,650 questions (5,634 generated + 16 curated exam-format).

## Files
- `index.html` — the app (vanilla JS)
- `questions.json` — generated bank (~5,600 questions) 
- `curated.json` — hand-written 読解 (短文/中文/長文/統合理解/情報検索) + dialogue 聴解 (課題理解/ポイント理解/即時応答) + 用法/並べ替え
- `grammar.json` — searchable N2 grammar reference (149 patterns)

## Features
- Progress saved in localStorage: seen-question prioritization, missed-question review pool (2 consecutive correct = graduated), score history on the dashboard
- Mock test: 45 min, ~38 questions in exam order with multi-question reading passages and two-voice dialogue listening

## Deploy
**Render (static site):** New → Static Site → point at a repo containing these two files. Publish directory: `.`

**Your existing FastAPI SRS app:** drop both files into `static/n2/` and open `/static/n2/index.html`. Same origin, so no CORS concerns.

**Local test:** `python3 -m http.server 8000` in this folder (fetch() needs http, not file://).

## Regenerating / expanding the bank
`generate.py` (included) rebuilds `questions.json` from:
- elzup/jlpt-word-list — N2 vocab (JMdict/EDICT-derived, EDRDG licence)
- jkindrix/japanese-language-data — grammar + Tatoeba sentences (CC-BY-SA 4.0 / CC-BY 2.0 FR)

Question data is redistributable under CC-BY-SA 4.0 with attribution (shown in the app footer). Real JLPT past questions are copyrighted by JEES/Japan Foundation and are NOT included.

## Question schema
```json
{"s":"kanji","q":"...<u>削除</u>...","opts":["さくじょ","..."],"a":0,"exp":"...","en":"optional EN"}
```
Sections: kanji, hyoki, bunmyaku, iikae, yoho, bunpo, narabe (has "order"), dokkai (has "passage"), chokai (has "audio" — spoken via Web Speech API).

Missed questions export as JSON from the results screen for import into your SRS.


## Continuous generation (optional, uses your Anthropic API key)
1. Copy `n2_generator.py` into your existing FastAPI SRS repo.
2. In your main app file: `from n2_generator import router as n2_router` then `app.include_router(n2_router)`.
3. Add CORS for your Pages origin (see docstring in n2_generator.py).
4. In `index.html`, set `const BACKEND = "https://your-srs-app.onrender.com"`.
5. A "新しい問題を生成" panel appears in the ドリル tab: pick a section, generate 3 at a time (~1-3 yen per batch at Sonnet pricing). Questions are validated for structure, deduplicated, stored in `n2_generated.db`, and marked 生成 in the app. Bad ones can be deleted from the results screen.

Note: generated questions are structurally validated but not human-reviewed. Treat them as drill volume, not gospel. Your Render free-tier disk is ephemeral: n2_generated.db resets on redeploy, same as your SRS SQLite — if that bites, point N2_DB_PATH at the same persistence workaround you use for your decks.
