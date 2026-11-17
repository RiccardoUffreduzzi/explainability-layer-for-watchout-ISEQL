# Detection report: fight

## Event and rule

The system detected an event with rule `fight/A`, from 0:00 to 0:05 (frames 0–120). In plain words, the event is a fight. In the rule, M1.arg1 is the man in a grey hooded sweatshirt and khaki pants and M1.arg2 is the man in a dark jacket and blue jeans. The rule that was executed:

    π_{M1.arg1, M1.arg2, M1.st, M1.et} (
      σ_{M1.arg1≠M1.arg2} (
        σ_{pred="physical_altercation" ∧ arg1="person" ∧ arg2="person"}(M1)
      ))

## What was observed

From 0:00 to 0:05 (frames 0–120), the video model saw the man in a grey hooded sweatshirt and khaki pants and the man in a dark jacket and blue jeans fight, selected by `σ_{pred="physical_altercation" ∧ arg1="person" ∧ arg2="person"}(M1)`. For the video model, `physical_altercation` means: "Two or more people are involved in aggressive behavior: fighting, pushing, hitting, punching, making aggressive gestures, or throwing objects at each other. Include IDs of all people involved."

## Why it was flagged

The two arguments of the same interval are different people (`M1.arg1≠M1.arg2`, defined as `left ≠ right`): the man in a grey hooded sweatshirt and the man in a dark jacket.

## Method and provenance

The video was sampled at 1.0 Hz: one frame in every 24 of a 24 fps video. Detections of the same relation at most 2 s apart were merged into one interval. The video model ran with temperature 0.0 and seed 42. Detection mode: visual. Rule parameters: rule defaults. WatchOut's lineage of this detection records M1 as the interval from 0:00 to 0:05. Source of truth: contract 9118e7309af73ec54a32bdd623eb6257d12686195fe7f20c1f5b3e90a2ed935f.

## Limits

These limits concern the conditions `M1.arg1≠M1.arg2` of the rule.

- The rule relies on matching the same person across frames (Re-ID).
- The evidence behind the Re-ID matches is not saved by the system.

These limits concern the whole detection.

- The system does not record a confidence value for visual detections.
- The system does not record what in the images led to each visual detection.
- Times are approximate: they depend on the sampling rate of the video analysis.
- Some information is not saved by the system and is reported as not available. Not available here: Re-ID similarity (Chroma stores the embeddings, not the match similarity); interval confidence (VisualPerInterval has no confidence column); key frames (this WatchOut version does not store key frames).
