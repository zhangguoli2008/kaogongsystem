from __future__ import annotations

from app.schemas.analysis import AnalysisInput, AnalysisResult
from app.schemas.analytics import AnalyticsAdviceInput, AnalyticsAdviceResult
from app.schemas.question import ErrorReason, ExamModule, QuestionOption
from app.schemas.upload import OcrResult


_ANALYSIS_BY_MODULE: dict[ExamModule, tuple[list[str], str, str, str, ErrorReason]] = {
    ExamModule.VERBAL: (
        ["主旨概括", "论证结构"],
        "作答时没有先定位材料的核心观点，容易被片段信息干扰。",
        "先概括各段要点，再比较选项与中心论点的匹配程度。",
        "每次练习后用一句话复述材料主旨，并记录干扰项类型。",
        ErrorReason.MISUNDERSTOOD,
    ),
    ExamModule.QUANT: (
        ["数量关系", "方程建模"],
        "计算前没有把题干条件转化为清晰的数量关系。",
        "列出未知量与等量关系，优先使用代入或排除验证。",
        "复习常见方程模型，并限时完成同类基础题。",
        ErrorReason.CALCULATION,
    ),
    ExamModule.REASONING: (
        ["判断推理", "逻辑关系"],
        "没有完整识别题干中的逻辑关系，导致依据不足。",
        "标记题干条件与结论，再按题型选择对应的推理规则。",
        "整理高频逻辑关系，练习时先写出判断依据。",
        ErrorReason.MISUNDERSTOOD,
    ),
    ExamModule.DATA: (
        ["资料分析", "增长率"],
        "对增长率的计算口径不够熟悉，容易把增长量与增长率混淆。",
        "确认基期与现期后，按增长率公式计算并代回选项核验。",
        "复习增长率、比重和倍数公式，每天限时练习两道资料题。",
        ErrorReason.CALCULATION,
    ),
    ExamModule.KNOWLEDGE: (
        ["常识判断", "知识体系"],
        "相关知识点的框架不完整，难以排除相近表述。",
        "按领域回忆关键概念，再用题干限定条件逐项排除。",
        "将易混知识点制成对比卡片，并在复习时主动回忆。",
        ErrorReason.UNKNOWN,
    ),
}


class DemoProvider:
    """Deterministic offline provider used by local demos and tests."""

    async def ocr(
        self,
        image_bytes: bytes,
        mime_type: str,
        request_id: str | None = None,
    ) -> OcrResult:
        del image_bytes, mime_type, request_id
        return OcrResult(
            stem="某地区2024年第一季度生产总值为120亿元，第二季度比第一季度增长10%，第二季度生产总值为多少亿元？",
            options=[
                QuestionOption(label="A", content="120亿元"),
                QuestionOption(label="B", content="126亿元"),
                QuestionOption(label="C", content="132亿元"),
                QuestionOption(label="D", content="144亿元"),
            ],
            user_answer="B",
            correct_answer="C",
            original_explanation="第二季度生产总值=120×(1+10%)=132亿元。",
            raw_text="某地区2024年第一季度生产总值为120亿元，第二季度比第一季度增长10%。",
            is_demo=True,
        )

    async def analyze(
        self, payload: AnalysisInput, request_id: str | None = None
    ) -> AnalysisResult:
        del request_id
        (
            knowledge_points,
            cause_analysis,
            correct_approach,
            study_advice,
            suggested_error_reason,
        ) = _ANALYSIS_BY_MODULE[payload.module]
        answers_match = payload.user_answer.strip() == payload.correct_answer.strip()
        has_explanation = bool(payload.original_explanation.strip())
        if answers_match:
            cause_analysis = "本次作答与正确答案一致，需要通过复盘巩固可复用的判断步骤。"
        if has_explanation:
            correct_approach = f"{correct_approach} 再对照已有解析核验每一步。"
        else:
            correct_approach = f"{correct_approach} 题目未提供原解析，完成后自行写出核验过程。"
        raw_response = {
            "cause_analysis": cause_analysis,
            "knowledge_points": knowledge_points,
            "correct_approach": correct_approach,
            "study_advice": study_advice,
            "suggested_error_reason": suggested_error_reason.value,
        }
        return AnalysisResult(
            cause_analysis=cause_analysis,
            knowledge_points=knowledge_points,
            correct_approach=correct_approach,
            study_advice=study_advice,
            suggested_error_reason=suggested_error_reason,
            raw_response=raw_response,
            provider_name="demo",
            model_name=None,
            is_demo=True,
        )

    async def advise(
        self, payload: AnalyticsAdviceInput, request_id: str | None = None
    ) -> AnalyticsAdviceResult:
        del request_id
        if payload.total_questions == 0 or not payload.module_distribution:
            advice = "先录入错题，系统会根据你的数据生成学习建议。"
        else:
            module = payload.module_distribution[0].label
            knowledge_point = (
                payload.knowledge_point_ranking[0].label
                if payload.knowledge_point_ranking
                else "核心知识点"
            )
            advice = (
                f"演示建议：优先复习{module}中的{knowledge_point}，"
                "再用一组同类题检验掌握情况。"
            )
        return AnalyticsAdviceResult(
            advice=advice,
            provider_name="demo",
            model_name=None,
            is_demo=True,
        )
