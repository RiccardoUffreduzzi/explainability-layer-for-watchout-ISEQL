# Detection report: handoff

## Event and rule

The system detected a handoff with rule `handoff/A`, from 0:01 to 0:08 (frames 24–192). In plain words, an object passing from one person to another was detected. In the rule, M1.arg1 is the man in a dark blue hoodie, M2.arg1 is the man in a grey jacket and dark trousers, and M1.arg2 is the cardboard box. The rule that was executed:

    π_{M1.arg1, M2.arg1, M1.arg2, M1.st, M2.et} (
      σ_{M1.arg1≠M2.arg1 ∧ M1.arg2=M2.arg2} (
        σ_{pred="carrying" ∧ arg1="person" ∧ arg2="object"}(M1)
        Bef(δ:∞; ζ:<=, ρ:0)
        σ_{pred="carrying" ∧ arg1="person" ∧ arg2="object"}(M2)
      ))

## What was observed

From 0:01 to 0:04 (frames 24–96), the video model saw a man in a dark blue hoodie carrying a cardboard box, selected by `σ_{pred="carrying" ∧ arg1="person" ∧ arg2="object"}(M1)`. From 0:05 to 0:08 (frames 120–192), it saw a man in a grey jacket and dark trousers carrying the cardboard box, selected by `σ_{pred="carrying" ∧ arg1="person" ∧ arg2="object"}(M2)`. For the video model, carrying means: "The person is holding, carrying, or transporting any object of class 'object' (package, suitcase, bag, backpack). Report for ANY person touching or holding a transportable item, even briefly."

## Why it was flagged

The first carrying ends before the second one starts: operator `Bef(δ:∞; ζ:<=, ρ:0)`, defined as `r.Te ζ s.Ts, s.Ts − r.Te ≤ δ`. With δ = ∞, the second carrying can start at any time after the first one ends. The two people are different (`M1.arg1≠M2.arg1`): the man in a dark blue hoodie and the man in a grey jacket and dark trousers. The object is the same in both intervals (`M1.arg2=M2.arg2`): the cardboard box.

## Method and provenance

The video was sampled at 1.0 Hz: one frame in every 24 of a 24 fps video. Detections of the same relation at most 2 s apart were merged into one interval. The video model ran with temperature 0.0 and seed 42. Detection mode: visual. Rule parameters: rule defaults. WatchOut's lineage of this detection records M1 as the interval from 0:01 to 0:04 and M2 as the interval from 0:05 to 0:08. Source of truth: contract 0b3250dd6ebaf622b94210c179c0d4e91a1e95f270967450908742fb022cce54.

## Limits

These limits concern the conditions `M1.arg1≠M2.arg1` and `M1.arg2=M2.arg2` of the rule.

- The rule relies on matching the same person across frames (Re-ID).
- The evidence behind the Re-ID matches is not saved by the system.

These limits concern the whole detection.

- The system does not record a confidence value for visual detections.
- The system does not record what in the images led to each visual detection.
- Times are approximate: they depend on the sampling rate of the video analysis.
- Some information is not saved by the system and is reported as not available. Not available here: audio rule (EventSpec has no handoff/B); Re-ID similarity (Chroma stores the embeddings, not the match similarity); interval confidence (VisualPerInterval has no confidence column); key frames (this WatchOut version does not store key frames).
