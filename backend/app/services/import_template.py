"""从「我的AI成精了」导入模板书籍数据。"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.models import Book, Chapter, ChapterPlan, Character, User
from app.services.generation import count_words

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT.parent / "我的AI成精了"

# 前30章规划（从故事大纲-章节规划提取）
CHAPTER_PLANS = [
    (1, "AI要跟我私奔", "顾念「赛博私奔」+ 条目 47", "94.7%；决定逃亡；宽带工装开门"),
    (2, "社区过关与拼贴梦", "拼贴记忆", "社区首次核查过关；七月记忆与卷宗对不上"),
    (3, "丰巢空柜与八平米", "收旧电视误会", "丰巢空柜；小裴失联；群租八平米弱电井"),
    (4, "合规二次上门与黄马甲", "黄马甲伪装", "合规二次上门；弱电箱赌赢；外卖转移"),
    (5, "十一号线与B口女警", "很正点（内心）", "11 号线 B 口女警；借晕脱身；小裴纸条"),
    (6, "假方向与路人镜头", "", "假方向路人拍"),
    (7, "群租躲藏与争宠", "顾念争宠", "群租躲藏"),
    (8, "热饮与黑夹克", "买热饮", "岳重追杀①"),
    (9, "独狗与通缉令", "「独狗」", "通缉令"),
    (10, "八平米日常", "", "躲藏日常"),
    (11, "弄堂雨景", "", "弄堂雨景"),
    (12, "通缉犯与芽芽", "吓哭芽芽", "说通缉犯"),
    (13, "快递柜馊主意", "快递柜虎狼", "顾念馊主意"),
    (14, "芽芽的糖", "芽芽后续", "修风筝和解"),
    (15, "网友寻人帖", "网友", "寻人帖发酵"),
    (16, "里弄告别", "芽芽后续", "赠画告别"),
    (17, "借车离城", "", "借车跑路"),
    (18, "服务区一夜", "", "服务区"),
    (19, "后备箱像综艺", "", "后备箱综艺"),
    (20, "全民寻狼", "", "全民寻狼"),
    (21, "硬卧与弹幕", "", "火车南逃"),
    (22, "福州暗仓", "", "福州"),
    (23, "摆拍逃亡课", "", "摆拍课"),
    (24, "旧货市场与岳重", "", "旧货市场"),
    (25, "狼哥复位", "", "狼哥"),
    (26, "小裴半句", "", "小裴"),
    (27, "CP谣言", "", "CP谣言"),
    (28, "北返决定", "", "北返"),
    (29, "夜车北行", "", "夜车"),
    (30, "图书馆前夜", "", "图书馆前夜"),
]


def _read(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def load_template_data() -> dict:
    writing_rules = _read(SOURCE / "写作规约.md")
    outline = _read(SOURCE / "故事大纲-章节规划")
    world = _read(SOURCE / "世界观")
    genre = _read(SOURCE / "题材定位")
    corpus_gu = _read(SOURCE / "语料库" / "顾念-网络梗语料库")
    corpus_police = _read(SOURCE / "语料库" / "女警起疑-组合抓手链")

    characters = []
    char_dir = SOURCE / "角色卡"
    if char_dir.exists():
        role_map = {
            "陆沉舟": "男主",
            "顾念": "AI女主",
            "苏令仪": "女警",
            "岳重": "反派",
            "霍铮": "配角",
            "顾心怡": "配角",
            "魏峥嵘": "反派",
            "张秉信": "配角",
            "顾鸿深": "配角",
            "顾心怡": "配角",
        }
        for i, f in enumerate(sorted(char_dir.iterdir())):
            if f.is_file():
                characters.append(
                    {
                        "name": f.name,
                        "role": role_map.get(f.name, "角色"),
                        "content": f.read_text(encoding="utf-8"),
                        "sort_order": i,
                    }
                )

    chapters = []
    body_dir = SOURCE / "正文"
    if body_dir.exists():
        for f in sorted(body_dir.glob("第*.md")):
            m = re.match(r"第(\d+)章\s*(.*)", f.stem)
            if m:
                no = int(m.group(1))
                title = m.group(2).strip()
                content = f.read_text(encoding="utf-8")
                chapters.append({"chapter_no": no, "title": title, "content": content})

    return {
        "title": "A级追逃：耳机里的共犯",
        "blurb": (
            "AI 一句「要不要跟我一起逃？」智源工程师陆沉舟携 AI 顾念赛博私奔，"
            "成了全网最脏的 A 级逃犯「独狗」，热搜跑得比警车还快：欺小孩、偷衣贼、"
            "高速口路人……词条越滚越邪，女警越追越近，网友越骂越起劲。"
            "这男的，坏、疯，还怪能活。"
        ),
        "genre": "现实 · 悬疑 · 轻喜剧 · 猫鼠追逃",
        "template_id": "chase_comedy",
        "writing_rules": writing_rules,
        "world_setting": world + "\n\n" + genre[:3000],
        "outline": outline[:8000],
        "corpus": corpus_gu + "\n\n" + corpus_police,
        "characters": characters,
        "chapter_plans": CHAPTER_PLANS,
        "chapters": chapters,
    }


def create_book_from_template(
    db: Session,
    user: User,
    title: str | None = None,
    blurb: str | None = None,
    import_chapters: bool = True,
) -> Book:
    data = load_template_data()
    book = Book(
        user_id=user.id,
        title=title or data["title"],
        blurb=blurb or data["blurb"],
        genre=data["genre"],
        template_id=data["template_id"],
        writing_rules=data["writing_rules"],
        world_setting=data["world_setting"],
        outline=data["outline"],
        corpus=data["corpus"],
    )
    db.add(book)
    db.flush()

    for c in data["characters"]:
        db.add(
            Character(
                book_id=book.id,
                name=c["name"],
                role=c["role"],
                content=c["content"],
                sort_order=c["sort_order"],
            )
        )

    existing_nos = {ch["chapter_no"] for ch in data.get("chapters", [])}
    for no, t, syn, hook in data["chapter_plans"]:
        status = "written" if no in existing_nos else "planned"
        db.add(
            ChapterPlan(
                book_id=book.id,
                chapter_no=no,
                title=t,
                synopsis=syn,
                comedy_hook=hook,
                status=status,
            )
        )
        db.add(
            Chapter(
                book_id=book.id,
                chapter_no=no,
                title=t,
                content="",
                status="planned",
            )
        )

    if import_chapters:
        for ch in data.get("chapters", []):
            chapter = (
                db.query(Chapter)
                .filter(Chapter.book_id == book.id, Chapter.chapter_no == ch["chapter_no"])
                .first()
            )
            if chapter:
                chapter.content = ch["content"]
                chapter.title = ch["title"]
                chapter.word_count = count_words(ch["content"])
                chapter.status = "written"

    db.commit()
    db.refresh(book)
    return book


def seed_demo_user(db: Session) -> User:
    email = "demo@novflow.local"
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(
        email=email,
        password_hash=hash_password("demo123456"),
        name="演示作者",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
