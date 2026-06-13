<template>
  <div class="min-h-screen bg-brand-surface text-gray-900 font-sans antialiased">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
    <VerifyEmailModal />
  </div>
</template>

<style>
/* App-wide neutral palette, retinted to match the Edllm landing: a low-chroma
   violet ramp (ink / ink-soft / muted / line) over a lavender bg, replacing
   Tailwind's neutral grays everywhere `gray-*` is used. These channels feed
   tailwind.config.ts's gray scale via rgb(var(--c-gray-N) / <alpha-value>), so
   values tweak here and hot-reload (src/ is bind-mounted) — no image rebuild.
   Anchors match the landing exactly (900=ink #20193a, 600≈ink-soft, 200=line
   #e5e2f0, 50=bg #faf8ff); 500 is nudged ~3% darker than the literal muted so
   the heavily-used body/caption text clears WCAG AA (4.5:1) on white, lavender,
   and gray-50. The accent (violet/indigo/purple/fuchsia) stays on Tailwind
   defaults — it already equals the landing's --accent / --accent-deep /
   --accent-fuchsia. The landing's own .ldg-scoped oklch tokens are unaffected. */
:root {
  --c-gray-50: 250 248 255;
  --c-gray-100: 241 238 249;
  --c-gray-200: 229 226 240;
  --c-gray-300: 205 201 219;
  --c-gray-400: 147 142 166;
  --c-gray-500: 114 110 134;
  --c-gray-600: 74 67 101;
  --c-gray-700: 56 47 84;
  --c-gray-800: 42 35 69;
  --c-gray-900: 32 25 58;

  /* Accent (violet) realigned to the landing's exact indigo hue 282 (oklch).
     Tailwind's default violet sits at ~hue 292 (more purple); these are the
     landing's --accent / --accent-bright / --accent-soft anchors, with a smooth
     monotonic-lightness ramp drifting toward hue 270 (--accent-deep) in the dark
     stops. Components: "L C H" — tailwind.config wraps them as
     oklch(var(--c-violet-N) / <alpha-value>) so opacity modifiers keep working.
     indigo / purple / fuchsia stay on Tailwind defaults — they already span the
     deep-indigo→violet→fuchsia gradient range with this violet. */
  --c-violet-50: 0.975 0.013 282;
  --c-violet-100: 0.92 0.045 282;
  --c-violet-200: 0.865 0.085 282;
  --c-violet-300: 0.79 0.13 282;
  --c-violet-400: 0.71 0.18 282;
  --c-violet-500: 0.655 0.225 282;
  --c-violet-600: 0.63 0.235 282;
  --c-violet-700: 0.55 0.215 282;
  --c-violet-800: 0.4 0.19 270;
  --c-violet-900: 0.34 0.16 268;

  /* Brand gradient anchors — the landing's --accent-deep / --accent-bright
     (oklch, hue 270→282). Single source for every brand surface (logo mark,
     primary CTAs, accent cards) via the .bg-brand-gradient utility below. */
  --brand-deep: oklch(0.46 0.19 270);
  --brand-bright: oklch(0.63 0.235 282);
}

/* Brand gradient — logo mark, primary CTAs, accent surfaces. Mirrors the
   landing's .btn-primary / .brand .mark fill so every screen shares one ramp. */
.bg-brand-gradient {
  background-image: linear-gradient(120deg, var(--brand-deep), var(--brand-bright));
}

/* Soft lavender page wash — mirrors the landing's fixed .bg radial, pinned to the
   viewport so dashboards/auth share the landing backdrop instead of flat gray. */
.bg-brand-surface {
  background-color: oklch(0.985 0.01 282);
  background-image: radial-gradient(125% 80% at 50% -10%, oklch(0.97 0.03 282) 0%, transparent 55%);
  background-repeat: no-repeat;
  background-attachment: fixed;
}
</style>
