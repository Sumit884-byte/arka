import type { FormEvent, KeyboardEvent, RefObject } from "react";
import IconButton from "./IconButton";
import { Paperclip, Send } from "./Icons";

type ComposerBarProps = {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  value: string;
  busy: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void;
};

export default function ComposerBar({
  inputRef,
  value,
  busy,
  onChange,
  onSubmit,
  onKeyDown,
}: ComposerBarProps) {
  return (
    <form className="composer-wrap" onSubmit={onSubmit}>
      <div className="composer">
        <IconButton variant="soft" size="lg" label="Attach file" disabled>
          <Paperclip size={18} strokeWidth={2} />
        </IconButton>
        <textarea
          ref={inputRef}
          rows={1}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask Arka anything…"
          disabled={busy}
        />
        <IconButton
          variant="primary"
          size="lg"
          label="Send message"
          disabled={busy || !value.trim()}
          type="submit"
        >
          <Send size={18} strokeWidth={2} />
        </IconButton>
      </div>
      <p className="fineprint">Arka can make mistakes. Review outputs before applying changes.</p>
    </form>
  );
}
