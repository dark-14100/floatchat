"use client";

/**
 * BackgroundIllustration — Fixed ocean atmosphere layer.
 *
 * Design spec §5 colours:
 *   Light — bg-base #F5F0E8, ocean #A8D8E8 / #87CEEB / #4BAAC8
 *   Dark  — bg-base #0B1220, purple #2A1F3D, silver #B8C8D8
 */

export default function BackgroundIllustration() {
  return (
    <>
      <style jsx global>{`
        @keyframes wave-drift-1 {
          0%, 100% { transform: translateX(0) translateY(0); }
          50% { transform: translateX(-25px) translateY(-5px); }
        }
        @keyframes wave-drift-2 {
          0%, 100% { transform: translateX(0) translateY(0); }
          50% { transform: translateX(18px) translateY(-7px); }
        }
        @keyframes wave-drift-3 {
          0%, 100% { transform: translateX(0) translateY(0); }
          50% { transform: translateX(-12px) translateY(-4px); }
        }
        @keyframes moon-glow {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.85; transform: scale(1.03); }
        }
        @keyframes twinkle-1 {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 1; }
        }
        @keyframes twinkle-2 {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 0.2; }
        }
        @keyframes shimmer-water {
          0%, 100% { opacity: 0.3; }
          50% { opacity: 0.7; }
        }
        @keyframes sand-shimmer {
          0%, 100% { opacity: 0.25; }
          50% { opacity: 0.42; }
        }
      `}</style>

      <div
        className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
        aria-hidden="true"
      >
        {/* ═══════════════════════════════════════════════════════
            LIGHT MODE — Tropical Coast
            ═══════════════════════════════════════════════════════ */}
        <div className="absolute inset-0 dark:hidden">

          {/* Solid sand base — fills entire panel, no white anywhere */}
          <div
            className="absolute inset-0"
            style={{ background: "#EDE8DD" }}
          />

          {/* Sky / sun radial glow — top-right (spec §5.2) */}
          <div
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 65% 45% at 82% 8%, rgba(255,255,255,0.6) 0%, transparent 70%)",
            }}
          />

          {/* Warm sand gradient — stronger golden tones upper half */}
          <div
            className="absolute inset-0"
            style={{
              background: `
                linear-gradient(170deg,
                  rgba(212,201,181,0.60) 0%,
                  rgba(201,169,110,0.40) 35%,
                  rgba(190,170,130,0.25) 55%,
                  rgba(180,200,210,0.15) 70%,
                  rgba(168,216,232,0.20) 100%
                )
              `,
            }}
          />

          {/* Golden sand pools */}
          <div
            className="absolute inset-0"
            style={{
              background: `
                radial-gradient(ellipse 45% 35% at 25% 30%, rgba(201,169,110,0.30) 0%, transparent 70%),
                radial-gradient(ellipse 40% 30% at 70% 40%, rgba(201,169,110,0.24) 0%, transparent 65%),
                radial-gradient(ellipse 55% 40% at 50% 20%, rgba(212,201,181,0.26) 0%, transparent 60%),
                radial-gradient(ellipse 35% 25% at 15% 50%, rgba(201,169,110,0.22) 0%, transparent 70%)
              `,
            }}
          />

          {/* Sand grain texture layer 1 */}
          <div
            className="absolute inset-0"
            style={{
              bottom: "45%",
              opacity: 0.35,
              backgroundImage: `
                radial-gradient(circle 1px at 8px 6px, #B8A080 1px, transparent 1px),
                radial-gradient(circle 0.8px at 22px 18px, #C9A96E 0.8px, transparent 0.8px),
                radial-gradient(circle 1.2px at 38px 11px, #A09070 1.2px, transparent 1.2px),
                radial-gradient(circle 0.6px at 14px 30px, #D4C9B5 0.6px, transparent 0.6px),
                radial-gradient(circle 1px at 45px 35px, #B8A080 1px, transparent 1px),
                radial-gradient(circle 0.7px at 30px 4px, #C9A96E 0.7px, transparent 0.7px),
                radial-gradient(circle 0.9px at 5px 22px, #A09070 0.9px, transparent 0.9px)
              `,
              backgroundSize: "52px 40px",
            }}
          />

          {/* Sand grain texture layer 2 */}
          <div
            className="absolute inset-0"
            style={{
              bottom: "45%",
              opacity: 0.30,
              backgroundImage: `
                radial-gradient(circle 0.8px at 12px 14px, #A09070 0.8px, transparent 0.8px),
                radial-gradient(circle 1.1px at 33px 7px, #D4C9B5 1.1px, transparent 1.1px),
                radial-gradient(circle 0.6px at 20px 28px, #C9A96E 0.6px, transparent 0.6px),
                radial-gradient(circle 1px at 42px 22px, #B8A080 1px, transparent 1px),
                radial-gradient(circle 0.5px at 7px 35px, #C9A96E 0.5px, transparent 0.5px)
              `,
              backgroundSize: "48px 38px",
            }}
          />

          {/* Golden sand shimmer — pulsating sparkle */}
          <div
            className="absolute inset-0"
            style={{
              animation: "sand-shimmer 4s ease-in-out infinite",
              backgroundImage: `
                radial-gradient(circle 1.5px at 100px 80px, rgba(201,169,110,0.5) 0.5px, transparent 1.5px),
                radial-gradient(circle 1px at 300px 150px, rgba(201,169,110,0.4) 0.5px, transparent 1px),
                radial-gradient(circle 1.2px at 550px 60px, rgba(201,169,110,0.45) 0.5px, transparent 1.2px),
                radial-gradient(circle 0.8px at 750px 200px, rgba(201,169,110,0.35) 0.4px, transparent 0.8px),
                radial-gradient(circle 1.3px at 950px 120px, rgba(201,169,110,0.4) 0.5px, transparent 1.3px),
                radial-gradient(circle 1px at 1150px 180px, rgba(201,169,110,0.45) 0.5px, transparent 1px),
                radial-gradient(circle 0.9px at 200px 250px, rgba(201,169,110,0.35) 0.4px, transparent 0.9px),
                radial-gradient(circle 1.1px at 450px 300px, rgba(201,169,110,0.4) 0.5px, transparent 1.1px)
              `,
              backgroundSize: "1440px 380px",
            }}
          />

          {/* Horizon line — warm-to-cool gradient */}
          <div
            className="absolute left-0 w-full"
            style={{
              bottom: "43%",
              height: "100px",
              background:
                "linear-gradient(to bottom, transparent 0%, rgba(168,216,232,0.10) 40%, rgba(135,206,235,0.15) 100%)",
            }}
          />

          {/* Ocean waves — animated, bottom ~40% */}
          <svg
            className="absolute bottom-0 left-0 w-full"
            viewBox="0 0 1440 560"
            preserveAspectRatio="none"
            style={{ height: "45vh" }}
          >
            <g style={{ animation: "wave-drift-1 8s ease-in-out infinite" }}>
              <path
                d="M0,100 C180,70 360,140 540,115 C720,90 900,55 1080,80 C1260,105 1380,130 1440,120 L1440,560 L0,560 Z"
                fill="#A8D8E8"
                opacity="0.45"
              />
            </g>
            <g style={{ animation: "wave-drift-2 10s ease-in-out infinite" }}>
              <path
                d="M0,200 C200,175 400,240 600,210 C800,180 1000,155 1200,185 C1340,200 1420,220 1440,215 L1440,560 L0,560 Z"
                fill="#87CEEB"
                opacity="0.50"
              />
            </g>
            <g style={{ animation: "wave-drift-3 7s ease-in-out infinite" }}>
              <path
                d="M0,300 C160,275 340,330 520,305 C700,280 880,258 1060,280 C1200,295 1360,320 1440,310 L1440,560 L0,560 Z"
                fill="#4BAAC8"
                opacity="0.55"
              />
            </g>
            <g style={{ animation: "wave-drift-1 12s ease-in-out infinite" }}>
              <path
                d="M0,400 C240,385 480,420 720,400 C960,380 1200,395 1440,390 L1440,560 L0,560 Z"
                fill="#1B7A9E"
                opacity="0.55"
              />
            </g>
            <path
              d="M0,480 C300,470 600,495 900,478 C1100,466 1300,480 1440,475 L1440,560 L0,560 Z"
              fill="#0D4F6B"
              opacity="0.55"
            />
          </svg>

          {/* Foam shimmer along shoreline */}
          <div
            className="absolute bottom-0 left-0 w-full"
            style={{
              height: "12vh",
              background:
                "linear-gradient(to top, rgba(253,250,244,0.3) 0%, transparent 100%)",
            }}
          />
        </div>

        {/* ═══════════════════════════════════════════════════════
            DARK MODE — Moonlit Shore
            ═══════════════════════════════════════════════════════ */}
        <div className="absolute inset-0 hidden dark:block">

          {/* Darken the sky — deepen the base */}
          <div
            className="absolute inset-0"
            style={{
              background: "rgba(5,8,16,0.45)",
            }}
          />

          {/* Deep purple wash from bottom-left (spec §5.3) */}
          <div
            className="absolute inset-0"
            style={{
              background: `
                radial-gradient(ellipse 90% 70% at 15% 95%, rgba(42,31,61,0.40) 0%, transparent 60%),
                radial-gradient(ellipse 60% 50% at 85% 80%, rgba(42,31,61,0.25) 0%, transparent 55%)
              `,
            }}
          />



          {/* Stars — layer 1, bright */}
          <div
            className="absolute inset-0"
            style={{
              animation: "twinkle-1 3s ease-in-out infinite",
              backgroundImage: `
                radial-gradient(circle 2px at 80px 40px, rgba(184,200,216,0.9) 1px, transparent 2px),
                radial-gradient(circle 1.5px at 250px 90px, rgba(184,200,216,0.7) 0.75px, transparent 1.5px),
                radial-gradient(circle 2px at 500px 55px, rgba(184,200,216,0.85) 1px, transparent 2px),
                radial-gradient(circle 1.8px at 720px 35px, rgba(184,200,216,0.8) 0.9px, transparent 1.8px),
                radial-gradient(circle 1.5px at 950px 75px, rgba(184,200,216,0.75) 0.75px, transparent 1.5px),
                radial-gradient(circle 2px at 1150px 50px, rgba(184,200,216,0.85) 1px, transparent 2px),
                radial-gradient(circle 1.6px at 1350px 30px, rgba(184,200,216,0.7) 0.8px, transparent 1.6px)
              `,
              backgroundSize: "1440px 120px",
            }}
          />
          {/* Stars — layer 2, dimmer */}
          <div
            className="absolute inset-0"
            style={{
              animation: "twinkle-2 4s ease-in-out infinite",
              backgroundImage: `
                radial-gradient(circle 1.2px at 170px 130px, rgba(184,200,216,0.6) 0.6px, transparent 1.2px),
                radial-gradient(circle 1px at 400px 160px, rgba(184,200,216,0.5) 0.5px, transparent 1px),
                radial-gradient(circle 1.4px at 600px 110px, rgba(184,200,216,0.55) 0.7px, transparent 1.4px),
                radial-gradient(circle 1px at 830px 145px, rgba(184,200,216,0.45) 0.5px, transparent 1px),
                radial-gradient(circle 1.3px at 1060px 125px, rgba(184,200,216,0.55) 0.65px, transparent 1.3px),
                radial-gradient(circle 1.1px at 1250px 155px, rgba(184,200,216,0.5) 0.55px, transparent 1.1px),
                radial-gradient(circle 0.8px at 50px 180px, rgba(184,200,216,0.4) 0.4px, transparent 0.8px),
                radial-gradient(circle 1px at 320px 200px, rgba(184,200,216,0.45) 0.5px, transparent 1px),
                radial-gradient(circle 0.9px at 680px 190px, rgba(184,200,216,0.4) 0.45px, transparent 0.9px),
                radial-gradient(circle 1.2px at 1000px 210px, rgba(184,200,216,0.5) 0.6px, transparent 1.2px)
              `,
              backgroundSize: "1440px 240px",
            }}
          />

          {/* Dark ocean waves — bottom ~40% */}
          <svg
            className="absolute bottom-0 left-0 w-full"
            viewBox="0 0 1440 560"
            preserveAspectRatio="none"
            style={{ height: "45vh" }}
          >
            <g style={{ animation: "wave-drift-1 9s ease-in-out infinite" }}>
              <path
                d="M0,100 C180,70 360,140 540,115 C720,90 900,55 1080,80 C1260,105 1380,130 1440,120 L1440,560 L0,560 Z"
                fill="#1A2840"
                opacity="0.30"
              />
            </g>
            <g style={{ animation: "wave-drift-2 11s ease-in-out infinite" }}>
              <path
                d="M0,200 C200,175 400,240 600,210 C800,180 1000,155 1200,185 C1340,200 1420,220 1440,215 L1440,560 L0,560 Z"
                fill="#162238"
                opacity="0.40"
              />
            </g>
            <g style={{ animation: "wave-drift-3 8s ease-in-out infinite" }}>
              <path
                d="M0,300 C160,275 340,330 520,305 C700,280 880,258 1060,280 C1200,295 1360,320 1440,310 L1440,560 L0,560 Z"
                fill="#111C30"
                opacity="0.50"
              />
            </g>
            <g style={{ animation: "wave-drift-1 13s ease-in-out infinite" }}>
              <path
                d="M0,400 C240,385 480,420 720,400 C960,380 1200,395 1440,390 L1440,560 L0,560 Z"
                fill="#0D1628"
                opacity="0.55"
              />
            </g>
            <path
              d="M0,480 C300,470 600,495 900,478 C1100,466 1300,480 1440,475 L1440,560 L0,560 Z"
              fill="#090F1E"
              opacity="0.60"
            />
          </svg>

          {/* Moonlit water shimmer streaks */}
          <div
            className="absolute left-0 w-full"
            style={{
              bottom: "20%",
              height: "80px",
              background: `
                linear-gradient(90deg,
                  transparent 5%,
                  rgba(184,200,216,0.04) 15%,
                  rgba(184,200,216,0.08) 30%,
                  transparent 42%,
                  rgba(123,157,184,0.06) 55%,
                  rgba(184,200,216,0.07) 70%,
                  transparent 85%
                )
              `,
              animation: "shimmer-water 5s ease-in-out infinite",
            }}
          />
        </div>
      </div>
    </>
  );
}
