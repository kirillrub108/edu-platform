<script setup lang="ts">
// Decorative, non-interactive landing backdrop. Layered for depth and craft
// rather than a single flat wash: a graph-paper grid + fine dots + film grain +
// concentric rings behind the hero + a few deliberately placed ambient lights.
// Static (no animation), aria-hidden, and pointer-transparent.
const noiseBg =
  `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")`
</script>

<template>
  <div aria-hidden="true" class="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
    <!-- base wash -->
    <div class="absolute inset-0 bg-gradient-to-b from-violet-50/70 via-white to-white"></div>

    <!-- ambient light — soft, deliberately placed (key / accent / fill) -->
    <div class="absolute -top-40 -left-32 h-[520px] w-[520px] rounded-full bg-violet-300/25 blur-[120px]"></div>
    <div class="absolute right-[-10%] top-[34%] h-[440px] w-[440px] rounded-full bg-amber-200/20 blur-[130px]"></div>
    <div class="absolute bottom-[-6%] left-1/4 h-[420px] w-[560px] rounded-full bg-indigo-200/20 blur-[140px]"></div>

    <!-- graph-paper grid, faded toward the edges so it reads near the hero -->
    <div
      class="absolute inset-0 opacity-60"
      style="
        background-image:
          linear-gradient(rgba(91, 33, 182, 0.045) 1px, transparent 1px),
          linear-gradient(90deg, rgba(91, 33, 182, 0.045) 1px, transparent 1px);
        background-size: 96px 96px;
        -webkit-mask-image: radial-gradient(ellipse 100% 72% at 50% 0%, #000 38%, transparent 85%);
        mask-image: radial-gradient(ellipse 100% 72% at 50% 0%, #000 38%, transparent 85%);
      "
    ></div>

    <!-- fine dot grid -->
    <div
      class="absolute inset-0"
      style="background-image: radial-gradient(rgba(109, 40, 217, 0.07) 1px, transparent 1px); background-size: 26px 26px;"
    ></div>

    <!-- concentric rings behind the hero / 3D motif -->
    <svg
      class="absolute left-1/2 top-[2%] h-[720px] w-[720px] -translate-x-1/2 text-violet-300/30"
      viewBox="0 0 720 720"
      fill="none"
    >
      <circle cx="360" cy="360" r="130" stroke="currentColor" stroke-width="1" />
      <circle cx="360" cy="360" r="215" stroke="currentColor" stroke-width="1" stroke-dasharray="2 9" />
      <circle cx="360" cy="360" r="310" stroke="currentColor" stroke-width="1" />
    </svg>

    <!-- film grain -->
    <div
      class="absolute inset-0 opacity-[0.04] mix-blend-multiply"
      :style="{ backgroundImage: noiseBg, backgroundSize: '140px 140px' }"
    ></div>

    <!-- keep the top legible under the hero text -->
    <div class="absolute inset-x-0 top-0 h-36 bg-gradient-to-b from-white/70 to-transparent"></div>
  </div>
</template>
