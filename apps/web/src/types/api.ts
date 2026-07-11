export interface User {
  id: string;
  email: string;
  created_at?: string;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  field_errors?: Record<string, string[]> | null;
  request_id?: string;
}

export const examTypes = ["国考", "省考", "事业编", "其他"] as const;
export type ExamType = (typeof examTypes)[number];

export const examModules = ["言语理解", "数量关系", "判断推理", "资料分析", "常识判断"] as const;
export type ExamModule = (typeof examModules)[number];

export const errorReasons = ["粗心", "不会", "理解错", "计算错", "时间不够"] as const;
export type ErrorReason = (typeof errorReasons)[number];

export const masteryStatuses = ["未掌握", "复习中", "已掌握"] as const;
export type MasteryStatus = (typeof masteryStatuses)[number];

export const analysisStatuses = ["未分析", "分析中", "已完成", "失败"] as const;
export type AnalysisStatus = (typeof analysisStatuses)[number];

export interface QuestionOption {
  label: string;
  content: string;
}

export interface Analysis {
  id: string;
  question_id: string;
  user_id: string;
  cause_analysis: string;
  knowledge_points: string[];
  correct_approach: string;
  study_advice: string;
  suggested_error_reason: ErrorReason | null;
  raw_response: Record<string, unknown>;
  provider_name: string;
  model_name: string | null;
  is_demo: boolean;
  created_at: string;
}

export interface QuestionInput {
  exam_type: ExamType;
  module: ExamModule;
  stem: string;
  options: QuestionOption[];
  user_answer: string;
  correct_answer: string;
  original_explanation?: string | null;
  source?: string | null;
  notes?: string | null;
  image_path?: string | null;
  ocr_raw_text?: string | null;
  knowledge_points: string[];
  error_reason?: ErrorReason | null;
  mastery_status: MasteryStatus;
  analysis_status?: AnalysisStatus;
  tags?: string[];
}

export interface Question extends Omit<
  QuestionInput,
  | "analysis_status"
  | "original_explanation"
  | "source"
  | "notes"
  | "image_path"
  | "ocr_raw_text"
  | "error_reason"
  | "tags"
> {
  id: string;
  user_id: string;
  original_explanation: string | null;
  source: string | null;
  notes: string | null;
  image_path: string | null;
  ocr_raw_text: string | null;
  error_reason: ErrorReason | null;
  tags: string[];
  analysis_status: AnalysisStatus;
  current_analysis_id: string | null;
  current_analysis: Analysis | null;
  analysis_error_code: string | null;
  created_at: string;
  updated_at: string;
}

export interface QuestionPage {
  items: Question[];
  page: number;
  page_size: number;
  total: number;
}

export interface Upload {
  id: string;
  original_name: string;
  storage_name: string;
  mime_type: string;
  size_bytes: number;
  created_at: string;
}

export interface OcrResult {
  stem: string;
  options: QuestionOption[];
  user_answer: string;
  correct_answer: string;
  original_explanation: string;
  raw_text: string;
  is_demo: boolean;
}

export interface BulkResult {
  updated?: number;
  deleted?: number;
  not_found: string[];
}

export interface ReviewRecord {
  id: string;
  question_id: string;
  user_id: string;
  result_status: MasteryStatus;
  review_note: string | null;
  reviewed_at: string;
}

export interface ReviewRecordPage {
  items: ReviewRecord[];
  page: number;
  page_size: number;
  total: number;
}

export interface TodayReviewResponse {
  daily_review_limit: 10 | 20 | 30 | 50;
  pending: Question[];
  completed: ReviewRecord[];
  completed_count: number;
  total: number;
}

export interface CountByLabel {
  label: string;
  count: number;
}

export interface TrendPoint {
  date: string;
  count: number;
}

export interface AnalyticsSummary {
  total_questions: number;
  module_distribution: CountByLabel[];
  knowledge_point_ranking: CountByLabel[];
  error_reason_distribution: CountByLabel[];
  mastery_distribution: CountByLabel[];
  trend_7d: TrendPoint[];
  trend_30d: TrendPoint[];
  ai_summary: string;
  is_demo: boolean;
}

export interface AnalyticsAdviceResult {
  advice: string;
  provider_name: string;
  model_name: string | null;
  is_demo: boolean;
}

export interface DashboardResponse {
  today_review: TodayReviewResponse;
  current_question: Question | null;
  recent_questions: Question[];
  weak_modules: CountByLabel[];
  trend_7d: TrendPoint[];
  ai_advice: string;
  provider_mode: "auto" | "demo" | "live" | string;
}
