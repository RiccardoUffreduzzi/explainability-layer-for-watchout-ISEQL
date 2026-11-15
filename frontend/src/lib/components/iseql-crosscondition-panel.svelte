<script lang="ts">
  import { nextId, aliasOf, TEMPORAL_ATTRS, type CrossCondition, type FlatInterval } from '$lib/iseql-model';
  import { inputInt, selectValue } from '$lib/dom-helpers';

  type Props = {
    crossConditions: CrossCondition[];
    flatIntervals: FlatInterval[];
    onChange: (ccs: CrossCondition[]) => void;
  };
  let { crossConditions, flatIntervals, onChange }: Props = $props();

  const CC_OPS = ['=', '≠', '<', '<=', '>', '>='];

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

  const hasIntervals = $derived(flatIntervals.length > 0);

  const sel = 'h-7 rounded-lg border bg-card px-1 py-0 font-mono text-xs';

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
    <button type="button" class="rounded border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-40" title="Add cross-condition" disabled={!hasIntervals} onclick={add}>＋</button>
  </div>

  {#if !hasIntervals}
    <p class="text-xs text-muted-foreground">Assign intervals to this set before adding cross-conditions.</p>
  {:else}
    <div class="max-h-40 space-y-1.5 overflow-y-auto pr-1">
      {#each crossConditions as c, i (c.id)}
      <div class="rounded border p-1.5">
        <div class="mb-1 flex items-center justify-between">
          <select class={sel + ' w-28'} value={c.type} onchange={(e) => patch(i, { type: selectValue(e, 'attr') as 'attr' | 'duration' })}>
            <option value="attr">inequality</option>
            <option value="duration">duration</option>
          </select>
          <button type="button" class="px-0.5 text-xs text-muted-foreground hover:text-foreground" title="remove" onclick={() => remove(i)}>✕</button>
        </div>

        {#if c.type === 'duration'}
          <div class="flex flex-wrap items-center gap-1">
            <select class={sel} value={c.left_alias} onchange={(e) => patch(i, { left_alias: selectValue(e) })}>
              {#each aliasOptions as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
            </select>
            <select class={sel + ' w-14'} value={c.left_attr} onchange={(e) => patch(i, { left_attr: selectValue(e) })}>
              {#each TEMPORAL_ATTRS as a (a)}<option value={a}>{a}</option>{/each}
            </select>
            <span class="text-xs text-muted-foreground">−</span>
            <select class={sel} value={c.right_alias ?? ''} onchange={(e) => patch(i, { right_alias: selectValue(e) })}>
              {#each aliasOptions as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
            </select>
            <select class={sel + ' w-14'} value={c.right_attr ?? ''} onchange={(e) => patch(i, { right_attr: selectValue(e) })}>
              {#each TEMPORAL_ATTRS as a (a)}<option value={a}>{a}</option>{/each}
            </select>
            <select class={sel + ' w-16'} value={c.op} onchange={(e) => patch(i, { op: selectValue(e, '=') })}>
              {#each CC_OPS as o (o)}<option value={o}>{o}</option>{/each}
            </select>
            <input class="h-7 w-16 rounded-lg border bg-card px-1 py-0 font-mono text-xs" type="number" value={c.value ?? 0} onchange={(e) => patch(i, { value: inputInt(e, 0) })} />
          </div>
        {:else}
          <div class="flex flex-wrap items-center gap-1">
            <select class={sel} value={c.left_alias} onchange={(e) => patch(i, { left_alias: selectValue(e) })}>
              {#each aliasOptions as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
            </select>
            <select class={sel + ' w-16'} value={c.left_attr} onchange={(e) => patch(i, { left_attr: selectValue(e) })}>
              {#each attrsFor(c.left_alias) as a (a)}<option value={a}>{a}</option>{/each}
            </select>
            <select class={sel + ' w-16'} value={c.op} onchange={(e) => patch(i, { op: selectValue(e, '=') })}>
              {#each CC_OPS as o (o)}<option value={o}>{o}</option>{/each}
            </select>
            <select class={sel} value={c.right_alias ?? ''} onchange={(e) => patch(i, { right_alias: selectValue(e) })}>
              {#each aliasOptions as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
            </select>
            <select class={sel + ' w-16'} value={c.right_attr ?? ''} onchange={(e) => patch(i, { right_attr: selectValue(e) })}>
              {#each attrsFor(c.right_alias) as a (a)}<option value={a}>{a}</option>{/each}
            </select>
          </div>
        {/if}
      </div>
    {:else}
      <p class="text-xs text-muted-foreground">No cross-conditions. e.g. M1 arg1 = M2 arg1</p>
      {/each}
    </div>
  {/if}
</div>
