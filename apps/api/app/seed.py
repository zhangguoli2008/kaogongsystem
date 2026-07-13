from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.analysis import Analysis
from app.models.question import Question
from app.models.review import ReviewRecord, UserSettings
from app.models.user import User

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-pass-123"

DEMO_QUESTIONS = (
    {
        "module": "言语理解",
        "stem": "推进基层治理现代化，既要完善制度，也要让群众真正参与其中。这段文字强调的是：",
        "options": [
            {"label": "A", "content": "基层治理只需要制度建设"},
            {"label": "B", "content": "制度建设与群众参与应协同推进"},
            {"label": "C", "content": "群众参与可以替代制度建设"},
            {"label": "D", "content": "基层治理的重点是技术升级"},
        ],
        "user_answer": "A",
        "correct_answer": "B",
        "knowledge_points": ["主旨概括", "并列关系"],
        "error_reason": "理解错",
        "mastery_status": "未掌握",
        "explanation": "文段用“既要……也要……”并列制度与参与，主旨应同时概括两方面。",
    },
    {
        "module": "言语理解",
        "stem": "在公共服务中，只有准确识别群众需求，政策才能真正做到____。填入最恰当的一项是：",
        "options": [
            {"label": "A", "content": "一劳永逸"},
            {"label": "B", "content": "面面俱到"},
            {"label": "C", "content": "有的放矢"},
            {"label": "D", "content": "按部就班"},
        ],
        "user_answer": "B",
        "correct_answer": "C",
        "knowledge_points": ["逻辑填空", "语境对应"],
        "error_reason": "粗心",
        "mastery_status": "复习中",
        "explanation": "“准确识别需求”对应有针对性地采取措施，即“有的放矢”。",
    },
    {
        "module": "数量关系",
        "stem": "甲乙两地相距 180 千米，一辆汽车以每小时 60 千米行驶，需要多少小时到达？",
        "options": [
            {"label": "A", "content": "2"},
            {"label": "B", "content": "2.5"},
            {"label": "C", "content": "3"},
            {"label": "D", "content": "4"},
        ],
        "user_answer": "D",
        "correct_answer": "C",
        "knowledge_points": ["行程问题", "路程速度时间"],
        "error_reason": "不会",
        "mastery_status": "未掌握",
        "explanation": "时间=路程÷速度=180÷60=3 小时。",
    },
    {
        "module": "数量关系",
        "stem": "一项工程甲单独完成需要 12 天，乙单独完成需要 18 天，两人合作 4 天后完成了工程的几分之几？",
        "options": [
            {"label": "A", "content": "1/3"},
            {"label": "B", "content": "5/9"},
            {"label": "C", "content": "2/3"},
            {"label": "D", "content": "7/9"},
        ],
        "user_answer": "A",
        "correct_answer": "B",
        "knowledge_points": ["工程问题", "效率叠加"],
        "error_reason": "计算错",
        "mastery_status": "复习中",
        "explanation": "合作效率为 1/12+1/18=5/36，4 天完成 5/9。",
    },
    {
        "module": "判断推理",
        "stem": "某图形序列中黑点数量依次为 1、2、4、7，下一个图形黑点数量最可能是：",
        "options": [
            {"label": "A", "content": "8"},
            {"label": "B", "content": "9"},
            {"label": "C", "content": "10"},
            {"label": "D", "content": "11"},
        ],
        "user_answer": "C",
        "correct_answer": "D",
        "knowledge_points": ["图形推理", "数量规律"],
        "error_reason": "时间不够",
        "mastery_status": "未掌握",
        "explanation": "相邻差依次为 1、2、3，下一差值为 4，因此为 11。",
    },
    {
        "module": "判断推理",
        "stem": "行政决策是行政机关为实现行政目标制定行动方案的活动。下列属于行政决策的是：",
        "options": [
            {"label": "A", "content": "市政府制定城市更新三年行动方案"},
            {"label": "B", "content": "企业制定年度销售计划"},
            {"label": "C", "content": "居民协商小区停车规则"},
            {"label": "D", "content": "学校社团安排周末活动"},
        ],
        "user_answer": "B",
        "correct_answer": "A",
        "knowledge_points": ["定义判断", "主体限定"],
        "error_reason": "理解错",
        "mastery_status": "已掌握",
        "explanation": "定义主体必须是行政机关，只有市政府符合。",
    },
    {
        "module": "资料分析",
        "stem": "某地区上年产值为 200 亿元，本年为 230 亿元，同比增长率为：",
        "options": [
            {"label": "A", "content": "10%"},
            {"label": "B", "content": "15%"},
            {"label": "C", "content": "20%"},
            {"label": "D", "content": "30%"},
        ],
        "user_answer": "C",
        "correct_answer": "B",
        "knowledge_points": ["增长率", "基期量"],
        "error_reason": "计算错",
        "mastery_status": "复习中",
        "explanation": "增长率=(230-200)÷200=15%。",
    },
    {
        "module": "资料分析",
        "stem": "某部门共有 500 人，其中专业技术人员 125 人，专业技术人员占比为：",
        "options": [
            {"label": "A", "content": "25%"},
            {"label": "B", "content": "30%"},
            {"label": "C", "content": "35%"},
            {"label": "D", "content": "40%"},
        ],
        "user_answer": "D",
        "correct_answer": "A",
        "knowledge_points": ["比重", "现期比重"],
        "error_reason": "粗心",
        "mastery_status": "已掌握",
        "explanation": "125÷500=25%。",
    },
    {
        "module": "常识判断",
        "stem": "我国宪法规定，国家的一切权力属于：",
        "options": [
            {"label": "A", "content": "国务院"},
            {"label": "B", "content": "全国人民代表大会"},
            {"label": "C", "content": "人民"},
            {"label": "D", "content": "国家机关"},
        ],
        "user_answer": "A",
        "correct_answer": "C",
        "knowledge_points": ["宪法", "国家权力归属"],
        "error_reason": "不会",
        "mastery_status": "未掌握",
        "explanation": "宪法第二条规定，中华人民共和国的一切权力属于人民。",
    },
    {
        "module": "常识判断",
        "stem": "下列现象主要由光的折射形成的是：",
        "options": [
            {"label": "A", "content": "平面镜成像"},
            {"label": "B", "content": "日食"},
            {"label": "C", "content": "树荫"},
            {"label": "D", "content": "水中的筷子看起来弯折"},
        ],
        "user_answer": "B",
        "correct_answer": "D",
        "knowledge_points": ["物理常识", "光的折射"],
        "error_reason": "时间不够",
        "mastery_status": "已掌握",
        "explanation": "光从水进入空气时传播方向改变，因此筷子看起来发生弯折。",
    },
)


