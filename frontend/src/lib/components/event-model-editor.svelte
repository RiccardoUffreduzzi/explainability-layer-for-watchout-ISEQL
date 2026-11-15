<script lang="ts">
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Select from '$lib/components/ui/select.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { inputFloat, inputInt, inputStr, selectValue } from '$lib/dom-helpers';

  interface ModelInterval {
    pred: string;
    ts: number;
    te: number;
    group: string;
    side: string;
  }
  interface ModelOperator {
    op: string;
    deltaKey: string;
    zeta: string;
    rho: number;
  }
  interface ModelCrossCondition {
    left: string;
    leftAttr: string;
    op: string;
    right: string;
    rightAttr: string;
  }

  type Props = {
    onChange: (m: Record<string, unknown>) => void;
  };
  let { onChange }: Props = $props();

  const OPERATOR_OPTIONS = [
    { value: 'auto', label: 'Auto (from interval times)' },
    { value: 'Bef', label: 'Before (Bef)' },
    { value: 'Aft', label: 'After (Aft)' },
    { value: 'SP', label: 'Start Preceding (SP)' },
    { value: 'EF', label: 'End Following (EF)' },
    { value: 'DJ', label: 'During (DJ)' },
    { value: 'RDJ', label: 'Reverse During (RDJ)' },
    { value: 'LOJ', label: 'Left Overlap (LOJ)' },
    { value: 'ROJ', label: 'Right Overlap (ROJ)' },
  ];
  const CC_OPS = ['=', '≠', '<', '<=', '>', '>='];

  // editable state (starts from a sensible enter/exit example)
  let predicates = $state<{ name: string; args: string }[]>([{ name: 'enter_or_exit_vehicle', args: 'person, vehicle' }]);
  let intervals = $state<ModelInterval[]>([{ pred: 'enter_or_exit_vehicle', ts: 0, te: 100, group: '', side: 'none' }]);
  let operators = $state<ModelOperator[]>([]);
  let crossConditions = $state<ModelCrossCondition[]>([]);

  function syncOperatorsCount() {
    const need = Math.max(0, intervals.length - 1);
    while (operators.length < need) {
      operators = [...operators, { op: 'auto', deltaKey: '', zeta: '<=', rho: 0 }];
    }
    if (operators.length > need) operators = operators.slice(0, need);
  }

  $effect(() => {
    syncOperatorsCount();
  });

  function argsOf(predName: string): string[] {
    const p = predicates.find((x) => x.name === predName);
    return p ? p.args.split(',').map((s) => s.trim()).filter(Boolean) : [];
  }

  function buildModel(): Record<string, unknown> {
    const intervalsOut = intervals.map((iv) => ({
      pred: { name: iv.pred, arguments: argsOf(iv.pred) },
      ts: iv.ts,
      te: iv.te,
      set_side: iv.side === 'none' ? null : iv.side,
      group_id: iv.group || null,
    }));
    const overrides = operators
      .map((o, i) => (o.op === 'auto' ? null : { side: 'none', pair_idx: i + 1, operator: o.op }))
      .filter(Boolean);
    const deltaMap: Record<string, unknown> = {};
    operators.forEach((o, i) => {
      if (o.deltaKey) {
        const entry: Record<string, unknown> = { delta: o.deltaKey };
        if (o.zeta) entry.zeta = o.zeta;
        if (o.rho) entry.rho = o.rho;
        deltaMap[String(i)] = entry;
      }
    });
    const m: Record<string, unknown> = {
      intervals: intervalsOut,
      cross_conditions: crossConditions.map((c) => ({
        left_alias: c.left,
        left_attr: c.leftAttr,
        op: c.op,
        right_alias: c.right,
        right_attr: c.rightAttr,
      })),
    };
    if (overrides.length) m.operator_overrides = overrides;
    if (Object.keys(deltaMap).length) m.delta_map = deltaMap;
    return m;
  }

  // Emit the serialized model on every change (and once on mount with the default).
  $effect(() => {
    onChange(buildModel());
  });

  function addInterval() {
    intervals = [...intervals, { pred: predicates[0]?.name ?? '', ts: 0, te: 100, group: '', side: 'none' }];
  }
  function removeInterval(i: number) {
    intervals = intervals.filter((_, idx) => idx !== i);
  }
  function patchInterval(i: number, p: Partial<ModelInterval>) {
    intervals = intervals.map((iv, idx) => (idx === i ? { ...iv, ...p } : iv));
  }
  function patchOp(i: number, p: Partial<ModelOperator>) {
    operators = operators.map((o, idx) => (idx === i ? { ...o, ...p } : o));
  }
  function addPredicate() {
    const name = `predicate_${predicates.length + 1}`;
    predicates = [...predicates, { name, args: 'person' }];
  }
  function removePredicate(name: string) {
    predicates = predicates.filter((p) => p.name !== name);
    intervals = intervals.map((iv) => (iv.pred === name ? { ...iv, pred: predicates[0]?.name ?? '' } : iv));
  }
  function addCc() {
    crossConditions = [...crossConditions, { left: 'M1', leftAttr: 'arg1', op: '=', right: 'M2', rightAttr: 'arg1' }];
  }
  function removeCc(i: number) {
    crossConditions = crossConditions.filter((_, idx) => idx !== i);
  }
  function patchCc(i: number, p: Partial<ModelCrossCondition>) {
    crossConditions = crossConditions.map((c, idx) => (idx === i ? { ...c, ...p } : c));
  }
  const predOptions = $derived(predicates.map((p) => ({ value: p.name, label: p.name })));
