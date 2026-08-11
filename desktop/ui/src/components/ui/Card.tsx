import { Sparkles } from "./Icons";

type SuggestionCardProps = {
  title: string;
  body: string;
  disabled?: boolean;
  onClick: () => void;
};

export function SuggestionCard({ title, body, disabled, onClick }: SuggestionCardProps) {
  return (
    <button type="button" className="suggestion" onClick={onClick} disabled={disabled}>
      <span className="suggestion-icon" aria-hidden="true">
        <Sparkles size={14} strokeWidth={2} />
      </span>
      <span className="suggestion-copy">
        <b>{title}</b>
        <span>{body}</span>
      </span>
    </button>
  );
}
