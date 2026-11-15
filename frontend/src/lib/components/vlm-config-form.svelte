<script lang="ts">
  import { api } from '$lib/api';
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import * as Select from '$lib/components/ui/select/index.js';
  import Field from '$lib/components/ui/field.svelte';
  import type { VlmConfig } from '$lib/types';
  import { selectValue, inputInt, inputFloat } from '$lib/dom-helpers';
  import { cn } from '$lib/utils';
  import { Gauge, ScanEye, Zap } from 'lucide-svelte';

  const DEFAULT_GRID_ROWS = 2;
  const DEFAULT_GRID_COLS = 4;

  const PROVIDER_DEFAULTS: Record<string, { delay: number; max_retries: number }> = {
    gemini: { delay: 0.1, max_retries: 10 },
    mistral: { delay: 3.0, max_retries: 10 },
    zhipu: { delay: 10.0, max_retries: 10 },
    ollama: { delay: 0, max_retries: 0 },
  };

  const MODEL_DEFAULTS: Record<string, string> = {
    gemini: 'gemini-3.6-flash',
    mistral: 'ministral-14b-2512',
    openai: 'gpt-4o-mini',
    claude: 'claude-3-haiku-20240307',
    zhipu: 'glm-4v-flash',
  };

  const EMBED_PROVIDERS = ['huggingface', 'ollama'];

  const EMBED_MODEL_DEFAULTS: Record<string, string> = {
    huggingface: 'google/siglip-base-patch16-224',
    ollama: 'clip',
  };

  type Props = {
    value: VlmConfig;
    onChange: (v: VlmConfig) => void;
    disabled?: boolean;
    availableProviders?: string[];
    detectedFrameRate?: number;
  };
  let { value = $bindable(), onChange, disabled = false, availableProviders = [], detectedFrameRate = 0 }: Props = $props();

  let ollamaModels = $state<{ value: string; label: string }[]>([]);
  let ollamaModelsLoading = $state(false);
  let ollamaModelsFailed = $state(false);

  let isOllama = $derived(value.provider === 'ollama');
  let providerOptions = $derived(
    availableProviders.map(p => ({ value: p, label: p.charAt(0).toUpperCase() + p.slice(1) }))
  );
  let embedProviderOptions = $derived(
    EMBED_PROVIDERS.map(p => ({ value: p, label: p.charAt(0).toUpperCase() + p.slice(1) }))
  );
  let frameRateValue = $derived(
    detectedFrameRate > 0 ? `${Number(detectedFrameRate.toFixed(1))}` : null
  );

  function patch(p: Partial<VlmConfig>) {
    onChange({ ...value, ...p });
  }

  async function fetchOllamaModels() {
    if (ollamaModelsLoading) return;
    ollamaModelsLoading = true;
    ollamaModelsFailed = false;
    try {
      const resp = await api.get<{ models: { name: string; label: string }[]; error?: string }>(
        '/api/vlm/models?provider=ollama'
      );
      if (!resp.error && resp.models?.length) {
        ollamaModels = resp.models.map((m) => ({ value: m.name, label: m.label }));
      } else {
        ollamaModelsFailed = true;
      }
    } catch {
      ollamaModelsFailed = true;
    } finally {
      ollamaModelsLoading = false;
    }
  }

  $effect(() => {
    if (availableProviders.length > 0 && !value.provider) {
      const p = availableProviders[0];
      const d = PROVIDER_DEFAULTS[p] || { delay: 3, max_retries: 10 };
      const m = p === 'ollama' ? '' : (MODEL_DEFAULTS[p] || '');
      patch({ provider: p, model: m, vlm_delay: d.delay, max_retries: d.max_retries });
      if (p === 'ollama') fetchOllamaModels();
    }
    if (!value.embed_provider) {
      patch({ embed_provider: EMBED_PROVIDERS[0], embed_model: EMBED_MODEL_DEFAULTS[EMBED_PROVIDERS[0]] });
    }
  });

  $effect(() => {
    if (isOllama && ollamaModels.length === 0 && !ollamaModelsLoading && !ollamaModelsFailed) {
      fetchOllamaModels();
    }
  });

  function handleProviderChange(p: string) {
    const d = PROVIDER_DEFAULTS[p] || { delay: 3, max_retries: 10 };
    const m = p === 'ollama' ? '' : (MODEL_DEFAULTS[p] || '');
    patch({ provider: p, model: m, vlm_delay: d.delay, max_retries: d.max_retries });
    if (p === 'ollama') fetchOllamaModels();
  }

  function handleEmbedProviderChange(p: string) {
    patch({ embed_provider: p, embed_model: EMBED_MODEL_DEFAULTS[p] || '' });
  }