</script>

<div class="space-y-4">
  <div>
    <div class="flex items-center justify-between">
      <Label>Predicates</Label>
      <button type="button" class="text-xs text-muted-foreground underline" onclick={addPredicate}>+ add</button>
    </div>
    <div class="space-y-2">
      {#each predicates as p, pi (p.name)}
        <div class="flex items-center gap-2 rounded-lg border p-2">
          <Input class="w-40 font-mono" value={p.name} onchange={(e) => {
            const old = p.name; const next = inputStr(e);
            predicates = predicates.map((x, idx) => (idx === pi ? { ...x, name: next } : x));
            intervals = intervals.map((iv) => (iv.pred === old ? { ...iv, pred: next } : iv));
          }} />
          <Input class="flex-1 font-mono" placeholder="person, vehicle" value={p.args} onchange={(e) => (predicates = predicates.map((x, idx) => (idx === pi ? { ...x, args: inputStr(e) } : x)))} />
          <button type="button" class="text-xs text-destructive underline" onclick={() => removePredicate(p.name)}>x</button>
        </div>
      {:else}
        <p class="text-xs text-muted-foreground">No predicates.</p>
      {/each}
    </div>
  </div>

  <div>
    <div class="flex items-center justify-between">
      <Label>Intervals</Label>
      <button type="button" class="text-xs text-muted-foreground underline" onclick={addInterval}>+ add</button>
    </div>
    <div class="space-y-2">
      {#each intervals as iv, i (i)}
        <div class="rounded-lg border p-2">
          <div class="flex items-center gap-2">
            <span class="w-6 text-center font-mono text-xs text-muted-foreground">M{i + 1}</span>
            <Select options={predOptions} value={iv.pred} onchange={(e) => patchInterval(i, { pred: selectValue(e) })} />
            <Input class="w-20" type="number" min="0" value={iv.ts} onchange={(e) => patchInterval(i, { ts: inputInt(e, 0) })} />
            <span class="text-xs text-muted-foreground">to</span>
            <Input class="w-20" type="number" min="0" value={iv.te} onchange={(e) => patchInterval(i, { te: inputInt(e, 100) })} />
            <Input class="w-28" placeholder="group" value={iv.group} onchange={(e) => patchInterval(i, { group: inputStr(e) })} />
            <Select
              options={[
                { value: 'none', label: 'no side' },
                { value: 'left', label: 'left' },
                { value: 'right', label: 'right' },
              ]}
              value={iv.side}
              onchange={(e) => patchInterval(i, { side: selectValue(e, 'none') })}
            />
            <button type="button" class="text-xs text-destructive underline" onclick={() => removeInterval(i)}>x</button>
          </div>
        </div>
      {:else}
        <p class="text-xs text-muted-foreground">No intervals.</p>
      {/each}
    </div>
  </div>

  {#if operators.length}
    <div>
      <Label>Operators between intervals</Label>
      <div class="space-y-2">
        {#each operators as op, i (i)}
          <div class="flex items-center gap-2 rounded-lg border p-2">
            <span class="font-mono text-xs text-muted-foreground">M{i + 1} → M{i + 2}</span>
            <Select options={OPERATOR_OPTIONS} value={op.op} onchange={(e) => patchOp(i, { op: selectValue(e, 'auto') })} />
            <Input class="w-44 font-mono" placeholder="delta key (e.g. delta_visual_handoff)" value={op.deltaKey} onchange={(e) => patchOp(i, { deltaKey: inputStr(e) })} />
            {#if op.deltaKey}
              <Select
                options={[{ value: '<=', label: '<=' }, { value: '<', label: '<' }]}
                value={op.zeta}
                onchange={(e) => patchOp(i, { zeta: selectValue(e, '<=') })}
              />
              <Input class="w-20" type="number" min="0" value={op.rho} onchange={(e) => patchOp(i, { rho: inputFloat(e, 0) })} />
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <div>
    <div class="flex items-center justify-between">
      <Label>Cross-conditions</Label>
      <button type="button" class="text-xs text-muted-foreground underline" onclick={addCc}>+ add</button>
    </div>
    <div class="space-y-2">
      {#each crossConditions as c, i (i)}
        <div class="flex items-center gap-2 rounded-lg border p-2 font-mono text-sm">
          <Input class="w-16" value={c.left} onchange={(e) => patchCc(i, { left: inputStr(e) })} />
          <span class="text-xs">.</span>
          <Input class="w-20" value={c.leftAttr} onchange={(e) => patchCc(i, { leftAttr: inputStr(e) })} />
          <Select options={CC_OPS.map((o) => ({ value: o, label: o }))} value={c.op} onchange={(e) => patchCc(i, { op: selectValue(e, '=') })} />
          <Input class="w-16" value={c.right} onchange={(e) => patchCc(i, { right: inputStr(e) })} />
          <span class="text-xs">.</span>
          <Input class="w-20" value={c.rightAttr} onchange={(e) => patchCc(i, { rightAttr: inputStr(e) })} />
          <button type="button" class="text-xs text-destructive underline" onclick={() => removeCc(i)}>x</button>
        </div>
      {:else}
        <p class="text-xs text-muted-foreground">No cross-conditions.</p>
      {/each}
    </div>
  </div>
</div>
