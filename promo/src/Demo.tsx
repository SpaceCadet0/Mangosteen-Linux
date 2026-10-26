import React from "react";
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";

// The Linux demo, built on the Mac one (SpaceCadet0/Mangosteen, promo/), in the light theme: one scene per wheel. Start dragging a file,
// tap the key without letting go, drop the file on a segment. Icons, wheels and windows are the Linux app's own.

export const FPS = 30;
export const SCENE = 126; // 4.2 s per wheel
export const WIDTH = 1600;
export const HEIGHT = 1000;

const BRAND = "#671E38";
const FONT = "Inter, Cantarell, 'Noto Sans', 'DejaVu Sans', sans-serif";
const smooth = Easing.bezier(0.45, 0, 0.2, 1);
const pop = Easing.bezier(0.34, 1.56, 0.64, 1);

/** Clamped interpolation with an easing. */
const tween = (
  frame: number,
  range: [number, number],
  output: [number, number],
  easing = smooth,
) =>
  interpolate(frame, range, output, {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing,
  });

// MARK: - Scenes (the real wheels of the Linux app for these files)

type Segment = { title: string; icon: string };
type DemoFile = { name: string; icon: string };
type Scene = {
  kind: string;
  key: string;
  files: DemoFile[];
  segments: Segment[];
  target: number;
  start: number; // segment the pointer first enters
  result: "file" | "window" | "float";
};

const photo = (title: string): Segment => ({ title, icon: "g-image" });

const SCENES: Scene[] = [
  {
    kind: "Convert",
    key: "Shift",
    files: [{ name: "photo.heic", icon: "photo-thumb" }],
    segments: [
      photo("PNG"),
      photo("JPG"),
      photo("WebP"),
      photo("TIFF"),
      photo("AVIF"),
      photo("GIF"),
      { title: "PDF", icon: "g-document" },
    ],
    target: 1,
    start: 3,
    result: "file",
  },
  {
    kind: "Tools",
    key: "Ctrl",
    files: [{ name: "Mangosteen.mp4", icon: "video-thumb" }],
    segments: [
      { title: "Trim", icon: "g-trim" },
      { title: "Split", icon: "g-split" },
      { title: "Speed", icon: "g-speed" },
      { title: "Volume", icon: "g-volume" },
      { title: "Bleep", icon: "g-bleep" },
      { title: "Hide", icon: "g-hide" },
      { title: "Reframe", icon: "g-crop" },
      { title: "Compress", icon: "g-compress" },
      { title: "Frames", icon: "g-frames" },
    ],
    target: 0,
    start: 2,
    result: "window",
  },
  {
    kind: "Actions",
    key: "Alt",
    files: [
      { name: "photo.heic", icon: "photo-thumb" },
      { name: "song.mp3", icon: "song" },
    ],
    segments: [
      { title: "Float", icon: "g-float" },
      { title: "Copy", icon: "g-copy" },
      { title: "Move", icon: "g-move" },
      { title: "Path", icon: "g-path" },
      { title: "Terminal", icon: "g-terminal" },
    ],
    target: 0,
    start: 2,
    result: "float",
  },
];

// MARK: - The wheel (geometry and colours of the app's dark wheel)

const OUTER = 160;
const INNER = 64;
const WHEEL_SCALE = 1.55;

/** Point at `radius` and `angle` (radians, 0 at the top, clockwise). */
const polar = (cx: number, cy: number, radius: number, angle: number) => ({
  x: cx + radius * Math.sin(angle),
  y: cy - radius * Math.cos(angle),
});

/** A ring segment drawn inset by the corner radius; a round-joined stroke of the same colour rounds it off. */
const segmentPath = (cx: number, cy: number, start: number, end: number) => {
  const corner = 10;
  const gap = 6;
  const ro = OUTER - 4 - corner;
  const ri = INNER + 4 + corner;
  const inset = (r: number) => (gap / 2 + corner) / r;
  const steps = 18;
  const points: string[] = [];
  for (let i = 0; i <= steps; i++) {
    const a = start + inset(ro) + (end - inset(ro) - (start + inset(ro))) * (i / steps);
    const p = polar(cx, cy, ro, a);
    points.push(`${p.x.toFixed(2)},${p.y.toFixed(2)}`);
  }
  for (let i = steps; i >= 0; i--) {
    const a = start + inset(ri) + (end - inset(ri) - (start + inset(ri))) * (i / steps);
    const p = polar(cx, cy, ri, a);
    points.push(`${p.x.toFixed(2)},${p.y.toFixed(2)}`);
  }
  return `M${points.join("L")}Z`;
};

