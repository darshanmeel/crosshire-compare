import { Fragment, type ReactNode } from "react";

const TOKEN = /(:(green|red|orange)\[([^\]]*)\])|(\*\*([^*]+)\*\*)|(`([^`]+)`)|(\*([^*\s][^*]*)\*)/g;
const TONE: Record<string, string> = { green: "pos", red: "neg", orange: "accent" };

/** The Streamlit markup the engine's sentences are written in, as spans. */
export function marks(text: string): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    if (m[1]) out.push(<span key={m.index} className={TONE[m[2]]}>{marks(m[3])}</span>);
    else if (m[4]) out.push(<b key={m.index}>{m[5]}</b>);
    else if (m[6]) out.push(<code key={m.index}>{m[7]}</code>);
    else out.push(<em key={m.index}>{m[9]}</em>);
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <Fragment>{out}</Fragment>;
}
