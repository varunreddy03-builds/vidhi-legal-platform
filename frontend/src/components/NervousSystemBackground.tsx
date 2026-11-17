import { useEffect, useRef } from "react";

type Intensity = "ambient" | "active";

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  glow: number;
}
interface Star {
  x: number;
  y: number;
  r: number;
  phase: number;
}
interface Pulse {
  a: number;
  b: number;
  t: number;
}

/**
 * Two blended canvas layers: starfield (passive cosmos) behind a neuron field
 * (ambient system activity). Never a claim about model reasoning; never interactive.
 */
export default function NervousSystemBackground({
  intensity = "ambient",
}: {
  intensity?: Intensity;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const intensityRef = useRef<Intensity>(intensity);
  intensityRef.current = intensity;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const mobile = window.innerWidth < 768;
    // Phones, like people who asked for less motion, get one carefully composed still frame: a moving canvas behind every screen made touches feel slow on modest phones.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches || mobile;
    const still = reduced;
    const dpr = Math.min(window.devicePixelRatio || 1, mobile ? 1.5 : 2);

    let w = 0;
    let h = 0;
    let nodes: Node[] = [];
    let stars: Star[] = [];
    const pulses: Pulse[] = [];
    let raf = 0;
    let running = true;
    let frame = 0;
    let flash = 0;
    let nextOverload = 9000 + Math.random() * 6000;

    const nodeCount = mobile ? 55 : 95;
    const starCount = mobile ? 180 : 320;
    const linkDist = mobile ? 110 : 150;

    function resize() {
      const c = canvas as HTMLCanvasElement;
      w = c.clientWidth;
      h = c.clientHeight;
      c.width = Math.floor(w * dpr);
      c.height = Math.floor(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      build();
    }

    function build() {
      nodes = [];
      for (let i = 0; i < nodeCount; i++) {
        // Edge-weighted placement keeps the centre sparse so legal content stays dominant.
        const edgeBias = Math.random() ** 0.55;
        const angle = Math.random() * Math.PI * 2;
        const cx = w / 2 + Math.cos(angle) * edgeBias * (w / 2) * 1.05;
        const cy = h / 2 + Math.sin(angle) * edgeBias * (h / 2) * 1.05;
        nodes.push({
          x: Math.min(Math.max(cx, 0), w),
          y: Math.min(Math.max(cy, 0), h),
          vx: (Math.random() - 0.5) * 0.06,
          vy: (Math.random() - 0.5) * 0.06,
          glow: 0,
        });
      }
      stars = [];
      for (let i = 0; i < starCount; i++) {
        stars.push({
          x: Math.random() * w,
          y: Math.random() * h,
          r: Math.random() * 0.9 + 0.2,
          phase: Math.random() * Math.PI * 2,
        });
      }
    }

    function draw(dt: number) {
      const active = intensityRef.current === "active";
      ctx!.clearRect(0, 0, w, h);

      // Layer 2 — starfield (slow parallax, neutral).
      for (const s of stars) {
        const tw = reduced ? 0.5 : 0.4 + 0.3 * Math.sin(frame / 120 + s.phase);
        ctx!.globalAlpha = tw * 0.55;
        ctx!.fillStyle = "#FFFFFF";
        ctx!.beginPath();
        ctx!.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx!.fill();
        if (!reduced) {
          s.x += 0.008;
          if (s.x > w) s.x = 0;
        }
      }
      ctx!.globalAlpha = 1;

      // Layer 1 — neuron field.
      if (!reduced) {
        for (const n of nodes) {
          n.x += n.vx * (active ? 1.7 : 1);
          n.y += n.vy * (active ? 1.7 : 1);
          if (n.x < 0 || n.x > w) n.vx *= -1;
          if (n.y < 0 || n.y > h) n.vy *= -1;
          n.glow *= 0.965;
        }
      }

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i];
          const b = nodes[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > linkDist * linkDist) continue;
          const d = Math.sqrt(d2);
          const alpha = (1 - d / linkDist) * (active ? 0.3 : 0.18);
          ctx!.strokeStyle = `rgba(91,140,255,${alpha.toFixed(3)})`;
          ctx!.lineWidth = 0.6;
          ctx!.beginPath();
          ctx!.moveTo(a.x, a.y);
          ctx!.lineTo(b.x, b.y);
          ctx!.stroke();
        }
      }

      for (const n of nodes) {
        const g = Math.min(n.glow, 1);
        ctx!.fillStyle = g > 0.05 ? "#C8A96B" : "#5B8CFF";
        ctx!.globalAlpha = 0.35 + g * 0.6;
        ctx!.beginPath();
        ctx!.arc(n.x, n.y, 1.2 + g * 1.6, 0, Math.PI * 2);
        ctx!.fill();
      }
      ctx!.globalAlpha = 1;

      if (!reduced) {
        // Firing: pulses travel along a connection and illuminate the destination.
        const fireChance = active ? 0.09 : 0.025;
        if (Math.random() < fireChance && nodes.length > 2) {
          const a = Math.floor(Math.random() * nodes.length);
          let b = Math.floor(Math.random() * nodes.length);
          if (b === a) b = (b + 1) % nodes.length;
          pulses.push({ a, b, t: 0 });
        }
        for (let i = pulses.length - 1; i >= 0; i--) {
          const p = pulses[i];
          p.t += active ? 0.035 : 0.02;
          const a = nodes[p.a];
          const b = nodes[p.b];
          if (!a || !b || p.t >= 1) {
            if (b) b.glow = 1;
            pulses.splice(i, 1);
            continue;
          }
          const x = a.x + (b.x - a.x) * p.t;
          const y = a.y + (b.y - a.y) * p.t;
          ctx!.fillStyle = "#C8A96B";
          ctx!.globalAlpha = 0.85 * (1 - p.t);
          ctx!.beginPath();
          ctx!.arc(x, y, 1.6, 0, Math.PI * 2);
          ctx!.fill();
          ctx!.globalAlpha = 1;
        }

        // Rare cluster overload: brighten, snap, scatter, flash, settle.
        nextOverload -= dt;
        if (nextOverload <= 0) {
          nextOverload = 8000 + Math.random() * 9000;
          flash = 1;
          const seed = nodes[Math.floor(Math.random() * nodes.length)];
          for (const n of nodes) {
            if (Math.hypot(n.x - seed.x, n.y - seed.y) < linkDist * 1.4) {
              n.glow = 1;
              n.vx += (n.x - seed.x) * 0.004;
              n.vy += (n.y - seed.y) * 0.004;
            }
          }
        }
        if (flash > 0) {
          ctx!.fillStyle = `rgba(240,166,58,${(flash * 0.05).toFixed(3)})`;
          ctx!.fillRect(0, 0, w, h);
          flash -= 0.04;
        }
      }
      frame++;
    }

    let last = performance.now();
    function loop(now: number) {
      const dt = now - last;
      last = now;
      draw(dt);
      if (still) return; // one carefully composed static frame
      raf = requestAnimationFrame(loop);
    }

    function onVisibility() {
      if (document.hidden && running) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!document.hidden && !running && !still) {
        running = true;
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    }

    resize();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    raf = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <div
      aria-hidden="true"
      data-testid="nervous-system-background"
      data-intensity={intensity}
      className="pointer-events-none fixed inset-0 z-0"
      style={{ background: "radial-gradient(120% 90% at 50% 0%, #0E1424 0%, #070A12 70%)" }}
    >
      <canvas ref={ref} className="absolute inset-0 h-full w-full" />
    </div>
  );
}
