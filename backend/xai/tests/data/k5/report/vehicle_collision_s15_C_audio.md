# Detection report: vehicle collision

## Event and rule

The system detected an event with rule `vehicle_collision/C`, from 0:00 to 0:07.5 (frames 0–180), from the audio branch of the rule. In plain words, the event is a vehicle collision. The branch projects `π_{M1.st, M2.et}`: the start of M1 and the end of M2. The rule that was executed:

    π_{M1.st, M2.et} (
      σ_{(pred="horn") ∨ (pred="skidding")}(M1)
      SP(δ:∞; ζ:<=, ρ:0)
      σ_{(pred="impact") ∨ (pred="glass_breaking")}(M2)
    )
    ∪
    π_{M1.arg1, M1.st, M1.et} (
      σ_{pred="vehicle_collision" ∧ arg1="vehicle"}(M1)
    )

## What was observed

From 0:00 to 0:05 (frames 0–120), the audio model heard a horn: the class of the interval is `horn`, one of the two classes `σ_{(pred="horn") ∨ (pred="skidding")}(M1)` accepts. For the system, `horn` means: "WatchOut assigns this class when the audio model answers with one of: horn, honk, honking." From 0:02.5 to 0:07.5 (frames 60–180), it heard glass breaking: the class of the interval is `glass_breaking`, one of the two classes `σ_{(pred="impact") ∨ (pred="glass_breaking")}(M2)` accepts. For the system, `glass_breaking` means: "WatchOut assigns this class when the audio model answers with one of: glass, glass_breaking, shatter, shattering."

## Why it was flagged

The glass breaking starts while the horn is ongoing: operator `SP(δ:∞; ζ:<=, ρ:0)`, defined as `r.Ts ζ s.Ts < r.Te, s.Ts − r.Ts ≤ δ`. With δ = ∞, the second sound can start at any time while the first one is ongoing.

## Confidences and reinforcement

The event was detected by both video and audio, in the same time interval. The association of the two modalities is recorded as: detected by both video and audio, at overlapping times. The audio model gave a confidence of 1.0 to the horn and of 1.0 to the glass breaking.

## Method and provenance

The video was sampled at 1.0 Hz: one frame in every 24 of a 24 fps video. Detections of the same relation at most 2 s apart were merged into one interval. The video model ran with temperature 0.0 and seed 42. Detection mode: multimodal. Rule parameters: rule defaults. WatchOut's lineage of this detection records M1 as the interval from 0:00 to 0:05 and M2 as the interval from 0:02.5 to 0:07.5. Source of truth: contract b2689362bb2e2ff726798b0e652c16138e8f244d635950aa4a0d829d9447f82f.

## Limits

These limits concern the whole detection.

- Times are approximate: they depend on the sampling rate of the video analysis.
- An audio detection does not say who or what produced the sound.
- Some information is not saved by the system and is reported as not available. Not available here: key frames (this WatchOut version does not store key frames).
