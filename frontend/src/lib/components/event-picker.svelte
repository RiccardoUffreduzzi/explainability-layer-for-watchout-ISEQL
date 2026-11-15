<script lang="ts">
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import Select from '$lib/components/ui/select.svelte';
  import Checkbox from '$lib/components/ui/checkbox.svelte';
  import type { Condition, Deltas, EventTypeInfo, Unit } from '$lib/types';
  import { inputInt } from '$lib/dom-helpers';
  import { Database } from 'lucide-svelte';

  type Props = {
    condition: Condition;
    deltas: Deltas;
    eventTypes: EventTypeInfo[];
    defaultDeltas: Deltas;
    onChangeDeltas: (d: Deltas) => void;
    disabled?: boolean;
    unit: Unit;
    fps?: number;
  };
  let {
    condition,
    deltas = $bindable(),
    eventTypes,
    defaultDeltas,
    onChangeDeltas,
    disabled = false,
    unit,
    fps = 0,
  }: Props = $props();

  const STRICTNESS_OPTIONS = [
    { value: '<=', label: '<=' },
    { value: '>=', label: '>=' },
    { value: '<', label: '<' },
    { value: '>', label: '>' },
  ];

  type ParamField = {
    key: string;
    kind: 'delta' | 'epsilon' | 'eta' | 'zeta' | 'rho';
    modality: 'visual' | 'audio';
  };

  const FIELD_ORDER: ParamField['kind'][] = ['delta', 'epsilon', 'zeta', 'eta', 'rho'];

  const eventParamFields = $derived(
    eventTypes
      .map((e) => {
        const fields: ParamField[] = [];
        const modalityFields: Record<'visual' | 'audio', Array<['delta_visual' | 'delta_audio' | 'epsilon_visual' | 'epsilon_audio' | 'eta_visual' | 'eta_audio' | 'zeta_visual' | 'zeta_audio' | 'rho_visual' | 'rho_audio', string | null]>> = {
          visual: [
            ['delta_visual', e.delta_visual],
            ['epsilon_visual', e.epsilon_visual],
            ['zeta_visual', e.zeta_visual],
            ['eta_visual', e.eta_visual],
            ['rho_visual', e.rho_visual],
          ],
          audio: [
            ['delta_audio', e.delta_audio],
            ['epsilon_audio', e.epsilon_audio],
            ['zeta_audio', e.zeta_audio],
            ['eta_audio', e.eta_audio],
            ['rho_audio', e.rho_audio],
          ],
        };
        for (const [modality, list] of Object.entries(modalityFields) as Array<['visual' | 'audio', [string, string | null][]]>) {
          for (const [kind, key] of list) {
            if (key) {
              fields.push({ key, kind: kind.split('_')[0] as ParamField['kind'], modality });
            }
          }
        }
        return { event: e, fields };
      })
      .filter(({ fields }) => fields.length > 0)
  );

  const visibleEvents = $derived(
    eventParamFields.filter(({ event, fields }) => {
      if (condition === 'C') return true;
      const wanted = condition === 'A' ? 'visual' : 'audio';
      return fields.some((f) => f.modality === wanted);
    })
  );

  function visibleFields(fields: ParamField[]): ParamField[] {
    if (condition === 'C') return fields;
    const wanted = condition === 'A' ? 'visual' : 'audio';
    return fields.filter((f) => f.modality === wanted);
  }

  function numValue(key: string) {
    const v = deltas[key] ?? defaultDeltas[key] ?? 0;
    return typeof v === 'number' ? v : 0;
  }

  function strValue(key: string, fallback: string) {
    const v = deltas[key];
    return typeof v === 'string' ? v : fallback;
  }

  const isUnbounded = (key: string) => deltas[key] === 'inf';

  function patch(p: Deltas) {
    onChangeDeltas({ ...deltas, ...p });
  }

  const fieldLabel = (f: ParamField) => {
    const symbol = f.kind === 'delta' ? 'δ' : f.kind === 'zeta' ? 'ζ' : f.kind === 'eta' ? 'η' : 'ρ';
    return symbol;
  };

  const fieldId = (f: ParamField) => `${f.kind}-${f.key}`;

  const MODALITY_GROUPS: ParamField['modality'][] = ['visual', 'audio'];

  const frameHint = (f: ParamField) => {
    if (unit !== 'seconds' || fps <= 0) return '';
    if (isUnbounded(f.key)) return '';
    const v = numValue(f.key);
    return `≈ ${Math.round(v * fps)} frames`;
  };
