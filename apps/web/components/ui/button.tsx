import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: "primary" | "ghost" | "danger";
  }
>(({ className, variant = "primary", ...props }, ref) => (
  <button ref={ref} className={cn("button", variant, className)} {...props} />
));
Button.displayName = "Button";
