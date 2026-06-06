# TTS
SILERO_MAX_CHARS: int = 800  # conservative limit: Silero returns 500 on very long inputs
TTS_CACHE_TTL_DAYS: int = 7

# Slide rendering
SLIDE_DPI: int = 150  # indistinguishable from 300 DPI on 1080p, 4× smaller PNGs

# Upload limits
MAX_SCRIPT_BYTES: int = 10 * 1024 * 1024  # 10 MB

# Worker concurrency
TTS_WORKERS: int = 4     # matches NUMBER_OF_THREADS in silero-tts docker-compose service
ENCODE_WORKERS: int = 3  # concurrent FFmpeg processes; leaves headroom for LO and TTS threads

# Quiz
QUIZ_PASS_THRESHOLD: float = 0.6  # default for new quizzes; per-quiz override in Quiz.pass_threshold
QUIZ_NUM_QUESTIONS: int = 5
QUIZ_NUM_OPTIONS: int = 4
QUIZ_MIN_QUESTIONS: int = 1
QUIZ_MAX_QUESTIONS: int = 20
QUIZ_DEFAULT_WEIGHT: float = 1.0
QUIZ_LLM_TEMPERATURE: float = 0.2
QUIZ_LLM_OPEN_MAX_TOKENS: int = 400
QUIZ_MAX_MATERIAL_CHARS: int = 12000
# Parallel LLM-IO grading of open answers — bounded by upstream LLM throughput.
QUIZ_GRADING_WORKERS: int = 4

# Billing / credits
# Per-operation credit cost. Keys are matched by callers via CREDIT_WEIGHTS["..."].
CREDIT_WEIGHTS: dict[str, int] = {
    "lesson_generate": 10,  # PPTX→видео полный цикл (vision+LLM+TTS+FFmpeg)
    "lesson_regen": 8,      # повторная генерация (кеш слайдов есть, но LLM+TTS+FFmpeg)
    "vision_analyze": 5,    # vision-анализ PPTX → SlideText (без видео)
    "slide_regen": 1,       # регенерация одного слайда через vision LLM
    "quiz_grade": 0,        # AI-проверка квиза — бесплатно (маркетинговый аргумент)
}

# Tariff plans. Keys match CreditPlan enum values.
PLAN_CONFIGS: dict[str, dict[str, int]] = {
    "free":    {"monthly_allowance": 0,   "onetime_credits": 50, "price_rub": 0},
    "starter": {"monthly_allowance": 30,  "onetime_credits": 0,  "price_rub": 490},
    "pro":     {"monthly_allowance": 120, "onetime_credits": 0,  "price_rub": 1490},
    "school":  {"monthly_allowance": 500, "onetime_credits": 0,  "price_rub": 4990},
}

TOPUP_PACKS: list[dict[str, int]] = [
    {"credits": 50,  "price_rub": 750},
    {"credits": 200, "price_rub": 2600},
]

CREDIT_CARRYOVER_RATIO: float = 0.5  # до 50% месячного объёма переносится на след. месяц

# Default question-type distribution for quiz generation.
# Keys match the type strings used in generate_quiz_v2 / _parse_payload_v2.
# Fractions must sum to 1.0; short_answer absorbs rounding remainders.
QUIZ_TYPE_DISTRIBUTION: dict[str, float] = {
    "single_choice": 0.50,
    "multiple_choice": 0.30,
    "true_false": 0.10,
    "short_answer": 0.10,
}
# Below this count the distribution is skipped and all questions are single_choice.
QUIZ_MIN_FOR_DISTRIBUTION: int = 4

# Access code generation
ACCESS_CODE_LENGTH: int = 6
# No I, O, 1, 0 — visually ambiguous characters excluded.
ACCESS_CODE_ALPHABET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ACCESS_CODE_MAX_RETRIES: int = 10
