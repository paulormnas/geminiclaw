import { readFileSync } from "node:fs";

/** Contraste WCAG dos pares texto/fundo declarados nos tokens, nos dois temas (design system §2.1). */
const css = readFileSync("src/styles/tokens.css", "utf8");

function block(selector: RegExp): string {
  const match = css.match(selector);
  if (!match) throw new Error(`bloco não encontrado: ${selector}`);
  return match[1] ?? "";
}

function vars(text: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const m of text.matchAll(/(--[\w-]+):\s*([^;]+);/g)) result[m[1] as string] = (m[2] as string).trim();
  return result;
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  s /= 100;
  l /= 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)];
}

function parse(value: string, all: Record<string, string>): [number, number, number] {
  const ref = value.match(/^var\((--[\w-]+)\)$/);
  if (ref) return parse(all[ref[1] as string] as string, all);
  const m = value.match(/hsl\(\s*([\d.]+)\s+([\d.]+)%\s+([\d.]+)%/);
  if (!m) throw new Error(`cor não suportada: ${value}`);
  return hslToRgb(Number(m[1]), Number(m[2]), Number(m[3]));
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function ratio(fg: string, bg: string, all: Record<string, string>): number {
  const a = luminance(parse(fg, all));
  const b = luminance(parse(bg, all));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const light = vars(block(/:root \{\s*color-scheme: light;([\s\S]*?)\n\}/));
const dark = vars(block(/:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/));

const PAIRS: [string, string][] = [
  ["--text", "--bg"],
  ["--text", "--surface"],
  ["--text", "--surface-2"],
  ["--text-muted", "--surface"],
  ["--text-muted", "--surface-2"],
  ["--primary-text", "--primary"],
  ["--accent-text", "--accent"],
  ["--pos", "--pos-bg"],
  ["--neg", "--neg-bg"],
  ["--warn", "--warn-bg"],
  ["--info", "--info-bg"],
  ["--neu", "--neu-bg"],
];

describe.each([
  ["claro", light],
  ["escuro", dark],
])("contraste no tema %s", (_name, theme) => {
  const all = { ...light, ...theme };
  it.each(PAIRS)("%s sobre %s ≥ 4,5:1", (fg, bg) => {
    expect(ratio(all[fg] as string, all[bg] as string, all)).toBeGreaterThanOrEqual(4.5);
  });
});
