import type { IconName } from "../components/Icon";
const sources: Record<
  string,
  { icon: IconName; color: string; background: string }
> = {
  Solar: { icon: "sun", color: "#ba7b15", background: "#fff0cc" },
  Wind: { icon: "wind", color: "#438779", background: "#e3f2ed" },
  Hydro: { icon: "water", color: "#6086b7", background: "#e9effa" },
  Battery: { icon: "battery", color: "#9670b3", background: "#f1eafa" },
};
export const sourceStyle = (source: string) =>
  sources[source] ?? {
    icon: "bolt" as IconName,
    color: "#728076",
    background: "#edf0ed",
  };
