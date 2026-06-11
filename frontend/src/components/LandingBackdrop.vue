<script setup lang="ts">
// Decorative, non-interactive landing backdrop. Layered for depth and craft
// rather than a single flat wash: a graph-paper grid + fine dots + film grain +
// concentric rings behind the hero + a few deliberately placed ambient lights.
// A few layers drift/rotate very slowly (reduced-motion gated); aria-hidden and
// pointer-transparent throughout.
const noiseBg =
  `url("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")`
</script>

<template>
  <div aria-hidden="true" class="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
    <!-- base wash — keeps a faint lavender tint at the bottom instead of fading
         to flat white, so the long page reads "airy" rather than empty -->
    <div class="absolute inset-0 bg-gradient-to-b from-violet-50/70 via-white to-violet-50/40"></div>

    <!-- ambient light — soft, deliberately placed (key / accent / fill).
         The `glow-drift*` classes add a very slow drift/pulse; the whole set is
         frozen under prefers-reduced-motion (see <style> below). Positions are
         %-based so they track the key sections (hero / metrics / pricing / CTA)
         regardless of exact page height. -->
    <!-- hero zone -->
    <div class="glow-drift absolute -top-40 -left-32 h-[520px] w-[520px] rounded-full bg-violet-300/25 blur-[120px]"></div>
    <div class="absolute right-[-10%] top-[34%] h-[440px] w-[440px] rounded-full bg-amber-200/20 blur-[130px]"></div>
    <!-- metrics banner aura -->
    <div class="glow-drift-slow absolute left-[-8%] top-[55%] h-[420px] w-[480px] rounded-full bg-fuchsia-200/20 blur-[140px]"></div>
    <div class="absolute bottom-[-6%] left-1/4 h-[420px] w-[560px] rounded-full bg-indigo-200/20 blur-[140px]"></div>
    <!-- pricing zone -->
    <div class="glow-drift absolute right-[-6%] top-[74%] h-[460px] w-[460px] rounded-full bg-violet-300/18 blur-[150px]" style="animation-delay: -7s"></div>
    <!-- final CTA zone -->
    <div class="glow-drift-slow absolute left-1/2 top-[90%] h-[420px] w-[620px] -translate-x-1/2 rounded-full bg-indigo-300/18 blur-[150px]" style="animation-delay: -11s"></div>

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
      class="rings absolute left-1/2 top-[2%] h-[720px] w-[720px] -translate-x-1/2 text-violet-300/30"
      viewBox="0 0 720 720"
      fill="none"
    >
      <circle cx="360" cy="360" r="130" stroke="currentColor" stroke-width="1" />
      <circle cx="360" cy="360" r="215" stroke="currentColor" stroke-width="1" stroke-dasharray="2 9" />
      <circle cx="360" cy="360" r="310" stroke="currentColor" stroke-width="1" />
    </svg>

    <!-- slow low-saturation aurora sweep behind the hero for atmospheric depth -->
    <div
      class="aurora absolute left-1/2 top-[1%] h-[640px] w-[840px] -translate-x-1/2 rounded-[50%] opacity-25 blur-[90px]"
      style="background: conic-gradient(from 200deg at 50% 50%, rgba(167,139,250,0), rgba(129,140,248,0.32), rgba(217,70,239,0.16), rgba(167,139,250,0));"
    ></div>

    <!-- film grain -->
    <div
      class="absolute inset-0 opacity-[0.04] mix-blend-multiply"
      :style="{ backgroundImage: noiseBg, backgroundSize: '140px 140px' }"
    ></div>

    <!-- keep the top legible under the hero text -->
    <div class="absolute inset-x-0 top-0 h-36 bg-gradient-to-b from-white/70 to-transparent"></div>
  </div>
</template>

<style scoped>
/* Very slow, low-amplitude drift + breathing on the ambient glows. Cheap
   (transform/opacity only) and decorative — fully disabled under
   prefers-reduced-motion so motion is never forced. */
.glow-drift,
.glow-drift-slow {
  will-change: transform, opacity;
}
.glow-drift {
  animation: glow-drift 18s ease-in-out infinite;
}
.glow-drift-slow {
  animation: glow-drift 26s ease-in-out infinite;
}
@keyframes glow-drift {
  0%,
  100% {
    transform: translate3d(0, 0, 0) scale(1);
    opacity: 0.85;
  }
  50% {
    transform: translate3d(5%, -6%, 0) scale(1.12);
    opacity: 1;
  }
}
/* The CTA glow is horizontally centered via -translate-x-1/2; preserve that
   offset while it drifts so it doesn't jump left. */
.glow-drift-slow.-translate-x-1\/2 {
  animation-name: glow-drift-centered;
}
@keyframes glow-drift-centered {
  0%,
  100% {
    transform: translate3d(-50%, 0, 0) scale(1);
    opacity: 0.85;
  }
  50% {
    transform: translate3d(-45%, -6%, 0) scale(1.12);
    opacity: 1;
  }
}

/* Slow aurora rotation + barely-there ring drift add a living atmosphere layer.
   Both keyframes carry the -50% centering so the elements stay put while moving. */
.aurora {
  will-change: transform;
  animation: aurora-spin 70s linear infinite;
}
@keyframes aurora-spin {
  0% { transform: translateX(-50%) rotate(0deg); }
  100% { transform: translateX(-50%) rotate(360deg); }
}
.rings {
  will-change: transform;
  transform-origin: 50% 50%;
  animation: rings-drift 52s ease-in-out infinite;
}
@keyframes rings-drift {
  0%, 100% { transform: translateX(-50%) rotate(0deg) scale(1); }
  50% { transform: translateX(-50%) rotate(6deg) scale(1.03); }
}
@media (prefers-reduced-motion: reduce) {
  .glow-drift,
  .glow-drift-slow,
  .aurora,
  .rings {
    animation: none;
  }
}
</style>
