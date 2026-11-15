<script lang="ts">
  import * as Select from '$lib/components/ui/select/index.js';
  import { nextId, aliasOf, TEMPORAL_ATTRS, type CrossCondition, type FlatInterval } from '$lib/iseql-model';
  import { inputInt } from '$lib/dom-helpers';

  type Props = {
    crossConditions: CrossCondition[];
    flatIntervals: FlatInterval[];
    onChange: (ccs: CrossCondition[]) => void;
  };
  let { crossConditions, flatIntervals, onChange }: Props = $props();

  const CC_OPS = ['=', '≠', '<', '<=', '>', '>='];
  const TYPE_OPTIONS = [
    { value: 'attr', label: 'inequality' },
    { value: 'duration', label: 'duration' },
  ];
  const OP_OPTIONS = CC_OPS.map((op) => ({ value: op, label: op }));
  const TEMPORAL_OPTIONS = TEMPORAL_ATTRS.map((attr) => ({ value: attr, label: attr }));

  const aliasOptions = $derived(flatIntervals.map((f) => ({ value: aliasOf(f.globalIndex), label: aliasOf(f.globalIndex) })));

  // arg attributes come from the intervals' actual args (arg1..argN), plus the
  // always-available temporal columns (sf/ef/st/et). No made-up arg3/arg4.
  const attrsByAlias = $derived.by(() => {
    const map = new Map<string, string[]>();
    for (const f of flatIntervals) {
      const args: string[] = [];
      for (let k = 0; k < f.interval.args.length; k++) args.push(`arg${k + 1}`);
      map.set(aliasOf(f.globalIndex), [...args, ...TEMPORAL_ATTRS]);
    }
    return map;
  });

  function attrsFor(alias: string | undefined): string[] {
    return attrsByAlias.get(alias ?? '') ?? [];
  }

  function attrOptions(alias: string | undefined) {
    return attrsFor(alias).map((attr) => ({ value: attr, label: attr }));
  }

  function labelOf(options: { value: string; label: string }[], value: string): string {
    return options.find((option) => option.value === value)?.label ?? value;
  }

  const hasIntervals = $derived(flatIntervals.length > 0);

  function patch(i: number, p: Partial<CrossCondition>) {
    onChange(crossConditions.map((c, k) => (k === i ? { ...c, ...p } : c)));
  }

  function add() {
    if (!hasIntervals) return;
    const f0 = flatIntervals[0];
    const f1 = flatIntervals[1] ?? f0;
    const a0 = attrsFor(aliasOf(f0.globalIndex));
    const a1 = attrsFor(aliasOf(f1.globalIndex));
    onChange([
      ...crossConditions,
      {
        id: nextId('cc'),
        type: 'attr',
        left_alias: aliasOf(f0.globalIndex),
        left_attr: a0[0] ?? 'sf',
        op: '=',
        right_alias: aliasOf(f1.globalIndex),
        right_attr: a1[0] ?? 'sf',
      },
    ]);
  }

  function remove(i: number) {
    onChange(crossConditions.filter((_, k) => k !== i));
  }
</script>

