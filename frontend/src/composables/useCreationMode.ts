export const CreationMode = {
  PRESENTATION_AND_TEXT: 'presentation_and_text',
  PRESENTATION_AUTO: 'presentation_auto',
  TEXT_ONLY: 'text_only',
  PROMPT: 'prompt',
} as const

export type CreationModeValue = typeof CreationMode[keyof typeof CreationMode]

export interface CreationModeCard {
  value: CreationModeValue
  title: string
  subtitle: string
  description: string
  emoji: string
  available: boolean
}

export const CREATION_MODE_CARDS: CreationModeCard[] = [
  {
    value: CreationMode.PRESENTATION_AND_TEXT,
    title: 'Презентация + Текст',
    subtitle: 'Загрузите слайды и текст',
    description: 'Загрузите PPTX и вставьте текст доклада. LLM разобьёт его по слайдам и улучшит формулировки.',
    emoji: '📊📝',
    available: true,
  },
  {
    value: CreationMode.PRESENTATION_AUTO,
    title: 'Презентация (автотекст)',
    subtitle: 'LLM сама напишет текст',
    description: 'Загрузите PPTX. Vision LLM проанализирует слайды и сгенерирует текст озвучки автоматически.',
    emoji: '📊✨',
    available: true,
  },
  {
    value: CreationMode.TEXT_ONLY,
    title: 'Только текст',
    subtitle: 'Из текста — слайды + видео',
    description: 'Дайте текст лекции, LLM нарежет его на слайды, оформит и сгенерирует видео.',
    emoji: '📝',
    available: false,
  },
  {
    value: CreationMode.PROMPT,
    title: 'Промпт',
    subtitle: 'Опишите тему — получите курс',
    description: 'Кратко опишите тему, LLM подготовит структуру, слайды, текст и озвучку.',
    emoji: '💬',
    available: false,
  },
]

export const useCreationMode = () => {
  const selected = useState<CreationModeValue | null>('creation.mode', () => null)
  const setMode = (mode: CreationModeValue) => {
    selected.value = mode
  }
  return { selected, setMode }
}
