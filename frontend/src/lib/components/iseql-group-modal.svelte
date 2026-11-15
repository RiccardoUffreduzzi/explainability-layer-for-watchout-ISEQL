<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import IseqlProjectionPanel from '$lib/components/iseql-projection-panel.svelte';
  import IseqlCrossconditionPanel from '$lib/components/iseql-crosscondition-panel.svelte';
  import type { BuilderGroup, FlatInterval, Unit } from '$lib/iseql-model';
  import { intervalLabel } from '$lib/iseql-model';
  import { inputStr } from '$lib/dom-helpers';

  type Props = {
    open: boolean;
    group: BuilderGroup | null;
    isNew: boolean;
    unit: Unit;
    onSave: (group: BuilderGroup) => void;
    onClose: () => void;
  };
  let { open, group, isNew, unit, onSave, onClose }: Props = $props();

  let draft = $state<BuilderGroup>({ name: '', intervals: [], ops: [], projection: null, crossConditions: [] });

  $effect(() => {
    if (open && group) {
      draft = {
        name: group.name,
        intervals: group.intervals.map((iv) => ({ ...iv, args: [...iv.args] })),
        ops: group.ops.map((o) => ({ ...o })),
        projection: group.projection ? [...group.projection] : null,
        crossConditions: group.crossConditions.map((c) => ({ ...c })),
      };
    }
  });

  const localFlat = $derived.by((): FlatInterval[] => {
    return draft.intervals.map((iv, i) => ({
      group: draft.name,
      localIndex: i,
      globalIndex: i,
      interval: iv,
    }));
  });
</script>

{#if open && group}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}>
    <div class="absolute inset-0 bg-black/40" onclick={onClose} role="presentation"></div>
    <div class="relative z-10 flex max-h-[85dvh] w-full max-w-md flex-col rounded-2xl border bg-card p-5 shadow-float" role="dialog" aria-modal="true" tabindex="-1">
      <div class="mb-3 text-sm font-semibold">{isNew ? 'New Set' : 'Set'}</div>

      <div class="min-h-0 flex-1 space-y-4 overflow-y-auto px-1">
        <Field>
          <Label>Name</Label>
          <Input class="h-8 w-full font-mono text-sm" value={draft.name} onchange={(e) => (draft = { ...draft, name: inputStr(e, draft.name) })} />
        </Field>

        <div>
          <div class="mb-1 text-xs font-semibold text-muted-foreground">Intervals</div>
          {#if draft.intervals.length}
            <div class="max-h-32 space-y-1 overflow-y-auto pr-1">
              {#each draft.intervals as iv, i (iv.id)}
                <div class="rounded border px-2 py-1 font-mono text-xs">
                  <span class="text-muted-foreground">M{i + 1}(arg1{iv.args.length > 1 ? ', arg2' : ''})</span>
                  <span class="mx-1 text-muted-foreground">=</span>
                  <span>{intervalLabel(iv)}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-xs text-muted-foreground">No intervals yet.</p>
          {/if}
        </div>

        <div>
          <IseqlProjectionPanel group={draft} {unit} onChange={(g) => (draft = g)} />
        </div>

        <div class="border-t pt-2">
          <IseqlCrossconditionPanel
            crossConditions={draft.crossConditions}
            flatIntervals={localFlat}
            onChange={(ccs) => (draft = { ...draft, crossConditions: ccs })}
          />
        </div>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={onClose}>Cancel</Button>
        <Button type="button" onclick={() => onSave(draft)}>Save</Button>
      </div>
    </div>
  </div>
{/if}
