<script lang="ts">
  import { detectOperator, OPERATOR_OPTIONS, type BuilderInterval, type BuilderOperator } from '$lib/iseql-model';
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import Select from '$lib/components/ui/select.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Checkbox from '$lib/components/ui/checkbox.svelte';
  import { inputStr, selectValue } from '$lib/dom-helpers';

  type Props = {
    open: boolean;
    a: BuilderInterval;
    b: BuilderInterval;
    initial: BuilderOperator;
    onSave: (op: BuilderOperator) => void;
    onClose: () => void;
  };
  let { open, a, b, initial, onSave, onClose }: Props = $props();

  let op = $state('auto');
  let delta = $state('');
  let epsilon = $state('');
  let zeta = $state('<=');
  let eta = $state('<=');
  let rho = $state('0');

  $effect(() => {
    if (!open) return;
    const det = detectOperator(a, b);
    op = initial.op === 'auto' ? det.op : initial.op;
    delta = initial.delta !== '' ? initial.delta : (det.delta != null ? String(det.delta) : '0');
    epsilon = initial.epsilon !== '' ? initial.epsilon : (det.epsilon != null ? String(det.epsilon) : '0');
    zeta = initial.zeta || '<=';
    eta = initial.eta || '<=';
    rho = initial.rho || '0';
  });

  const deltaUnbounded = $derived(delta === '∞');
  const epsilonUnbounded = $derived(epsilon === '∞');

  const usesDelta = $derived(['auto', 'Bef', 'Aft', 'SP', 'DJ', 'RDJ', 'LOJ', 'ROJ'].includes(op));
  const usesEpsilon = $derived(['auto', 'EF', 'DJ', 'RDJ', 'LOJ', 'ROJ'].includes(op));

  const STRICTNESS_OPTIONS = [
    { value: '<=', label: '<=' },
    { value: '>=', label: '>=' },
    { value: '<', label: '<' },
    { value: '>', label: '>' },
  ];

  function save() {
    onSave({ op, delta, epsilon, zeta, eta, rho });
  }
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}>
    <div class="absolute inset-0 bg-black/40" onclick={onClose} role="presentation"></div>
    <div
      class="relative z-10 w-full max-w-md rounded-2xl border bg-card p-5 shadow-float"
      role="dialog"
      aria-modal="true"
      tabindex="-1"
    >
      <div class="mb-3 flex items-center justify-between">
        <div class="text-sm font-semibold">Temporal operator</div>
      </div>

      <div class="mb-3 rounded-md border bg-muted/30 p-2 font-mono text-xs text-muted-foreground">
        σ <span class="text-foreground">{a.pred}</span> ··· σ <span class="text-foreground">{b.pred}</span>
      </div>

      <div class="space-y-3">
        <Field>
          <Label>Operator</Label>
          <Select options={OPERATOR_OPTIONS} value={op} onchange={(e) => (op = selectValue(e, 'auto'))} />
        </Field>

        {#if usesDelta}
          <Field>
            <Label>δ</Label>
            <div class="flex items-center gap-2">
              <Input class="font-mono" type="number" min="0" step="any" value={deltaUnbounded ? '' : delta} placeholder={deltaUnbounded ? '∞' : undefined} disabled={deltaUnbounded} onchange={(e) => (delta = inputStr(e))} />
              <label class="flex items-center gap-1 text-[11px] text-muted-foreground whitespace-nowrap">
                <Checkbox checked={deltaUnbounded} onCheckedChange={(c) => { delta = c ? '∞' : '0'; }} />
                ∞
              </label>
            </div>
          </Field>
        {/if}

        {#if usesEpsilon}
          <Field>
            <Label>ε</Label>
            <div class="flex items-center gap-2">
              <Input class="font-mono" type="number" min="0" step="any" value={epsilonUnbounded ? '' : epsilon} placeholder={epsilonUnbounded ? '∞' : undefined} disabled={epsilonUnbounded} onchange={(e) => (epsilon = inputStr(e))} />
              <label class="flex items-center gap-1 text-[11px] text-muted-foreground whitespace-nowrap">
                <Checkbox checked={epsilonUnbounded} onCheckedChange={(c) => { epsilon = c ? '∞' : '0'; }} />
                ∞
              </label>
            </div>
          </Field>
        {/if}

        <div class="grid grid-cols-2 gap-3">
          {#if usesDelta}
            <Field>
              <Label>ζ</Label>
              <Select options={STRICTNESS_OPTIONS} value={zeta} onchange={(e) => (zeta = selectValue(e, '<='))} />
            </Field>
          {/if}
          {#if usesEpsilon}
            <Field>
              <Label>η</Label>
              <Select options={STRICTNESS_OPTIONS} value={eta} onchange={(e) => (eta = selectValue(e, '<='))} />
            </Field>
          {/if}
        </div>

        <Field>
          <Label>ρ</Label>
          <Input class="font-mono" type="number" min="0" step="any" value={rho} onchange={(e) => (rho = inputStr(e))} />
        </Field>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={onClose}>Cancel</Button>
        <Button type="button" onclick={save}>Apply</Button>
      </div>
    </div>
  </div>
{/if}
