/**
 * Consistent icon + text action link used across the UI.
 * For: Reply, Share, Open PDF, GitHub, etc.
 */

import { cn } from '@/lib/utils';

interface ActionLinkProps {
  icon: React.ReactNode;
  label: string;
  onClick?: () => void;
  href?: string;
  external?: boolean;
  active?: boolean;
  className?: string;
  'data-agent-action'?: string;
}

export function ActionLink({
  icon,
  label,
  onClick,
  href,
  external = false,
  active = false,
  className,
  ...props
}: ActionLinkProps) {
  const classes = cn(
    "inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary transition-colors",
    active && "text-foreground",
    className,
  );

  if (href) {
    return (
      <a
        href={href}
        target={external ? "_blank" : undefined}
        rel={external ? "noreferrer" : undefined}
        className={classes}
        {...props}
      >
        {icon}
        <span>{label}</span>
      </a>
    );
  }

  return (
    <button onClick={onClick} className={classes} {...props}>
      {icon}
      <span>{label}</span>
    </button>
  );
}
