type LoadingVariant = 'default' | 'title' | 'badge' | 'short' | 'long' | 'metric' | 'chip';

type LoadingLineProps = {
  variant?: LoadingVariant;
  className?: string;
};

type LoadingBlockProps = {
  lines?: LoadingVariant[];
  className?: string;
};

type LoadingCardProps = {
  blocks?: LoadingVariant[][];
  className?: string;
};

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ');
}

export function LoadingLine({ variant = 'default', className }: LoadingLineProps) {
  return <div className={classNames('panel-loading-line', `panel-loading-line-${variant}`, className)} />;
}

export function LoadingBlock({ lines = ['default', 'default', 'short'], className }: LoadingBlockProps) {
  return (
    <div className={classNames('panel-loading-block', className)}>
      {lines.map((line, index) => <LoadingLine className={index === 0 && line === 'default' ? 'panel-loading-line-long' : ''} key={`${line}-${index}`} variant={line} />)}
    </div>
  );
}

export function LoadingCard({
  blocks = [
    ['title', 'badge'],
    ['long', 'default', 'short'],
    ['default', 'long', 'short'],
  ],
  className,
}: LoadingCardProps) {
  return (
    <article className={classNames('panel-loading-card', className)}>
      {blocks.map((lines, index) => <LoadingBlock key={index} lines={lines} />)}
    </article>
  );
}