def _stable_id(user_id: str, kind: str, index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"kaogong-demo:{user_id}:{kind}:{index}"))


async def seed_demo_data(session: AsyncSession) -> dict[str, int]:
    """Create or repair the deterministic demo account and sample dataset."""

    user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            settings=UserSettings(daily_review_limit=20),
        )
        session.add(user)
        await session.flush()
    elif await session.get(UserSettings, user.id) is None:
        session.add(UserSettings(user_id=user.id, daily_review_limit=20))
    if not verify_password(DEMO_PASSWORD, user.password_hash):
        user.password_hash = hash_password(DEMO_PASSWORD)

    now = datetime.now(timezone.utc)
    for index, fixture in enumerate(DEMO_QUESTIONS, start=1):
        question_id = _stable_id(user.id, "question", index)
        analysis_id = _stable_id(user.id, "analysis", index)
        question = await session.get(Question, question_id)
        if question is None:
            question = Question(
                id=question_id,
                user_id=user.id,
                exam_type="国考",
                module=fixture["module"],
                stem=fixture["stem"],
                options=fixture["options"],
                user_answer=fixture["user_answer"],
                correct_answer=fixture["correct_answer"],
                original_explanation=fixture["explanation"],
                source="演示题库",
                notes="这是可编辑的演示错题。",
                knowledge_points=fixture["knowledge_points"],
                error_reason=fixture["error_reason"],
                mastery_status=fixture["mastery_status"],
                analysis_status="已完成",
                current_analysis_id=analysis_id,
                created_at=now - timedelta(days=index - 1),
                updated_at=now - timedelta(days=index - 1),
            )
            session.add(question)

        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            analysis = Analysis(
                id=analysis_id,
                question_id=question_id,
                user_id=user.id,
                cause_analysis=f"本题主要错因是{fixture['error_reason']}，需要回到关键条件逐项核对。",
                knowledge_points=fixture["knowledge_points"],
                correct_approach=f"先识别{fixture['knowledge_points'][0]}，再根据题干条件排除干扰项。",
                study_advice="复盘时先独立重做，再用一句话记录判断依据，三天后再次检验。",
                suggested_error_reason=fixture["error_reason"],
                raw_response={
                    "cause_analysis": f"本题主要错因是{fixture['error_reason']}。",
                    "knowledge_points": fixture["knowledge_points"],
                    "correct_approach": f"运用{fixture['knowledge_points'][0]}完成判断。",
                    "study_advice": "独立重做并记录依据。",
                    "suggested_error_reason": fixture["error_reason"],
                },
                provider_name="demo",
                model_name="deterministic-demo-v1",
                is_demo=True,
                created_at=now - timedelta(days=max(index - 2, 0)),
            )
            session.add(analysis)

        question.analysis_status = "已完成"
        question.analysis_error_code = None
        question.current_analysis_id = analysis_id

        if index <= 6:
            review_id = _stable_id(user.id, "review", index)
            if await session.get(ReviewRecord, review_id) is None:
                session.add(
                    ReviewRecord(
                        id=review_id,
                        question_id=question_id,
                        user_id=user.id,
                        result_status=fixture["mastery_status"],
                        review_note="演示复习记录：已重新核对题干、答案与关键知识点。",
                        reviewed_at=now - timedelta(days=7 + index),
                    )
                )

    await session.commit()
    return {"questions": len(DEMO_QUESTIONS), "analyses": len(DEMO_QUESTIONS), "reviews": 6}


async def _main() -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            summary = await seed_demo_data(session)
    finally:
        await engine.dispose()
    print(
        "Demo data ready: "
        f"{DEMO_EMAIL} ({summary['questions']} questions, "
        f"{summary['analyses']} analyses, {summary['reviews']} reviews)"
    )


if __name__ == "__main__":
    asyncio.run(_main())