const Wheel: React.FC<{ scene: Scene; highlighted: number | null; fileCount: number }> = ({
  scene,
  highlighted,
  fileCount,
}) => {
  const size = (OUTER + 24) * 2;
  const c = size / 2;
  const segments = scene.segments;
  const span = (Math.PI * 2) / segments.length;
  const label = 0.5 * (INNER + OUTER);
  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ overflow: "visible" }}>
        <defs>
          <filter id="shadow" x="-30%" y="-30%" width="160%" height="160%">
            <feDropShadow dx="0" dy="6" stdDeviation="12" floodColor="#000" floodOpacity="0.22" />
          </filter>
        </defs>
        <circle cx={c} cy={c} r={OUTER} fill="rgba(239,239,241,0.97)" filter="url(#shadow)" />
        {segments.map((segment, index) => {
          const start = index * span - span / 2;
          const fill = highlighted === index ? BRAND : "#E3E3E6";
          return (
            <path
              key={segment.title}
              d={segmentPath(c, c, start, start + span)}
              fill={fill}
              stroke={fill}
              strokeWidth={20}
              strokeLinejoin="round"
            />
          );
        })}
        {segments.map((segment, index) => {
          const at = polar(c, c, label, index * span);
          return (
            <text
              key={segment.title}
              x={at.x}
              y={at.y + 14}
              textAnchor="middle"
              fill={highlighted === index ? "#fff" : "#1E1E21"}
              style={{ font: `700 11.5px ${FONT}` }}
            >
              {segment.title}
            </text>
          );
        })}
        <text x={c} y={c - 1} textAnchor="middle" fill="#1E1E21" style={{ font: `700 12.5px ${FONT}` }}>
          {scene.kind}
        </text>
        <text x={c} y={c + 15} textAnchor="middle" fill="#76767C" style={{ font: `400 11px ${FONT}` }}>
          {fileCount === 1 ? "1 file" : `${fileCount} files`}
        </text>
      </svg>
      {/* Segment icons as <Img>, which Remotion waits for on every frame; an SVG <image> could miss a frame. */}
      {segments.map((segment, index) => {
        const at = polar(c, c, label, index * span);
        return (
          <Img
            key={segment.title}
            src={staticFile(`icons/${highlighted === index ? segment.icon.replace("g-", "gw-") : segment.icon}.png`)}
            style={{
              position: "absolute",
              left: at.x - 12,
              top: at.y - 25,
              width: 24,
              height: 20,
              objectFit: "contain",
              opacity: highlighted === index ? 1 : 0.85,
            }}
          />
        );
      })}
    </div>
  );
};

// MARK: - Small parts

const Cursor: React.FC<{ pressed: boolean }> = ({ pressed }) => (
  <svg width={34} height={46} viewBox="0 0 17 23" style={{ scale: pressed ? "0.9" : "1", transformOrigin: "2px 2px" }}>
    <path
      d="M1.5 1.5 L1.5 18.5 L5.6 14.6 L8.4 21 L11.1 19.8 L8.4 13.6 L14 13.6 Z"
      fill="#000"
      stroke="#fff"
      strokeWidth={1.2}
      strokeLinejoin="round"
    />
  </svg>
);

const FileIcon: React.FC<{ file: DemoFile; selected: boolean; size?: number; showName?: boolean }> = ({
  file,
  selected,
  size = 128,
  showName = true,
}) => (
  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, width: size + 60 }}>
    <div style={{ padding: 6, borderRadius: 12, background: selected ? "rgba(0,0,0,0.07)" : "transparent" }}>
      <Img src={staticFile(`icons/${file.icon}.png`)} style={{ width: size, height: size, objectFit: "contain" }} />
    </div>
    {showName && (
      <div
        style={{
          font: `500 21px ${FONT}`,
          color: selected ? "#fff" : "#1E1E21",
          padding: "2px 10px",
          borderRadius: 8,
          background: selected ? "#3584E4" : "transparent",
        }}
      >
        {file.name}
      </div>
    )}
  </div>
);

const Keycap: React.FC<{ label: string; pressed: number }> = ({ label, pressed }) => (
  <div
    style={{
      width: 210,
      height: 112,
      borderRadius: 18,
      background: "linear-gradient(#FFFFFF, #ECECEF)",
      border: "1px solid #D4D4D8",
      boxShadow: `0 ${10 - pressed * 7}px 0 #C9C9CE, 0 ${16 - pressed * 8}px 28px rgba(0,0,0,0.16)`,
      translate: `0px ${pressed * 7}px`,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "#1E1E21",
      font: `600 30px ${FONT}`,
      outline: pressed > 0.5 ? `2px solid ${BRAND}` : "2px solid transparent",
    }}
  >
    {label}
  </div>
);

