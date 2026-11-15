<script lang="ts">
  import Input from '$lib/components/ui/input.svelte';
  import Label from '$lib/components/ui/label.svelte';
  import Select from '$lib/components/ui/select.svelte';
  import Field from '$lib/components/ui/field.svelte';
  import type { AudioConfig } from '$lib/types';
  import { inputFloat, selectValue } from '$lib/dom-helpers';

  const DEFAULT_AUDIO_MODELS: Record<string, string> = {
    huggingface: 'Qwen/Qwen2-Audio-7B-Instruct',
    panns: 'CNN14',
  };
  const PROVIDER_LABELS: Record<string, string> = {
    panns: 'PANNs',
    huggingface: 'HuggingFace LALM',
  };
  const DEFAULT_CONFIGS: Record<string, { window: number; hop: number }> = {
    huggingface: { window: 5.0, hop: 2.5 },
    panns: { window: 2.5, hop: 1.25 },
  };
  const QUANTIZATION_OPTIONS = [
    { value: 'none', label: 'None (full precision)' },
    { value: '8bit', label: '8-bit' },
    { value: '4bit', label: '4-bit (recommended)' },
  ];

  type Props = {
    value: AudioConfig;
    onChange: (v: AudioConfig) => void;
    disabled?: boolean;
    availableProviders?: string[];
  };
  let { value = $bindable(), onChange, disabled = false, availableProviders = ['panns', 'huggingface'] }: Props = $props();

  let provider = $derived(value.provider);
  let isHuggingface = $derived(provider === 'huggingface');

  function patch(p: Partial<AudioConfig>) {
    onChange({ ...value, ...p });
  }

  $effect(() => {
    if (availableProviders.length > 0 && !provider) {
      const p = availableProviders[0];
      patch({ provider: p, model: DEFAULT_AUDIO_MODELS[p] || '', quantization: 'none' });
    }
  });

  function handleProviderChange(e: Event) {
    const newProvider = selectValue(e);
    const cfg = DEFAULT_CONFIGS[newProvider] || DEFAULT_CONFIGS.panns;
    patch({ provider: newProvider, model: DEFAULT_AUDIO_MODELS[newProvider] || '', window: cfg.window, hop: cfg.hop });
  }

  let providerOptions = $derived(
    availableProviders.map(p => ({
      value: p,
      label: PROVIDER_LABELS[p] || p,
    }))
  );

</script>

<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
  <Field>
    <Label for="audio-provider">Audio Provider</Label>
    <Select
      id="audio-provider"
      options={providerOptions}
      value={provider}
      onchange={handleProviderChange}
      {disabled}
    />
  </Field>

  <Field>
    <Label for="audio-model">Model</Label>
    <div class="flex h-9 items-center rounded-lg border border-input bg-muted px-3 text-sm text-muted-foreground">
      {DEFAULT_AUDIO_MODELS[provider] || ''}
    </div>
  </Field>

  <Field>
    <Label for="audio-window">Window (seconds)</Label>
    <Input id="audio-window" type="number" min="0.1" step="0.1"
      value={value.window}
      onchange={(e) => patch({ window: inputFloat(e, 2.5) })}
      {disabled}
    />
  </Field>

  <Field>
    <Label for="audio-hop">Hop (seconds)</Label>
    <Input id="audio-hop" type="number" min="0.1" step="0.05"
      value={value.hop}
      onchange={(e) => patch({ hop: inputFloat(e, 1.25) })}
      {disabled}
    />
  </Field>

  {#if isHuggingface}
    <Field class="lg:col-span-2">
      <Label for="audio-quantization">Quantization</Label>
      <Select
        id="audio-quantization"
        options={QUANTIZATION_OPTIONS}
        value={value.quantization}
        onchange={(e) => patch({ quantization: (e.currentTarget as HTMLSelectElement).value })}
        {disabled}
      />
    </Field>
  {/if}
</div>
