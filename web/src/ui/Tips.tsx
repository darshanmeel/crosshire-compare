import { marks } from "./marks";

export function Tips({ items }: { items: (string | false | null | undefined)[] }) {
  return <ul className="tips">{items.filter(Boolean).map((t, i) => <li key={i}>{marks(t as string)}</li>)}</ul>;
}
