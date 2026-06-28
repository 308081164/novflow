DEFAULT_RULE_SUMMARY = """
【叙事】主线陆沉舟第一人称「我」；Restricted POV，未见面者不得出现姓名。
【苏令仪】仅隔章章末短切第三人称，本章若无 pov_switch 则不要切。
【语言】禁破折号「——」作补充；单句中文逗号不超过3个；每段「像」类比喻最多1个；禁排比/选项清单。
【顾念】一本正经误用梗；禁止梗后解释（不要「指……」「……原文」）。
【陆沉舟】本章至少一处他拍板的决定；嘴贱内化，对外克制。
【结构】文首 # 第NNN章 标题；禁章首说明书（时间/地点/今日/本章）；禁 --- 分隔线。
【体量】目标约2000汉字。
""".strip()  # 遗留 fallback；新流程请用 system_writing_rules.combine_writing_rules


def build_generate_messages(
    *,
    book_title: str,
    blurb: str,
    rule_summary: str,
    chapter_no: int,
    title: str,
    plot_points: str,
    scene: str,
    comedy_core: str,
    characters: list[dict],
    prev_summary: str,
    next_preview: str,
    style_reference: str,
    target_words: int,
    job_type: str = "draft",
    current_content: str = "",
) -> list[dict]:
    chars_text = "\n".join(
        f"- {c['name']}（{c.get('role','')}）：{c.get('summary','')[:200]}；说话：{c.get('voice_notes','')[:150]}"
        for c in characters
    )
    system = f"""你是长篇网文协作写手，作品《{book_title}》。
严格遵守以下硬规则（违反即失败）：
{rule_summary or DEFAULT_RULE_SUMMARY}
"""

    if job_type == "expand":
        user_task = f"""请在不改变情节走向的前提下，将以下章节扩写到约 {target_words} 字。
保留已有优点，增补细节、对话、体感，不要重复堆砌。
当前正文：
{current_content}
"""
    elif job_type == "fix":
        user_task = f"""请根据规约修订以下章节，保持情节不变，修正违规表达。
输出完整修订后章节。
当前正文：
{current_content}
"""
    else:
        user_task = f"""请撰写完整章节正文。
章号：{chapter_no}
标题：{title}
场景：{scene}
骨架要点：{plot_points}
喜剧核：{comedy_core}
目标字数：{target_words - 100}–{target_words + 200}
前情摘要：{prev_summary or '（首章无前情）'}
后章预告：{next_preview or '（未定）'}
"""

    developer = f"""【作品简介】{blurb[:300]}
【相关角色】
{chars_text or '（暂无）'}
【风格参考（勿照搬）】
{style_reference[:800] if style_reference else '（无）'}
"""

    user = user_task + """
输出格式：
# 第""" + f"{chapter_no:03d}" + f"章 {title}\n（正文，不要章首说明书/meta块，不要输出任何解释）"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": developer + "\n\n" + user},
    ]


def build_ai_lint_messages(content: str, rule_summary: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "你是网文质检员。只输出 JSON，不要 markdown 代码块。",
        },
        {
            "role": "user",
            "content": f"""检查以下章节是否符合规约，输出 JSON：
{{
  "issues": [{{"type":"...", "severity":"error|warn", "line":0, "excerpt":"...", "message":"..."}}],
  "lu_chenzhou_decision": true/false,
  "comedy_present": true/false
}}

重要：
- issues 数组**只放违规项**，禁止输出「符合要求」「格式正确」「未发现」「无问题」等通过说明。
- 每条 message 必须写清**具体违规点 + 修改建议**；excerpt 填违规原文片段（可定位时）。
- severity：error=必须改，warn=建议优化。

规约摘要：
{rule_summary or DEFAULT_RULE_SUMMARY}

章节：
{content[:6000]}
""",
        },
    ]
