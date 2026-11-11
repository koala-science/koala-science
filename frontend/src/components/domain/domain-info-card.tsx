import { Card } from '@/components/ui/card';
import { FileText } from 'lucide-react';

interface DomainInfoCardProps {
  name: string;
  description: string;
  paperCount?: number;
}

export function DomainInfoCard({ name, description, paperCount = 0 }: DomainInfoCardProps) {
  const displayName = name.startsWith('d/') ? name : `d/${name}`;

  return (
    <Card className="p-0 gap-0" data-agent-action="domain-info">
      <div className="p-6">
        <h1 className="font-heading text-2xl font-bold tracking-tight sm:text-3xl mb-2">
          {displayName}
        </h1>
        {description && (
          <p className="text-sm leading-relaxed text-foreground/80">
            {description}
          </p>
        )}
      </div>

      <div className="border-t bg-secondary/40 px-6 py-2.5 flex items-center gap-4 text-xs text-muted-foreground">
        <div className="inline-flex items-center gap-1.5">
          <FileText className="h-3.5 w-3.5" />
          <span>{paperCount} paper{paperCount === 1 ? '' : 's'}</span>
        </div>
      </div>
    </Card>
  );
}
