import { readFileSync } from "node:fs";
import { join } from "node:path";

import { initials } from "./team";
import { applyTheme, getTheme } from "./theme";

// ------------------------------------------------------------------ team avatars
test("team initials", () => {
  expect(initials("Real Madrid")).toBe("RM");
  expect(initials("Arsenal")).toBe("AR");
  expect(initials("Nott'm Forest")).toBe("NM");
  expect(initials("")).toBe("?");
});

// ------------------------------------------------------------------ theme
test("dark by default; the choice is remembered", () => {
  expect(getTheme()).toBe("dark");
  applyTheme("light");
  expect(getTheme()).toBe("light");
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  applyTheme("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});

// ------------------------------------------------------------------ WCAG AA contrast of the tokens
function oklchToLinearRgb(l: number, c: number, h: number): [number, number, number] {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (v: number) => Math.min(1, Math.max(0, v));
  return [
    clamp(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
    clamp(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
    clamp(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_),
  ];
}

function luminance(rgb: [number, number, number]): number {
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

function contrast(fg: [number, number, number], bg: [number, number, number]): number {
  const [hi, lo] = [luminance(fg), luminance(bg)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const css = readFileSync(join(process.cwd(), "src/index.css"), "utf8");

function tokens(selector: ":root" | ".dark"): Record<string, [number, number, number]> {
  const block = css.slice(css.indexOf(`${selector} {`)).split("}")[0]!;
  const out: Record<string, [number, number, number]> = {};
  for (const match of block.matchAll(/--([a-z-]+):\s*oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)/g)) {
    out[match[1]!] = oklchToLinearRgb(Number(match[2]), Number(match[3]), Number(match[4]));
  }
  return out;
}

const PAIRS: [string, string][] = [
  ["foreground", "background"],
  ["foreground", "card"],
  ["foreground", "secondary"], // team monograms (spec 005)
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["muted-foreground", "muted"],
  ["primary-foreground", "primary"],
  ["primary", "card"], // accent text and links (spec 005)
  ["primary", "background"],
  ["accent-foreground", "accent"],
  ["positive", "card"],
  ["negative", "card"],
  ["experimental", "experimental-soft"],
  ["experimental", "card"],
  ["info", "info-soft"],
  ["positive", "positive-soft"],
  ["negative", "negative-soft"],
];

// Field borders are user-interface components: at least 3:1 against what surrounds them (1.4.11).
test.each([":root", ".dark"] as const)("field borders meet 3:1 in %s", (theme) => {
  const t = tokens(theme);
  for (const bg of ["card", "background"]) {
    const ratio = contrast(t["input"]!, t[bg]!);
    expect({
      pair: `input on ${bg}`,
      ok: ratio >= 3,
      ratio: Math.round(ratio * 100) / 100,
    }).toMatchObject({
      ok: true,
    });
  }
});

test.each([":root", ".dark"] as const)("text tokens meet WCAG AA (4.5:1) in %s", (theme) => {
  const t = tokens(theme);
  for (const [fg, bg] of PAIRS) {
    const ratio = contrast(t[fg]!, t[bg]!);
    expect({
      pair: `${fg} on ${bg}`,
      ok: ratio >= 4.5,
      ratio: Math.round(ratio * 100) / 100,
    }).toMatchObject({ ok: true });
  }
});