// MARK: - One wheel scene

/** Where things sit: "wide" (1600 × 1000) for the READMEs, "square" (1000 × 1000) for the welcome window. */
export type LayoutName = "wide" | "square";
type Layout = {
  fileX: number;
  fileY: number;
  anchor: { x: number; y: number };
  pointerStart: { x: number; y: number };
  floatRight: number;
  floatTop: number;
};
const LAYOUTS: Record<LayoutName, Layout> = {
  wide: {
    fileX: 420,
    fileY: 330,
    anchor: { x: 860, y: 430 },
    pointerStart: { x: 1180, y: 820 },
    floatRight: 120,
    floatTop: 250,
  },
  square: {
    fileX: 260,
    fileY: 300,
    anchor: { x: 650, y: 470 },
    pointerStart: { x: 880, y: 880 },
    floatRight: 28,
    floatTop: 470,
  },
};

// Timeline (frames inside the scene): reach the file, grab it, drag it, tap the key, the wheel opens, move round the
// ring, drop.
const T = { reach: 16, grab: 20, drag: 40, key: 44, keyDown: 48, keyUp: 56, wheel: 50, move: 62, arrive: 92, act: 98 };

const SceneView: React.FC<{ scene: Scene; layout: Layout }> = ({ scene, layout }) => {
  const { fileX, fileY, anchor } = layout;
  const frame = useCurrentFrame();
  const count = scene.files.length;
  const fileCenter = { x: fileX + 64 + (count - 1) * 95, y: fileY + 64 };

  const segments = scene.segments;
  const span = (Math.PI * 2) / segments.length;
  const ring = 0.5 * (INNER + OUTER) * WHEEL_SCALE;
  const startAngle = scene.start * span;
  let targetAngle = scene.target * span;
  // Go the short way round.
  while (targetAngle - startAngle > Math.PI) targetAngle -= Math.PI * 2;
  while (startAngle - targetAngle > Math.PI) targetAngle += Math.PI * 2;

  let pointer: { x: number; y: number };
  if (frame < T.grab) {
    pointer = {
      x: tween(frame, [0, T.reach], [layout.pointerStart.x, fileCenter.x]),
      y: tween(frame, [0, T.reach], [layout.pointerStart.y, fileCenter.y]),
    };
  } else if (frame < T.move) {
    pointer = {
      x: tween(frame, [T.grab, T.drag], [fileCenter.x, anchor.x]),
      y: tween(frame, [T.grab, T.drag], [fileCenter.y, anchor.y]),
    };
  } else {
    const half = (T.move + T.arrive) / 2;
    const radius = tween(frame, [T.move, half - 4], [0, ring]);
    const angle = tween(frame, [half - 6, T.arrive], [startAngle, targetAngle]);
    pointer = polar(anchor.x, anchor.y, radius, angle);
  }

  // Which segment is under the pointer.
  const dx = pointer.x - anchor.x;
  const dy = pointer.y - anchor.y;
  const distance = Math.hypot(dx, dy) / WHEEL_SCALE;
  const wheelVisible = frame >= T.wheel && frame < T.act + 8;
  let highlighted: number | null = null;
  if (wheelVisible && distance >= INNER && distance <= OUTER + 20) {
    const angle = (Math.atan2(dx, -dy) + Math.PI * 2) % (Math.PI * 2);
    highlighted = Math.round(angle / span) % segments.length;
  }

  const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
  const wheelOpacity = interpolate(frame, [T.wheel, T.wheel + 6, T.act + 2, T.act + 9], [0, 1, 1, 0], clamp);
  const wheelScale =
    frame < T.act ? tween(frame, [T.wheel, T.wheel + 9], [0.82, 1], pop) : tween(frame, [T.act, T.act + 9], [1, 0.9]);
  const keyOpacity = interpolate(frame, [T.key - 6, T.key, T.act + 12, T.act + 20], [0, 1, 1, 0], clamp);
  const keyPressed = interpolate(frame, [T.keyDown - 2, T.keyDown, T.keyUp, T.keyUp + 3], [0, 1, 1, 0], clamp);
  const dragging = frame >= T.grab && frame < T.act;
  const resultIn = tween(frame, [T.act + 4, T.act + 16], [0, 1], pop);
  const sceneOut = interpolate(frame, [SCENE - 10, SCENE], [1, 0], clamp);
  const sceneIn = interpolate(frame, [0, 8], [0, 1], clamp);

  return (
    <AbsoluteFill style={{ opacity: sceneIn * sceneOut }}>
      {/* Files in the folder */}
      {scene.files.map((file, index) => (
        <div key={file.name} style={{ position: "absolute", left: fileX - 30 + index * 190, top: fileY }}>
          <FileIcon file={file} selected={frame >= T.grab - 2} />
        </div>
      ))}

      {/* Result: the converted file next to the original */}
      {scene.result === "file" && frame >= T.act + 4 && (
        <div
          style={{
            position: "absolute",
            left: fileX - 30 + 190,
            top: fileY,
            scale: String(resultIn),
            opacity: resultIn,
          }}
        >
          <FileIcon file={{ name: "photo.jpg", icon: "photo-thumb" }} selected={false} />
        </div>
      )}

      {/* The wheel */}
      {wheelOpacity > 0 && (
        <div
          style={{
            position: "absolute",
            left: anchor.x - (OUTER + 24),
            top: anchor.y - (OUTER + 24),
            scale: String(WHEEL_SCALE * wheelScale),
            opacity: wheelOpacity,
          }}
        >
          <Wheel scene={scene} highlighted={highlighted} fileCount={count} />
        </div>
      )}

      {/* The key */}
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 70,
          display: "flex",
          justifyContent: "center",
          opacity: keyOpacity,
        }}
      >
        <Keycap label={scene.key} pressed={keyPressed} />
      </div>

      {/* Tool window */}
      {scene.result === "window" && frame >= T.act + 4 && (
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", opacity: resultIn }}>
          <Img
            src={staticFile("linux-trim.png")}
            style={{
              width: 800,
              scale: String(0.9 + 0.1 * resultIn),
              filter: "drop-shadow(0 26px 50px rgba(0,0,0,0.25))",
              borderRadius: 10,
            }}
          />
        </AbsoluteFill>
      )}

      {/* Float shelf */}
      {scene.result === "float" && frame >= T.act + 4 && (
        <div
          style={{
            position: "absolute",
            right: layout.floatRight,
            top: layout.floatTop,
            translate: `${(1 - resultIn) * 200}px 0px`,
            opacity: resultIn,
          }}
        >
          <Img src={staticFile("linux-float.png")} style={{ width: 400, filter: "drop-shadow(0 20px 44px rgba(0,0,0,0.25))" }} />
        </div>
      )}

      {/* Dragged files follow the pointer */}
      {dragging && (
        <div style={{ position: "absolute", left: pointer.x - 42, top: pointer.y - 42, opacity: 0.72 }}>
          {scene.files.map((file, index) => (
            <div key={file.name} style={{ position: "absolute", left: index * 10, top: -index * 10 }}>
              <FileIcon file={file} selected={false} size={84} showName={false} />
            </div>
          ))}
          {count > 1 && (
            <div
              style={{
                position: "absolute",
                left: 96,
                top: -18,
                minWidth: 34,
                height: 34,
                borderRadius: 17,
                background: "#E01B24",
                color: "#fff",
                font: `700 20px ${FONT}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              {count}
            </div>
          )}
        </div>
      )}

      {/* Pointer */}
      {frame < T.act + 14 && (
        <div
          style={{
            position: "absolute",
            left: pointer.x - 3,
            top: pointer.y - 3,
            opacity: frame < T.act + 6 ? 1 : tween(frame, [T.act + 6, T.act + 14], [1, 0]),
          }}
        >
          <Cursor pressed={dragging} />
        </div>
      )}
    </AbsoluteFill>
  );
};

// MARK: - Whole video

export const Demo: React.FC<{ layout?: LayoutName }> = ({ layout = "wide" }) => (
  <AbsoluteFill
    style={{
      background:
        "radial-gradient(1200px 700px at 30% 20%, rgba(103,30,56,0.10), transparent 70%), radial-gradient(900px 600px at 85% 90%, rgba(103,30,56,0.06), transparent 70%), #F6F5F6",
    }}
  >
    {SCENES.map((scene, index) => (
      <Sequence key={scene.kind} from={index * SCENE} durationInFrames={SCENE} layout="absolute-fill">
        <SceneView scene={scene} layout={LAYOUTS[layout]} />
      </Sequence>
    ))}
  </AbsoluteFill>
);
