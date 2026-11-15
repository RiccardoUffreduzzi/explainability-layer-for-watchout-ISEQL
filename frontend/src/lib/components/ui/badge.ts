import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' | 'info';

const BASE = 'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2';
const VARIANT: Record<BadgeVariant, string> = {
  default: 'border-transparent bg-primary text-primary-foreground hover:bg-primary/80',
  secondary: 'border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80',
  destructive: 'border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80',
  outline: 'text-foreground',
  success: 'border-transparent bg-success text-success-foreground hover:bg-success/80',
  warning: 'border-transparent bg-warning text-warning-foreground hover:bg-warning/80',
  info: 'border-transparent bg-info text-info-foreground hover:bg-info/80',
};

export function badgeClasses(variant: BadgeVariant = 'default', extra: ClassValue[] = []): string {
  return twMerge(clsx(BASE, VARIANT[variant], ...extra));
}
