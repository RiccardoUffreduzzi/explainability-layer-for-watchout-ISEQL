<script lang="ts">
  import { cn } from '$lib/utils';
  import type { Unit } from '$lib/types';

  type Props = {
    unit: Unit;
    onUnitChange: (u: Unit) => void;
    secondsLabel?: string;
    class?: string;
  };
  let { unit, onUnitChange, secondsLabel = 'Seconds', class: className = '' }: Props = $props();

  const OPTIONS = $derived<{ value: Unit; label: string }[]>([
    { value: 'seconds', label: secondsLabel },
    { value: 'frames', label: 'Frames' },
  ]);
</script>

<div class={cn('inline-flex h-7 items-center rounded-md border border-border bg-muted/30 p-0.5', className)}>
  {#each OPTIONS as opt (opt.value)}
    <button
      type="button"
      class={cn(
        'h-full rounded px-2 text-xs font-medium transition-colors',
        unit === opt.value
          ? 'bg-card text-foreground shadow-sm'
          : 'text-muted-foreground hover:text-foreground'
      )}
      onclick={() => onUnitChange(opt.value)}
    >
      {opt.label}
    </button>
  {/each}
</div>
