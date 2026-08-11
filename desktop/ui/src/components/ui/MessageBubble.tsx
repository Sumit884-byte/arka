import { motion } from "framer-motion";
import CopyButton from "./CopyButton";
import MessageContent from "./MessageContent";

type MessageBubbleProps = {
  role: "user" | "assistant";
  text: string;
  routeSkill?: string;
};

export default function MessageBubble({ role, text, routeSkill }: MessageBubbleProps) {
  const isAssistant = role === "assistant";

  return (
    <motion.article
      className={`msg ${role === "user" ? "user" : "arka"}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
    >
      <div className={`avatar ${isAssistant ? "arka" : ""}`}>{role === "user" ? "You" : "A"}</div>
      <div className={`bubble ${role}`}>
        {routeSkill ? (
          <div className="bubble-meta">
            <div className="chip">routed → {routeSkill}</div>
          </div>
        ) : null}
        <div className="bubble-body">
          <MessageContent text={text} markdown={isAssistant} />
          <CopyButton text={text} />
        </div>
      </div>
    </motion.article>
  );
}
