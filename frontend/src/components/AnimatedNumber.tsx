import { useEffect, useRef, useState } from "react";

/** Counts smoothly from the previous value to the new one (cost ticks up while Claude runs). */
export function useAnimatedNumber(target: number, durationMs = 900): number {
  const [value, setValue] = useState(target);
  const from = useRef(target);
  useEffect(() => {
    const start = performance.now();
    const begin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - (1 - t) ** 3;
      setValue(begin + (target - begin) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs]);
  return value;
}

/** A number that counts smoothly to its new value (decimals allowed, unlike StatCounter). */
export function AnimatedNumber({ value, format }: { value: number; format: (n: number) => string }) {
  return <>{format(useAnimatedNumber(value))}</>;
}
