import { motion } from "framer-motion";

export default function TypingIndicator() {
  return (
    <div className="typing-indicator" aria-label="Arka is thinking">
      {[0, 1, 2].map((index) => (
        <motion.span
          key={index}
          className="typing-dot"
          animate={{ opacity: [0.35, 1, 0.35], y: [0, -3, 0] }}
          transition={{
            duration: 0.9,
            repeat: Infinity,
            delay: index * 0.15,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  );
}
