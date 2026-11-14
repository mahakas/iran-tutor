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

export type TutorResponse = {
  answer: string;
  sources: Source[];
  recognized_question?: string;
  transcript?: string;
  uncertain_parts?: string[];
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
