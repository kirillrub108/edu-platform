<!-- Layered decorative background (design_handoff_edllm). Fixed, non-interactive,
     aria-hidden. Aurora blobs + conic rays + dot-grid + cursor glow live in `.bg`;
     film grain is its own fixed layer. Motion (drift/rays/parallax/cursor) is
     wired by useLandingMotion and fully disabled under prefers-reduced-motion. -->
<template>
  <div>
    <div class="bg" aria-hidden="true">
      <div class="rays" data-parallax="0.06"></div>
      <div class="aurora a1" data-parallax="0.12"></div>
      <div class="aurora a2" data-parallax="0.18"></div>
      <div class="aurora a3" data-parallax="0.08"></div>
      <div class="aurora a4" data-parallax="0.14"></div>
      <div class="grid-tex"></div>
      <div class="cursor-glow"></div>
    </div>
    <div class="grain" aria-hidden="true"></div>
  </div>
</template>
