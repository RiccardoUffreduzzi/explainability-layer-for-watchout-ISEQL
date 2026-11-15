<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import Input from '$lib/components/ui/input.svelte';
  import Select from '$lib/components/ui/select.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import ExprEditor from '$lib/components/expr-editor.svelte';
  import type { Condition } from '$lib/types';
  import { parseBoolExpr, boolTextFromSelection, tokenizeBoolExpr, predicateLabel, type Vocabulary, type EditorToken } from '$lib/iseql-model';
  import { inputInt, selectValue } from '$lib/dom-helpers';

  interface IntervalDraft {
    pred: string;
    args: string[];
    ts: number;
    te: number;
    group: string;
    selection?: Record<string, unknown> | null;
  }

  type Props = {
    open: boolean;
    condition: Condition;
    vocabulary: Vocabulary;
    groupOptions: string[];
    initial: IntervalDraft | null;
    onSave: (d: IntervalDraft) => void;
    onClose: () => void;
    onOpenPredicate?: (name: string, modality: 'visual' | 'audio') => void;
  };
  let { open, condition, vocabulary, groupOptions, initial, onSave, onClose, onOpenPredicate = () => undefined }: Props = $props();

  let text = $state('');
  let ts = $state(0);
  let te = $state(10);
  let group = $state('');
  let confirm = $state<{ name: string; modality: 'visual' | 'audio' } | null>(null);

  $effect(() => {
    if (!open || !initial) return;
    text = boolTextFromSelection(initial.selection, initial.pred);
    ts = initial.ts;
    te = initial.te;
    group = initial.group;
  });

  const predOptions = $derived(
    vocabulary.predicates
      .filter((p) => condition === 'C' || (condition === 'A' ? p.modality === 'visual' : p.modality === 'audio'))
      .map((p) => ({ value: p.name, label: p.name })),
  );

  function vocabSlots(name: string): string[][] {
    return vocabulary.predicates.find((p) => p.name === name)?.args ?? [];
  }

  function labelOf(name: string): string {
    return predicateLabel(name, vocabSlots(name));
  }

  function openPredicate(name: string) {
    const modality = vocabulary.predicates.find((p) => p.name === name)?.modality ?? 'visual';
    confirm = { name, modality };
  }

  function unionArgsMap(preds: string[]): Record<string, string[]> {
    const map: Record<string, string[]> = {};
    preds.forEach((p) => {
      vocabSlots(p).forEach((slot, i) => {
        if (!slot.length) return;
        const k = String(i + 1);
        (map[k] ??= []).push(...slot);
      });
    });
    for (const k of Object.keys(map)) map[k] = [...new Set(map[k])];
    return map;
  }

  function unionArgs(preds: string[]): string[] {
    const map = unionArgsMap(preds);
    return Object.keys(map)
      .sort((a, b) => Number(a) - Number(b))
      .map((k) => map[k][0] ?? '')
      .filter(Boolean);
  }

  function predArgsMap(preds: string[]): Record<string, string[][]> {
    return Object.fromEntries(preds.map((p) => [p, vocabSlots(p)]));
  }

  const tokens = $derived<EditorToken[] | null>(mapTokens(tokenizeBoolExpr(text)));
  const parsed = $derived(parseBoolExpr(text));

  function mapTokens(tk: ReturnType<typeof tokenizeBoolExpr>): EditorToken[] | null {
    if (!tk) return null;
    return tk.map((t) => (t.type === 'pred' ? { type: 'item' as const, name: t.name } : t));
  }

  function onText(next: string) {
    text = next;
  }

  function save() {
    if (!parsed || !parsed.length) return;
    const allPreds = [...new Set(parsed.flat())];
    const first = allPreds[0];
    let selection: Record<string, unknown> | null = null;
    if (parsed.length === 1 && parsed[0].length === 1) {
      const slots = vocabSlots(first);
      selection = slots.some((s) => s.length > 1)
        ? { preds: [first], args: unionArgsMap([first]), pred_args: { [first]: slots } }
        : null;
    } else if (parsed.length === 1) {
      selection = { preds: parsed[0], args: unionArgsMap(parsed[0]), pred_args: predArgsMap(parsed[0]) };
    } else {
      selection = {
        branches: parsed.map((b) => ({
          preds: b,
          args: unionArgsMap(b),
          pred_args: predArgsMap(b),
        })),
      };
    }
    onSave({ pred: first, args: unionArgs(allPreds), ts, te, group, selection });
  }
</script>

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') onClose(); }}>
    <div class="absolute inset-0 bg-black/40" onclick={onClose} role="presentation"></div>
    <div class="relative z-10 w-full max-w-md rounded-2xl border bg-card p-5 shadow-float" role="dialog" aria-modal="true" tabindex="-1">
      <div class="mb-3 flex items-center justify-between">
        <div class="text-sm font-semibold">Interval</div>
      </div>

      <div class="space-y-3">
        <Field>
          <Label>Predicates Expression</Label>
          <ExprEditor {text} {tokens} options={predOptions.map((p) => p.value)} operators={['∨']} kind="pred" {onText} onOpen={openPredicate} {labelOf} />
        </Field>
        <div class="grid grid-cols-2 gap-3">
          <Field>
            <Label>Start</Label>
            <Input type="number" min="0" value={ts} onchange={(e) => (ts = inputInt(e, 0))} />
          </Field>
          <Field>
            <Label>End</Label>
            <Input type="number" min="0" value={te} onchange={(e) => (te = inputInt(e, 10))} />
          </Field>
        </div>
        <Field>
          <Label>Set</Label>
          <Select options={[{ value: '', label: 'No set' }, ...groupOptions.map((g) => ({ value: g, label: g }))]} value={group} onchange={(e) => (group = selectValue(e, ''))} />
        </Field>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={onClose}>Cancel</Button>
        <Button type="button" onclick={save}>Save</Button>
      </div>
    </div>
  </div>
{/if}

{#if confirm}
  <div class="fixed inset-0 z-[60] flex items-center justify-center p-4" role="presentation" onkeydown={(e) => { if (e.key === 'Escape') confirm = null; }}>
    <div class="absolute inset-0 bg-black/40" onclick={() => (confirm = null)} role="presentation"></div>
    <div class="relative z-10 w-full max-w-sm rounded-2xl border bg-card p-5 shadow-float" role="dialog" aria-modal="true" tabindex="-1">
      <div class="mb-2 text-sm font-semibold">Open configuration</div>
      <p class="mb-3 text-xs text-muted-foreground">
        Open the {confirm.modality === 'audio' ? 'audio class' : 'relation'} configuration for <span class="font-mono text-foreground">{confirm.name}</span>?
      </p>
      <div class="flex justify-end gap-2">
        <Button type="button" variant="ghost" onclick={() => (confirm = null)}>Cancel</Button>
        <Button type="button" onclick={() => { onOpenPredicate(confirm!.name, confirm!.modality); confirm = null; }}>Open</Button>
      </div>
    </div>
  </div>
{/if}
