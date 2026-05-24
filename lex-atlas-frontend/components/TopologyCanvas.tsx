"use client";

/**
 * TopologyCanvas — the hero visualization on the landing page.
 *
 * Ported directly from the Stitch mockup's vanilla-JS canvas. ~45 floating
 * nodes connecting when proximate, with KHO (court) nodes pulsing in
 * terracotta. Matches the architectural-grid aesthetic — the canvas draws
 * its own 32px grid as the base layer so it blends with the page bg.
 *
 * Performance: requestAnimationFrame loop, O(n²) edge check (acceptable at
 * n=45). Cleans up RAF on unmount.
 */

import { useEffect, useRef } from "react";

interface TopologyNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  type: "kho" | "finlex" | "vero";
}

interface TopologyCanvasProps {
  className?: string;
  /** Approximate node count. Default 45 matches Stitch. */
  nodeCount?: number;
  /** Max edge distance in px. Default 120. */
  connectionDistance?: number;
}

export function TopologyCanvas({
  className,
  nodeCount = 45,
  connectionDistance = 120,
}: TopologyCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;
    let nodes: TopologyNode[] = [];

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = parent.clientWidth * dpr;
      canvas.height = parent.clientHeight * dpr;
      canvas.style.width = `${parent.clientWidth}px`;
      canvas.style.height = `${parent.clientHeight}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const initNodes = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      nodes = [];
      for (let i = 0; i < nodeCount; i++) {
        const r = Math.random();
        nodes.push({
          x: Math.random() * w,
          y: Math.random() * h,
          vx: (Math.random() - 0.5) * 0.5,
          vy: (Math.random() - 0.5) * 0.5,
          radius: r > 0.8 ? 4 : 2,
          type: r > 0.9 ? "kho" : r > 0.5 ? "finlex" : "vero",
        });
      }
    };

    const draw = () => {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);

      // Draw architectural grid on the canvas
      ctx.strokeStyle = "rgba(196, 199, 199, 0.1)";
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 32) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += 32) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      // Update positions + draw connections (O(n²) is fine at n=45)
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > w) n.vx *= -1;
        if (n.y < 0 || n.y > h) n.vy *= -1;

        for (let j = i + 1; j < nodes.length; j++) {
          const m = nodes[j];
          const dx = n.x - m.x;
          const dy = n.y - m.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < connectionDistance) {
            ctx.beginPath();
            ctx.moveTo(n.x, n.y);
            ctx.lineTo(m.x, m.y);
            ctx.strokeStyle = `rgba(26, 28, 27, ${1 - dist / connectionDistance})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      // Draw nodes
      for (const n of nodes) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        if (n.type === "kho") {
          ctx.fillStyle = "#944921"; // terracotta — KHO highlights
          ctx.shadowBlur = 10;
          ctx.shadowColor = "#944921";
        } else {
          ctx.fillStyle = "#1a1c1b"; // charcoal — finlex/vero default
          ctx.shadowBlur = 0;
        }
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      rafId = requestAnimationFrame(draw);
    };

    resize();
    initNodes();
    draw();

    const onResize = () => {
      resize();
      initNodes();
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      cancelAnimationFrame(rafId);
    };
  }, [nodeCount, connectionDistance]);

  return (
    <canvas
      ref={canvasRef}
      className={"absolute inset-0 h-full w-full cursor-crosshair " + (className ?? "")}
      role="img"
      aria-label="Lex Atlas topology · animated knowledge graph"
    />
  );
}
