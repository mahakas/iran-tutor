export type TutorMode = "tutor" | "problem_solver" | "question_designer";

export type GradeOption = {
  number: number;
  title: string;
  has_major: boolean;
};

export type MajorOption = { code: string; title: string };
export type BookOption = {
  id: number;
  title: string;
  grade_number: number;
  major_code: string;
  status: string;
};

export type Source = {
  book_id?: number;
  book_title?: string;
  chapter_number?: number | null;
  chapter_title?: string | null;
  pdf_page_index?: number | null;
  printed_page_number?: number | null;
  citation?: string;
  score?: number;
};

export type UsageInfo = {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_toman: number;
  tokens_remaining: number;
};

export type StudentUser = {
  id: string;
  phone_number: string;
  masked_phone: string;
  full_name: string | null;
  plan_code: "trial" | "normal" | "pro" | "vip" | string;
  plan_title: string;
  tokens_total: number;
  tokens_remaining: number;
  tokens_used_total: number;
  tokens_used_today: number;
  used_value_toman: number;
  plan_started_at: string | null;
  plan_expires_at: string | null;
  days_remaining: number;
  is_expired: boolean;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string | null;
};

export type PlanItem = {
  id: number;
  code: string;
  name: string;
  description: string;
  price_toman: number;
  token_quota: number;
  duration_days: number;
  effective_toman_per_1k: number;
  is_active: boolean;
  sort_order: number;
};

export type PublicPlansPayload = {
  plans: PlanItem[];
  token_price_per_1k_toman: number;
  starter_tokens: number;
  starter_duration_days: number;
  payment_mode: string;
};

export type TokenUsageLogItem = {
  id: string;
  action: string;
  book_id: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_toman: number;
  created_at: string | null;
};

export type PaymentTransactionItem = {
  id: string;
  plan_code: string;
  plan_name: string;
  amount_toman: number;
  tokens_granted: number;
  duration_days: number;
  provider: string;
  status: string;
  ref_id: string | null;
  created_at: string | null;
  paid_at: string | null;
};

export type TutorResponse = {
  answer: string;
  sources: Source[];
  recognized_question?: string;
  transcript?: string;
  uncertain_parts?: string[];
  usage?: UsageInfo;
};

export type ExamQuestion = {
  id: string;
  prompt: string;
  choices: Record<"A" | "B" | "C" | "D", string>;
  points: number;
  source: Source;
};

export type Exam = {
  id: string;
  title: string;
  book_id: number;
  grade_number: number;
  major_code: string;
  exam_type: "konkoor" | "final";
  time_limit_seconds: number;
  expires_at: string;
  status?: "active" | "submitted" | "expired";
  questions: ExamQuestion[];
  report_card?: ExamReport;
  submitted_answers?: Record<string, string | null>;
  usage?: UsageInfo;
};

export type ExamSummary = {
  id: string;
  title: string;
  book_id: number;
  book_title: string | null;
  grade_number: number;
  major_code: string;
  exam_type: "konkoor" | "final";
  status: "active" | "submitted" | "expired";
  question_count: number;
  time_limit_seconds: number;
  expires_at: string;
  created_at: string | null;
  submitted_at: string | null;
  report_summary: {
    score: number;
    scale: "percent" | "out_of_20";
    correct: number;
    wrong: number;
    unanswered: number;
    total_questions: number;
  } | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  attachment?: string;
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  book_id: number;
  book_title: string | null;
  grade_number: number;
  major_code: string;
  mode: TutorMode;
  message_count: number;
  created_at: string | null;
  updated_at: string | null;
};

export type ChatSessionDetail = ChatSessionSummary & {
  messages: ChatMessage[];
};

export type ExamQuestionResult = {
  id: string;
  answer: string | null;
  correct: boolean;
  correct_option: string;
  explanation: string;
  source: Source;
};

export type ExamReport = {
  score: number;
  scale: "percent" | "out_of_20";
  correct: number;
  wrong: number;
  unanswered: number;
  total_questions: number;
  by_question: ExamQuestionResult[];
};
