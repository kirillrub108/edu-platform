<script setup lang="ts">
import { FileText, Volume2, Video, Sparkles } from 'lucide-vue-next'

// Pointer-driven 3D parallax. Rest pose is a gentle isometric tilt; moving the
// pointer over the scene nudges it. Disabled on coarse pointers (touch).
const tiltX = ref(7)
const tiltY = ref(-11)
let coarse = false

onMounted(() => {
  coarse = window.matchMedia?.('(pointer: coarse)').matches ?? false
})

const onMove = (e: PointerEvent) => {
  if (coarse) return
  const el = e.currentTarget as HTMLElement
  const r = el.getBoundingClientRect()
  const px = (e.clientX - r.left) / r.width - 0.5
  const py = (e.clientY - r.top) / r.height - 0.5
  tiltY.value = -11 + px * 16
  tiltX.value = 7 - py * 13
}

const onLeave = () => {
  tiltX.value = 7
  tiltY.value = -11
}

// Faux slide bullet widths and waveform bar heights — purely decorative.
const bullets = ['85%', '70%', '78%', '55%']
const bars = [40, 70, 95, 60, 85, 45, 75, 100, 55, 80, 35, 65]
</script>

<template>
  <section class="px-6 pb-8 lg:pb-12">
    <div
      class="scene mx-auto max-w-3xl"
      @pointermove="onMove"
      @pointerleave="onLeave"
    >
      <div
        class="scene-stage relative aspect-[16/10] sm:aspect-[16/9]"
        :style="{ transform: `rotateX(${tiltX}deg) rotateY(${tiltY}deg)` }"
      >
        <!-- under-glow -->
        <div
          class="pointer-events-none absolute inset-x-8 bottom-2 h-24 rounded-full bg-violet-500/30 blur-3xl"
          style="transform: translateZ(-60px)"
        ></div>

        <!-- main app window -->
        <div
          class="absolute inset-0 overflow-hidden rounded-2xl border border-violet-100 bg-white shadow-hero"
          style="transform: translateZ(0)"
        >
          <!-- window chrome -->
          <div class="flex items-center gap-2 border-b border-gray-100 bg-gray-50/80 px-4 py-2.5">
            <span class="h-2.5 w-2.5 rounded-full bg-rose-300"></span>
            <span class="h-2.5 w-2.5 rounded-full bg-amber-300"></span>
            <span class="h-2.5 w-2.5 rounded-full bg-emerald-300"></span>
            <div class="ml-3 flex-1">
              <div class="mx-auto w-44 rounded-md bg-white px-2 py-1 text-center text-[10px] text-gray-400 ring-1 ring-gray-100">
                edllm · lesson.mp4
              </div>
            </div>
          </div>

          <!-- slide preview -->
          <div class="grid h-[calc(100%-2.75rem)] grid-cols-[1.6fr_1fr] gap-3 p-4">
            <div class="relative overflow-hidden rounded-xl bg-gradient-to-br from-violet-600 via-purple-500 to-fuchsia-500 p-4 text-white">
              <div class="text-[11px] font-medium uppercase tracking-wider text-white/70">Лекция · слайд 07</div>
              <div class="mt-2 h-2.5 w-3/4 rounded-full bg-white/80"></div>
              <div class="mt-1.5 h-2.5 w-1/2 rounded-full bg-white/50"></div>
              <!-- play overlay -->
              <div class="absolute bottom-3 right-3 grid h-9 w-9 place-items-center rounded-full bg-white/90 text-violet-700 shadow-lg">
                <Video class="h-4 w-4" />
              </div>
            </div>
            <div class="space-y-2.5">
              <div v-for="(w, i) in bullets" :key="i" class="flex items-center gap-2">
                <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-violet-300"></span>
                <span class="h-2 rounded-full bg-gray-100" :style="{ width: w }"></span>
              </div>
              <div class="mt-3 flex items-end gap-1.5">
                <span class="w-2 rounded-t bg-violet-200" style="height: 28px"></span>
                <span class="w-2 rounded-t bg-violet-300" style="height: 44px"></span>
                <span class="w-2 rounded-t bg-violet-400" style="height: 22px"></span>
                <span class="w-2 rounded-t bg-violet-500" style="height: 52px"></span>
                <span class="w-2 rounded-t bg-violet-300" style="height: 36px"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- floating chip: source PPTX -->
        <div class="float-layer absolute -left-5 top-6 hidden lg:block" style="transform: translateZ(70px)">
          <div class="chip animate-float">
            <div class="grid h-7 w-7 place-items-center rounded-lg bg-violet-100 text-violet-700">
              <FileText class="h-3.5 w-3.5" />
            </div>
            <div class="leading-tight">
              <div class="text-[11px] font-semibold text-gray-900">slides.pptx</div>
              <div class="text-[10px] text-gray-400">24 слайда</div>
            </div>
          </div>
        </div>

        <!-- floating chip: SpeechKit waveform -->
        <div class="float-layer absolute -left-8 bottom-4 hidden lg:block" style="transform: translateZ(115px)">
          <div class="chip animate-float-slow" style="animation-delay: -2s">
            <div class="grid h-7 w-7 place-items-center rounded-lg bg-red-50 text-red-500">
              <Volume2 class="h-3.5 w-3.5" />
            </div>
            <div class="flex items-end gap-[3px]">
              <span
                v-for="(h, i) in bars"
                :key="i"
                class="wave-bar w-[3px] rounded-full bg-gradient-to-t from-violet-500 to-fuchsia-400"
                :style="{ height: h * 0.22 + 'px', animationDelay: i * 90 + 'ms' }"
              ></span>
            </div>
            <div class="text-[10px] font-medium text-gray-500">SpeechKit</div>
          </div>
        </div>

        <!-- floating chip: render output -->
        <div class="float-layer absolute -right-4 top-10 hidden lg:block" style="transform: translateZ(95px)">
          <div class="chip animate-float-slow" style="animation-delay: -4s">
            <div class="grid h-7 w-7 place-items-center rounded-lg bg-emerald-50 text-emerald-600">
              <Sparkles class="h-3.5 w-3.5" />
            </div>
            <div class="leading-tight">
              <div class="text-[11px] font-semibold text-gray-900">MP4 · 1080p</div>
              <div class="text-[10px] text-emerald-600">готово · 2:14</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.scene {
  perspective: 1400px;
}
.scene-stage {
  transform-style: preserve-3d;
  transition: transform 0.4s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: transform;
}
.float-layer {
  transform-style: preserve-3d;
}
.chip {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  border-radius: 0.875rem;
  border: 1px solid rgb(237 233 254);
  background: rgba(255, 255, 255, 0.85);
  padding: 0.5rem 0.75rem;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 28px rgba(109, 40, 217, 0.16);
}

@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-12px); }
}
.animate-float { animation: float 6s ease-in-out infinite; }
.animate-float-slow { animation: float 8s ease-in-out infinite; }

@keyframes wave {
  0%, 100% { transform: scaleY(0.4); }
  50% { transform: scaleY(1); }
}
.wave-bar {
  transform-origin: bottom;
  animation: wave 1.1s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .scene-stage { transition: none; }
  .animate-float,
  .animate-float-slow,
  .wave-bar { animation: none; }
}
</style>
