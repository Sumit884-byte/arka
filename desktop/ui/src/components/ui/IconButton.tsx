import type { ButtonHTMLAttributes, ReactNode } from "react";

type IconButtonVariant = "ghost" | "soft" | "primary";

type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: IconButtonVariant;
  size?: "sm" | "md" | "lg";
  label: string;
  children: ReactNode;
};

const sizeClass = {
  sm: "icon-btn-sm",
  md: "icon-btn-md",
  lg: "icon-btn-lg",
} as const;

export default function IconButton({
  variant = "ghost",
  size = "md",
  label,
  className = "",
  children,
  ...props
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={`icon-btn ${sizeClass[size]} icon-btn-${variant} ${className}`.trim()}
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </button>
  );
}