</script>

<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
  <Field>
    <Label for="vlm-provider">VLM Provider</Label>
    <Select.Root type="single" items={providerOptions} value={value.provider} onValueChange={(next: string | undefined) => next && handleProviderChange(next)} {disabled}>
      <Select.Trigger id="vlm-provider">
        {providerOptions.find((option) => option.value === value.provider)?.label ?? value.provider}
      </Select.Trigger>
      <Select.Content>
        {#each providerOptions as option (option.value)}
          <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>
  </Field>

  <Field>
    <Label for="vlm-model">Model</Label>
    {#if isOllama && ollamaModelsLoading}
      <div class="flex h-9 items-center rounded-md border border-input bg-muted px-3 text-sm text-muted-foreground">
        Detecting models...
      </div>
    {:else if isOllama && ollamaModelsFailed}
      <div class="flex h-9 items-center rounded-md border border-input bg-muted px-3 text-sm text-muted-foreground">
        Failed to detect models. <button type="button" class="ml-1 underline" onclick={fetchOllamaModels}>Retry</button>
      </div>
    {:else if isOllama && ollamaModels.length > 0}
      <Select.Root type="single" items={ollamaModels} value={value.model} onValueChange={(next: string | undefined) => patch({ model: next ?? '' })} {disabled}>
        <Select.Trigger id="vlm-model">
          {ollamaModels.find((option) => option.value === value.model)?.label ?? value.model}
        </Select.Trigger>
        <Select.Content>
          {#each ollamaModels as option (option.value)}
            <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    {:else}
      <Input
        id="vlm-model"
        type="text"
        placeholder={isOllama ? 'No models found, type name' : 'Type model name'}
        value={value.model}
        onchange={(e) => patch({ model: selectValue(e) })}
        {disabled}
      />
    {/if}
  </Field>

  <Field>
    <Label for="embed-provider">Embedding Provider</Label>
    <Select.Root type="single" items={embedProviderOptions} value={value.embed_provider} onValueChange={(next: string | undefined) => next && handleEmbedProviderChange(next)} {disabled}>
      <Select.Trigger id="embed-provider">
        {embedProviderOptions.find((option) => option.value === value.embed_provider)?.label ?? value.embed_provider}
      </Select.Trigger>
      <Select.Content>
        {#each embedProviderOptions as option (option.value)}
          <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>
  </Field>

  <Field>
    <Label for="embed-model">Model</Label>
    <Input
      id="embed-model"
      type="text"
      placeholder="HF model id, e.g. google/siglip-base-patch16-224"
      value={value.embed_model}
      onchange={(e) => patch({ embed_model: selectValue(e) })}
      {disabled}
    />
  </Field>

  <Field>
    <Label for="memory-n">Memory N (recency frames)</Label>
    <Input
      id="memory-n"
      type="number"
      min="1"
      value={value.memory_n}
      onchange={(e) => patch({ memory_n: inputInt(e, 3) })}
      {disabled}
    />
  </Field>

  <Field>
    <Label for="memory-top-k">Top-K similar</Label>
    <Input
      id="memory-top-k"
      type="number"
      min="1"
      value={value.memory_top_k}
      onchange={(e) => patch({ memory_top_k: inputInt(e, 5) })}
      {disabled}
    />
  </Field>


  <Field>
    <Label for="grid-rows">Grid Rows</Label>
    <Input id="grid-rows" type="number" min="1" max="10"
      value={value.grid_rows}
      onchange={(e) => patch({ grid_rows: inputInt(e, DEFAULT_GRID_ROWS) })}
      {disabled} />
  </Field>

  <Field>
    <Label for="grid-cols">Grid Columns</Label>
    <Input id="grid-cols" type="number" min="1" max="10"
      value={value.grid_cols}
      onchange={(e) => patch({ grid_cols: inputInt(e, DEFAULT_GRID_COLS) })}
      {disabled} />
  </Field>

  <Field class="lg:col-span-2">
    <Label for="frame-rate">Frame Rate</Label>
    <div
      id="frame-rate"
      class="flex h-9 items-center gap-1.5 rounded-lg border border-input bg-muted px-3 text-sm"
    >
      {#if frameRateValue !== null}
        <span class="font-mono text-foreground">{frameRateValue}</span>
        <span class="text-muted-foreground">frames per second (fps)</span>
      {:else}
        <span class="text-muted-foreground">Detected from the uploaded video</span>
      {/if}
    </div>
  </Field>

  <Field class="lg:col-span-2">
    <Label>Sampling Rate</Label>
    <div class="grid grid-cols-3 gap-1 rounded-lg border border-input bg-muted/30 p-1" role="group" aria-label="Sampling rate">
      <button
        type="button"
        class={cn(
          'flex min-w-0 flex-col items-center justify-center gap-0.5 rounded-md border border-transparent px-2 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
          value.sampling_rate === 0.5 ? 'border-sky-500/60 bg-sky-500/10 text-sky-700 shadow-sm dark:text-sky-300' : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'
        )}
        aria-pressed={value.sampling_rate === 0.5}
        onclick={() => patch({ sampling_rate: 0.5 })}
        {disabled}
      >
        <span class="flex min-w-0 items-center gap-1.5"><Zap class="size-3.5 shrink-0" /><span class="truncate">Fast</span></span>
        <span class="text-[10px] opacity-70">0.5 Hz</span>
      </button>
      <button
        type="button"
        class={cn(
          'flex min-w-0 flex-col items-center justify-center gap-0.5 rounded-md border border-transparent px-2 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
          value.sampling_rate === 1 ? 'border-sky-500/60 bg-sky-500/10 text-sky-700 shadow-sm dark:text-sky-300' : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'
        )}
        aria-pressed={value.sampling_rate === 1}
        onclick={() => patch({ sampling_rate: 1 })}
        {disabled}
      >
        <span class="flex min-w-0 items-center gap-1.5"><Gauge class="size-3.5 shrink-0" /><span class="truncate">Balanced</span></span>
        <span class="text-[10px] opacity-70">1 Hz</span>
      </button>
      <button
        type="button"
        class={cn(
          'flex min-w-0 flex-col items-center justify-center gap-0.5 rounded-md border border-transparent px-2 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
          value.sampling_rate === 2 ? 'border-sky-500/60 bg-sky-500/10 text-sky-700 shadow-sm dark:text-sky-300' : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'
        )}
        aria-pressed={value.sampling_rate === 2}
        onclick={() => patch({ sampling_rate: 2 })}
        {disabled}
      >
        <span class="flex min-w-0 items-center gap-1.5"><ScanEye class="size-3.5 shrink-0" /><span class="truncate">Detailed</span></span>
        <span class="text-[10px] opacity-70">2 Hz</span>
      </button>
    </div>
  </Field>

  {#if !isOllama}
    <Field class="lg:col-span-2">
      <Label for="vlm-delay">Delay between VLM calls (seconds)</Label>
      <Input id="vlm-delay" type="number" min="0" step="0.1"
        value={value.vlm_delay}
        onchange={(e) => patch({ vlm_delay: inputFloat(e, 3) })}
        {disabled} />
    </Field>

    <Field class="lg:col-span-2">
      <Label for="vlm-max-retries">Max retries on rate limit</Label>
      <Input id="vlm-max-retries" type="number" min="0" max="20"
        value={value.max_retries}
        onchange={(e) => patch({ max_retries: inputInt(e, 10) })}
        {disabled} />
    </Field>
  {/if}
</div>
