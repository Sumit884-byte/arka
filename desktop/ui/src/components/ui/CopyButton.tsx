import { toast } from "sonner";
import IconButton from "./IconButton";
import { Copy } from "./Icons";

type CopyButtonProps = {
  text: string;
};

export default function CopyButton({ text }: CopyButtonProps) {
  async function copy() {
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied to clipboard");
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
      toast.success("Copied to clipboard");
    }
  }

  return (
    <IconButton variant="ghost" size="sm" label="Copy to clipboard" onClick={() => void copy()}>
      <Copy size={16} strokeWidth={2} />
    </IconButton>
  );
}

export function CopyButtonWithFeedback({ text, label = "Copy output" }: { text: string; label?: string }) {
  async function copy() {
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      toast.success(label);
    } catch {
      toast.error("Could not copy");
    }
  }

  return (
    <IconButton variant="ghost" size="sm" label={label} onClick={() => void copy()}>
      <Copy size={16} strokeWidth={2} />
    </IconButton>
  );
}