</script>

<div class="rounded-lg border border-border bg-muted/30 p-3 text-xs mb-4">
  <p class="flex items-center gap-1 font-medium text-foreground">
    <Database class="size-3.5 text-info" /> All events auto-detected via ISEQL SQL queries
  </p>
</div>

{#if visibleEvents.length}
  <div class="space-y-2">
    {#each visibleEvents as { event, fields }}
      {@const shown = visibleFields(fields)}
      {#if shown.length}
        {@const hasVisual = shown.some((f) => f.modality === 'visual')}
        {@const hasAudio = shown.some((f) => f.modality === 'audio')}
        <div class="rounded-lg border border-border bg-muted/30 p-2">
          <p class="text-xs font-medium text-foreground mb-1.5">{event.id}</p>
          {#each MODALITY_GROUPS as modality}
            {@const group = shown.filter((f) => f.modality === modality)}
            {#if group.length}
              {#if hasVisual && hasAudio}
                <p class="text-[11px] font-medium text-muted-foreground mt-1.5 mb-1 first:mt-0 uppercase tracking-wide">
                  {modality}
                </p>
              {/if}
              <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {#each FIELD_ORDER as kind}
                  {#each group.filter((f) => f.kind === kind) as f}
                    {#if f.kind === 'zeta' || f.kind === 'eta'}
                      <Field>
                        <Label for={fieldId(f)} title={f.key}>{fieldLabel(f)}</Label>
                        <Select id={fieldId(f)}
                          options={STRICTNESS_OPTIONS}
                          value={strValue(f.key, '<=')}
                          disabled={disabled}
                          onchange={(ev) => patch({ [f.key]: (ev.currentTarget as HTMLSelectElement).value })} />
                      </Field>
                    {:else if f.kind === 'delta' || f.kind === 'epsilon'}
                      <Field>
                        <Label for={fieldId(f)} title={f.key}>{fieldLabel(f)}</Label>
                        <div class="flex items-center gap-2">
                          <Input id={fieldId(f)} type="number" min="0"
                            value={isUnbounded(f.key) ? '' : numValue(f.key)}
                            placeholder={isUnbounded(f.key) ? '∞' : undefined}
                            disabled={disabled || isUnbounded(f.key)}
                            onchange={(ev) => patch({ [f.key]: inputInt(ev, 0) })} />
                          <label class="flex items-center gap-1 text-[11px] text-muted-foreground whitespace-nowrap">
                            <Checkbox checked={isUnbounded(f.key)}
                              disabled={disabled}
                              onCheckedChange={(c) => {
                                if (c) patch({ [f.key]: 'inf' });
                                else {
                                  const def = defaultDeltas[f.key];
                                  patch({ [f.key]: typeof def === 'number' ? def : 5 });
                                }
                              }} />
                            ∞
                          </label>
                        </div>
                        {#if !isUnbounded(f.key) && frameHint(f)}<p class="mt-0.5 text-[11px] text-muted-foreground">{frameHint(f)}</p>{/if}
                      </Field>
                    {:else}
                      <Field>
                        <Label for={fieldId(f)} title={f.key}>{fieldLabel(f)}</Label>
                        <Input id={fieldId(f)} type="number" min="0" value={numValue(f.key)}
                          onchange={(ev) => patch({ [f.key]: inputInt(ev, 0) })}
                          {disabled} />
                        {#if frameHint(f)}<p class="mt-0.5 text-[11px] text-muted-foreground">{frameHint(f)}</p>{/if}
                      </Field>
                    {/if}
                  {/each}
                {/each}
              </div>
            {/if}
          {/each}
        </div>
      {/if}
    {/each}
  </div>
{/if}
