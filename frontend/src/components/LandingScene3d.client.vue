<script setup lang="ts">
import type * as ThreeNS from 'three'

// Product motif: a lecture slide (cool / violet) sitting above an audio
// waveform (warm / amber) — the PPTX→narrated-video idea in one object. Cool =
// the visual slide, warm = the voice. Three.js is imported lazily inside
// onMounted so it never lands in the initial bundle, and every GPU resource is
// disposed on unmount. The parent only mounts this on capable desktops; if the
// WebGL context still fails, we emit `fail` so it can fall back to the CSS scene.

const emit = defineEmits<{ fail: [] }>()

const host = ref<HTMLDivElement | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const ready = ref(false)

let THREE!: typeof ThreeNS
let renderer: ThreeNS.WebGLRenderer | null = null
let raf = 0
let running = false
let inView = true
let started = 0

const disposables: { dispose: () => void }[] = []
let resizeObs: ResizeObserver | null = null
let viewObs: IntersectionObserver | null = null

// Pointer parallax target (normalised −0.5..0.5), lerped toward in the loop.
let targetX = 0
let targetY = 0

function drawSlideTexture(): HTMLCanvasElement {
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 624
  const x = c.getContext('2d')
  if (!x) return c
  const r = (px: number, py: number, w: number, h: number, rad: number | number[]) => {
    x.beginPath()
    x.roundRect(px, py, w, h, rad)
  }

  // card
  r(28, 28, 968, 568, 34)
  x.fillStyle = '#ffffff'
  x.fill()
  x.lineWidth = 2
  x.strokeStyle = '#ede9fe'
  x.stroke()

  // header band (top corners only, square against the body)
  r(28, 28, 968, 120, [34, 34, 0, 0])
  x.fillStyle = '#6d28d9'
  x.fill()
  x.fillStyle = 'rgba(255,255,255,0.92)'
  r(64, 70, 360, 22, 11)
  x.fill()
  for (let i = 0; i < 3; i++) {
    x.beginPath()
    x.arc(900 + i * 28, 88, 8, 0, Math.PI * 2)
    x.fillStyle = ['#fbbf24', '#f472b6', '#a78bfa'][i]
    x.fill()
  }

  // left visual block
  r(64, 196, 420, 348, 22)
  const g = x.createLinearGradient(64, 196, 484, 544)
  g.addColorStop(0, '#7c3aed')
  g.addColorStop(1, '#4f46e5')
  x.fillStyle = g
  x.fill()

  // right bullet lines
  const widths = [400, 330, 380, 300]
  widths.forEach((w, i) => {
    r(528, 214 + i * 60, w, 20, 10)
    x.fillStyle = i === 0 ? '#a78bfa' : '#e5e7eb'
    x.fill()
  })

  // amber play badge (links to the waveform)
  x.beginPath()
  x.arc(900, 500, 52, 0, Math.PI * 2)
  x.fillStyle = '#f59e0b'
  x.fill()
  x.beginPath()
  x.moveTo(884, 474)
  x.lineTo(884, 526)
  x.lineTo(928, 500)
  x.closePath()
  x.fillStyle = '#ffffff'
  x.fill()

  return c
}