<div class="space-y-2">
  <div class="flex items-center justify-between">
    <span class="text-xs font-semibold">Cross-conditions</span>
    <button type="button" class="rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-40" title="Add cross-condition" disabled={!hasIntervals} onclick={add}>＋</button>
  </div>

  {#if !hasIntervals}
    <p class="text-xs text-muted-foreground">Assign intervals to this set before adding cross-conditions.</p>
  {:else}
    <div class="max-h-40 space-y-1.5 overflow-y-auto pr-1">
      {#each crossConditions as c, i (c.id)}
      <div class="rounded-lg border p-1.5">
        <div class="mb-1 flex items-center justify-between">
          <Select.Root type="single" items={TYPE_OPTIONS} value={c.type} onValueChange={(next: string | undefined) => next && patch(i, { type: next as 'attr' | 'duration' })}>
            <Select.Trigger class="h-7 w-28 font-mono text-xs">{labelOf(TYPE_OPTIONS, c.type)}</Select.Trigger>
            <Select.Content>
              {#each TYPE_OPTIONS as option (option.value)}
                <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
          <button type="button" class="px-0.5 text-xs text-muted-foreground hover:text-foreground" title="remove" onclick={() => remove(i)}>✕</button>
        </div>

        {#if c.type === 'duration'}
          <div class="flex flex-wrap items-center gap-1">
            <Select.Root type="single" items={aliasOptions} value={c.left_alias} onValueChange={(next: string | undefined) => next && patch(i, { left_alias: next })}>
              <Select.Trigger class="h-7 w-28 font-mono text-xs">{labelOf(aliasOptions, c.left_alias)}</Select.Trigger>
              <Select.Content>
                {#each aliasOptions as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={TEMPORAL_OPTIONS} value={c.left_attr} onValueChange={(next: string | undefined) => next && patch(i, { left_attr: next })}>
              <Select.Trigger class="h-7 w-16 font-mono text-xs">{labelOf(TEMPORAL_OPTIONS, c.left_attr)}</Select.Trigger>
              <Select.Content>
                {#each TEMPORAL_OPTIONS as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <span class="text-xs text-muted-foreground">−</span>
            <Select.Root type="single" items={aliasOptions} value={c.right_alias ?? ''} onValueChange={(next: string | undefined) => next && patch(i, { right_alias: next })}>
              <Select.Trigger class="h-7 w-28 font-mono text-xs">{labelOf(aliasOptions, c.right_alias ?? '')}</Select.Trigger>
              <Select.Content>
                {#each aliasOptions as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={TEMPORAL_OPTIONS} value={c.right_attr ?? ''} onValueChange={(next: string | undefined) => next && patch(i, { right_attr: next })}>
              <Select.Trigger class="h-7 w-16 font-mono text-xs">{labelOf(TEMPORAL_OPTIONS, c.right_attr ?? '')}</Select.Trigger>
              <Select.Content>
                {#each TEMPORAL_OPTIONS as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={OP_OPTIONS} value={c.op} onValueChange={(next: string | undefined) => next && patch(i, { op: next })}>
              <Select.Trigger class="h-7 w-16 font-mono text-xs">{labelOf(OP_OPTIONS, c.op)}</Select.Trigger>
              <Select.Content>
                {#each OP_OPTIONS as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <input class="h-7 w-16 rounded-lg border bg-card px-1 py-0 font-mono text-xs" type="number" value={c.value ?? 0} onchange={(e) => patch(i, { value: inputInt(e, 0) })} />
          </div>
        {:else}
          <div class="flex flex-wrap items-center gap-1">
            <Select.Root type="single" items={aliasOptions} value={c.left_alias} onValueChange={(next: string | undefined) => next && patch(i, { left_alias: next })}>
              <Select.Trigger class="h-7 w-28 font-mono text-xs">{labelOf(aliasOptions, c.left_alias)}</Select.Trigger>
              <Select.Content>
                {#each aliasOptions as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={attrOptions(c.left_alias)} value={c.left_attr} onValueChange={(next: string | undefined) => next && patch(i, { left_attr: next })}>
              <Select.Trigger class="h-7 w-16 font-mono text-xs">{labelOf(attrOptions(c.left_alias), c.left_attr)}</Select.Trigger>
              <Select.Content>
                {#each attrOptions(c.left_alias) as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={OP_OPTIONS} value={c.op} onValueChange={(next: string | undefined) => next && patch(i, { op: next })}>
              <Select.Trigger class="h-7 w-16 font-mono text-xs">{labelOf(OP_OPTIONS, c.op)}</Select.Trigger>
              <Select.Content>
                {#each OP_OPTIONS as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={aliasOptions} value={c.right_alias ?? ''} onValueChange={(next: string | undefined) => next && patch(i, { right_alias: next })}>
              <Select.Trigger class="h-7 w-28 font-mono text-xs">{labelOf(aliasOptions, c.right_alias ?? '')}</Select.Trigger>
              <Select.Content>
                {#each aliasOptions as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" items={attrOptions(c.right_alias)} value={c.right_attr ?? ''} onValueChange={(next: string | undefined) => next && patch(i, { right_attr: next })}>
              <Select.Trigger class="h-7 w-16 font-mono text-xs">{labelOf(attrOptions(c.right_alias), c.right_attr ?? '')}</Select.Trigger>
              <Select.Content>
                {#each attrOptions(c.right_alias) as option (option.value)}
                  <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
          </div>
        {/if}
      </div>
    {:else}
      <p class="text-xs text-muted-foreground">No cross-conditions. e.g. M1 arg1 = M2 arg1</p>
      {/each}
    </div>
  {/if}
</div>
