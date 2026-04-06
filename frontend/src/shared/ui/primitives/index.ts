// Primitives — Shadcn UI 原始组件统一导出
// 所有 import 统一走 @/shared/ui/primitives 或 @/shared/ui（兼容旧路径）
export { Button, buttonVariants } from "./button";
export type { ButtonProps } from "./button";

export { Badge, badgeVariants } from "./badge";
export type { BadgeProps } from "./badge";

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
} from "./card";

export { Input } from "./input";

export { Textarea } from "./textarea";

export * from "./dialog";
export * from "./dropdown-menu";
export * from "./toast";
export * from "./toaster";
export * from "./use-toast";

