import { Fragment } from "react";

// Minimal renderer for model answers: paragraphs, "-"/"1." lists, **bold**,
// _italic_ and [n] citation chips. Answers used to be one pre-wrapped block, so
// lists and paragraph breaks ran together.
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_|\[\d+\])/g).map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (/^_[^_]+_$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>;
    if (/^\[\d+\]$/.test(part))
      return (
        <sup key={i} className="mx-0.5 rounded bg-gold/20 px-1 text-[10px] font-semibold text-ink">
          {part.slice(1, -1)}
        </sup>
      );
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export default function AnswerText({ text }: { text: string }) {
  const blocks = text.replace(/\r/g, "").split(/\n{2,}/).filter((b) => b.trim());
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const bullets = lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l));
        if (bullets) {
          const ordered = /^\s*\d/.test(lines[0]);
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={i} className={`${ordered ? "list-decimal" : "list-disc"} space-y-1 pl-5`}>
              {lines.map((l, j) => (
                <li key={j}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""))}</li>
              ))}
            </Tag>
          );
        }
        const heading = block.match(/^#{1,4}\s+(.*)/);
        if (heading) return <p key={i} className="font-semibold">{inline(heading[1])}</p>;
        return <p key={i}>{inline(lines.join(" "))}</p>;
      })}
    </div>
  );
}
