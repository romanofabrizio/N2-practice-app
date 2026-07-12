"""
n2_generator.py — drop-in FastAPI router for continuous N2 question generation.

Setup (in your existing SRS FastAPI app):
    from n2_generator import router as n2_router
    app.include_router(n2_router)

Requires env var ANTHROPIC_API_KEY (you already have this for card generation).

Endpoints:
    POST /n2/generate?section=dokkai_tan&n=3   -> generate & store new questions
    GET  /n2/questions                          -> all stored generated questions (app format)
    GET  /n2/stats                              -> counts per section
    DELETE /n2/questions/{qid}                  -> remove a bad question

CORS: if your Pages site is on a different origin, add in your main app:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware,
        allow_origins=["https://YOURNAME.github.io"],
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])
"""
import json
import os
import sqlite3
import hashlib
import urllib.request
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/n2", tags=["n2"])

DB_PATH = os.environ.get("N2_DB_PATH", "n2_generated.db")
MODEL = "claude-sonnet-4-6"
MAX_PER_CALL = 5


def _db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS n2_questions(
        id TEXT PRIMARY KEY,
        section TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    return con


# ---------------- prompts per section ----------------
COMMON_RULES = """あなたはJLPT N2の問題作成者です。以下のルールを厳守してください。
- 語彙・文法・漢字はN2レベル（N1専用の語彙・文法は使わない）
- 正解は必ず1つだけ。他の選択肢が文脈上成立しないことを確認する
- 選択肢は互いに重複しない
- 実在の試験問題の複製はしない。完全オリジナルで作成する
- 出力はJSON配列のみ。前置き・後置き・マークダウンの```は一切書かない"""

SECTION_PROMPTS = {
    "dokkai_tan": """短文読解を{n}題作成。各180〜230字の説明文・意見文（テーマ：仕事、生活、社会、科学など多様に）。
筆者の主張や理由を問う質問1問、選択肢4つ。
JSON形式: [{{"s":"dokkai_tan","kind":"group","passage":"本文","questions":[{{"q":"質問","opts":["正解","誤答1","誤答2","誤答3"],"a":0,"exp":"根拠となる本文の箇所を示す解説"}}]}}]""",
    "dokkai_chu": """中文読解を{n}題作成。各450〜550字、段落2〜3つ。
質問2〜3問（指示語の内容、理由、筆者の主張など多角的に）、各4択。
JSON形式: [{{"s":"dokkai_chu","kind":"group","passage":"本文（段落は\\nで区切る）","questions":[{{"q":"...","opts":["正解","誤1","誤2","誤3"],"a":0,"exp":"..."}}]}}]""",
    "dokkai_joho": """情報検索問題を{n}題作成。お知らせ・案内・募集要項の形式（■や・で構造化、料金/日程/条件の組み合わせを含む）。
特定の状況の人がどうすべきか、料金計算、内容正誤を問う質問2問、各4択。
JSON形式: [{{"s":"dokkai_joho","kind":"group","passage":"お知らせ全文","questions":[{{"q":"...","opts":["正解","誤1","誤2","誤3"],"a":0,"exp":"..."}}]}}]""",
    "chokai_kadai": """聴解・課題理解を{n}題作成。職場や日常の男女の会話（4〜6往復）。会話の結果「これから何をするか」を問う。
JSON形式: [{{"s":"chokai_kadai","audio":[{{"sp":"F","t":"発話"}},{{"sp":"M","t":"発話"}}],"q":"男の人／女の人はこのあと何をしますか。","opts":["正解","誤1","誤2","誤3"],"a":0,"exp":"根拠の発話を引用した解説"}}]""",
    "chokai_point": """聴解・ポイント理解を{n}題作成。男女の会話（3〜5往復）。理由・原因・詳細を問う。会話には正解を選ばせないためのひっかけ（一度否定される情報）を入れる。
JSON形式: [{{"s":"chokai_point","audio":[{{"sp":"M","t":"..."}},{{"sp":"F","t":"..."}}],"q":"...のはなぜですか。","opts":["正解","誤1","誤2","誤3"],"a":0,"exp":"..."}}]""",
    "chokai_sokuji": """聴解・即時応答を{n}題作成。職場での一言（依頼、報告、謝罪、確認、挨拶など）に対する適切な応答を選ぶ。選択肢は3つ。誤答は「言葉は関連するが応答として不自然」なもの。
JSON形式: [{{"s":"chokai_sokuji","audio":[{{"sp":"F","t":"一言"}}],"q":"応答として最もよいものを選びなさい。","opts":["正解","誤1","誤2"],"a":0,"exp":"..."}}]""",
    "yoho": """語彙・用法問題を{n}題作成。N2レベルの語（動詞・副詞・名詞）について、正しい使い方の文1つと、意味を誤解した不自然な文3つ。
JSON形式: [{{"s":"yoho","q":"「語」","opts":["正しい用法の文","誤用1","誤用2","誤用3"],"a":0,"exp":"語の意味と典型的な使い方"}}]""",
    "narabe": """文法・並べ替え問題を{n}題作成。4つの語句を正しく並べたとき★の位置に入るものを問う。文は「AAA　＿＿　＿＿　★　＿＿　BBB。」の形式（★の位置は変えてよい）。
"a"は選択肢配列の中で★に入る語句のインデックス。"order"に正しい並び順を空白区切りで書く。
JSON形式: [{{"s":"narabe","q":"文頭　＿＿　★　＿＿　＿＿　文末。","opts":["語句1","語句2","語句3","語句4"],"a":2,"order":"語句4 語句3 語句1 語句2","exp":"完成文と解説"}}]""",
}


def _call_claude(prompt: str) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 4000,
        "system": COMMON_RULES,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return "".join(b.get("text", "") for b in data.get("content", []))


def _validate(item: dict) -> bool:
    try:
        opts = item["opts"]
        n = len(opts)
        if item.get("kind") == "group":
            return bool(item.get("passage")) and all(_validate(q) for q in item["questions"])
        if n not in (3, 4) or len(set(opts)) != n:
            return False
        if not (0 <= item["a"] < n):
            return False
        return True
    except (KeyError, TypeError):
        # group items validate questions individually
        if item.get("kind") == "group":
            try:
                return bool(item.get("passage")) and all(
                    len(q["opts"]) == 4 and len(set(q["opts"])) == 4 and 0 <= q["a"] < 4
                    for q in item["questions"])
            except (KeyError, TypeError):
                return False
        return False


@router.post("/generate")
def generate(section: str = Query(...), n: int = Query(3, ge=1, le=MAX_PER_CALL)):
    if section not in SECTION_PROMPTS:
        raise HTTPException(400, f"section must be one of {list(SECTION_PROMPTS)}")
    raw = _call_claude(SECTION_PROMPTS[section].format(n=n))
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(502, "Claude returned non-JSON; try again")
    if not isinstance(items, list):
        items = [items]

    con = _db()
    stored, skipped = 0, 0
    for it in items:
        if not _validate(it):
            skipped += 1
            continue
        it["gen"] = True  # marks machine-generated in the app
        blob = json.dumps(it, ensure_ascii=False, sort_keys=True)
        qid = hashlib.sha1(blob.encode()).hexdigest()[:12]
        try:
            con.execute("INSERT INTO n2_questions(id, section, payload) VALUES (?,?,?)",
                        (qid, section, blob))
            stored += 1
        except sqlite3.IntegrityError:
            skipped += 1  # duplicate
    con.commit()
    con.close()
    return {"stored": stored, "skipped": skipped, "section": section}


@router.get("/questions")
def questions():
    con = _db()
    rows = con.execute("SELECT id, payload FROM n2_questions ORDER BY created_at").fetchall()
    con.close()
    groups, items = [], []
    for qid, blob in rows:
        it = json.loads(blob)
        it["srv_id"] = qid
        (groups if it.get("kind") == "group" else items).append(it)
    return {"groups": groups, "items": items}


@router.get("/stats")
def stats():
    con = _db()
    rows = con.execute("SELECT section, COUNT(*) FROM n2_questions GROUP BY section").fetchall()
    con.close()
    return dict(rows)


@router.delete("/questions/{qid}")
def delete_question(qid: str):
    con = _db()
    cur = con.execute("DELETE FROM n2_questions WHERE id = ?", (qid,))
    con.commit()
    con.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "not found")
    return {"deleted": qid}