function init() {
  const el = host.value
  const cv = canvas.value
  if (!el || !cv) return

  const width = el.clientWidth
  const height = el.clientHeight

  try {
    renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, alpha: true })
  } catch {
    emit('fail')
    return
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(width, height, false)
  renderer.outputColorSpace = THREE.SRGBColorSpace

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(34, width / height, 0.1, 100)
  camera.position.set(0, 0, 5.4)

  const root = new THREE.Group()
  root.rotation.x = -0.04
  scene.add(root)

  // lighting
  scene.add(new THREE.AmbientLight(0xffffff, 0.85))
  const dir = new THREE.DirectionalLight(0xffffff, 0.7)
  dir.position.set(3, 4, 5)
  scene.add(dir)
  const rim = new THREE.PointLight(0xa855f7, 0.6, 40)
  rim.position.set(-3, 1, 2)
  scene.add(rim)

  // soft glow anchored behind the slide (not a free-floating blob)
  const glowMat = new THREE.MeshBasicMaterial({
    color: 0x7c3aed,
    transparent: true,
    opacity: 0.22,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  })
  const glowGeo = new THREE.PlaneGeometry(4.1, 2.9)
  const glow = new THREE.Mesh(glowGeo, glowMat)
  glow.position.set(0, 0.28, -0.4)
  root.add(glow)
  disposables.push(glowGeo, glowMat)

  // slide
  const tex = new THREE.CanvasTexture(drawSlideTexture())
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = renderer.capabilities.getMaxAnisotropy()
  const slideMat = new THREE.MeshStandardMaterial({
    map: tex,
    transparent: true,
    roughness: 0.62,
    metalness: 0.05,
    side: THREE.DoubleSide,
  })
  const slideGeo = new THREE.PlaneGeometry(3.2, 1.95)
  const slide = new THREE.Mesh(slideGeo, slideMat)
  slide.position.set(0, 0.28, 0)
  root.add(slide)
  disposables.push(tex, slideMat, slideGeo)

  // audio waveform
  const COUNT = 32
  const span = 2.8
  const step = span / COUNT
  const barGeo = new THREE.BoxGeometry(0.05, 1, 0.05)
  const barMat = new THREE.MeshStandardMaterial({
    color: 0xfbbf24,
    emissive: 0xf59e0b,
    emissiveIntensity: 0.45,
    roughness: 0.4,
    metalness: 0.1,
  })
  const bars = new THREE.InstancedMesh(barGeo, barMat, COUNT)
  bars.position.set(0, -0.92, 0.18)
  root.add(bars)
  disposables.push(barGeo, barMat, bars)
  const dummy = new THREE.Object3D()
  // taller in the centre, like a real envelope
  const envelope = (i: number) => 0.45 + 0.55 * Math.sin((i / (COUNT - 1)) * Math.PI)

  const frame = (now: number) => {
    raf = requestAnimationFrame(frame)
    if (!renderer || !running || !inView) return
    const t = (now - started) / 1000

    for (let i = 0; i < COUNT; i++) {
      const h = (0.14 + (0.5 + 0.5 * Math.sin(t * 1.7 + i * 0.5)) * 0.5) * envelope(i)
      dummy.position.set(-span / 2 + i * step + step / 2, h / 2, 0)
      dummy.scale.set(1, h, 1)
      dummy.updateMatrix()
      bars.setMatrixAt(i, dummy.matrix)
    }
    bars.instanceMatrix.needsUpdate = true

    // pointer parallax + gentle idle sway
    const idle = Math.sin(t * 0.35) * 0.05
    root.rotation.y += (targetY + idle - root.rotation.y) * 0.05
    root.rotation.x += (-0.04 + targetX - root.rotation.x) * 0.05

    renderer.render(scene, camera)
    if (!ready.value) ready.value = true
  }

  started = performance.now()
  running = true
  raf = requestAnimationFrame(frame)

  // responsive
  resizeObs = new ResizeObserver(() => {
    if (!renderer) return
    const w = el.clientWidth
    const h = el.clientHeight
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
  })
  resizeObs.observe(el)

  // pause when off-screen / tab hidden
  viewObs = new IntersectionObserver(
    (entries) => {
      inView = entries[0]?.isIntersecting ?? true
    },
    { threshold: 0.05 },
  )
  viewObs.observe(el)
}

function onPointerMove(e: PointerEvent) {
  const el = host.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const nx = (e.clientX - r.left) / r.width - 0.5
  const ny = (e.clientY - r.top) / r.height - 0.5
  targetY = nx * 0.5
  targetX = -ny * 0.32
}

function onPointerLeave() {
  targetX = 0
  targetY = 0
}

function onVisibility() {
  running = document.visibilityState === 'visible'
}

onMounted(async () => {
  try {
    THREE = await import('three')
  } catch {
    emit('fail')
    return
  }
  init()
  host.value?.addEventListener('pointermove', onPointerMove)
  host.value?.addEventListener('pointerleave', onPointerLeave)
  document.addEventListener('visibilitychange', onVisibility)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(raf)
  running = false
  host.value?.removeEventListener('pointermove', onPointerMove)
  host.value?.removeEventListener('pointerleave', onPointerLeave)
  document.removeEventListener('visibilitychange', onVisibility)
  resizeObs?.disconnect()
  viewObs?.disconnect()
  for (const d of disposables) d.dispose()
  renderer?.dispose()
  renderer?.forceContextLoss()
  renderer = null
})
</script>

<template>
  <section class="px-6 pb-8 lg:pb-14">
    <div
      ref="host"
      aria-hidden="true"
      class="scene-3d relative mx-auto aspect-[16/10] w-full max-w-3xl sm:aspect-[16/9]"
    >
      <canvas
        ref="canvas"
        class="absolute inset-0 h-full w-full transition-opacity duration-700"
        :class="ready ? 'opacity-100' : 'opacity-0'"
      ></canvas>
    </div>
  </section>
</template>
