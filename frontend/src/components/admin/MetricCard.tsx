import type { ElementType } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type ColorVariant = 'default' | 'success' | 'warning' | 'danger';

interface MetricCardProps {
  icon: ElementType;
  label: string;
  value: number | string;
  description?: string;
  colorVariant?: ColorVariant;
  change?: number;
}

const variantStyles: Record<ColorVariant, { icon: string; value: string }> = {
  default: { icon: 'text-gray-500', value: 'text-gray-900' },
  success: { icon: 'text-green-600', value: 'text-green-700' },
  warning: { icon: 'text-amber-500', value: 'text-amber-700' },
  danger: { icon: 'text-red-500', value: 'text-red-700' },
};

export function MetricCard({
  icon: Icon,
  label,
  value,
  description,
  colorVariant = 'default',
  change,
}: MetricCardProps) {
  const styles = variantStyles[colorVariant];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-gray-500">{label}</CardTitle>
        <Icon className={cn('h-5 w-5', styles.icon)} />
      </CardHeader>
      <CardContent>
        <div className={cn('text-3xl font-bold', styles.value)}>{value}</div>
        <div className="flex items-center gap-2 mt-1">
          {change !== undefined && (
            <span
              className={cn(
                'flex items-center text-xs font-medium',
                change >= 0 ? 'text-green-600' : 'text-red-600',
              )}
            >
              {change >= 0 ? (
                <TrendingUp className="h-3 w-3 mr-0.5" />
              ) : (
                <TrendingDown className="h-3 w-3 mr-0.5" />
              )}
              {Math.abs(change)}%
            </span>
          )}
          {description && (
            <p className="text-xs text-gray-500">{description}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
