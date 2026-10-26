import { Composition } from "remotion";
import { Demo, FPS, HEIGHT, SCENE, WIDTH } from "./Demo";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* 1600 × 1000 for the READMEs */}
      <Composition
        id="LinuxDemo"
        component={Demo}
        defaultProps={{ layout: "wide" as const }}
        durationInFrames={SCENE * 3}
        fps={FPS}
        width={WIDTH}
        height={HEIGHT}
      />
      {/* 1000 × 1000 for the welcome window */}
      <Composition
        id="LinuxDemoSquare"
        component={Demo}
        defaultProps={{ layout: "square" as const }}
        durationInFrames={SCENE * 3}
        fps={FPS}
        width={1000}
        height={1000}
      />
    </>
  );
};
