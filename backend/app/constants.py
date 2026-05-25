# TTS
SILERO_MAX_CHARS: int = 800  # conservative limit: Silero returns 500 on very long inputs

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
