# Detection report: suspicious near vehicle

## Event and rule

The system detected an event with rule `suspicious_near_vehicle/A`, from 0:02 to 0:07 (frames 48–168). In plain words, a person lingered suspiciously near a vehicle. In the rule, M1.arg1 is the person in a dark hooded jacket and M1.arg2 is the silver sedan. The rule that was executed:

    π_{M1.arg1, M1.arg2, M1.st, M1.et} (
      σ_{(M1.et − M1.st) >= 3} (
        σ_{pred="suspicious_near_vehicle" ∧ arg1="person" ∧ arg2="vehicle"}(M1)
      ))

## What was observed

From 0:02 to 0:07 (frames 48–168), the video model saw the person in a dark hooded jacket lingering suspiciously around the silver sedan, selected by `σ_{pred="suspicious_near_vehicle" ∧ arg1="person" ∧ arg2="vehicle"}(M1)`. For the video model, `suspicious_near_vehicle` means: "A person is lingering suspiciously around a parked vehicle without entering it: peering into windows with hands cupped around the eyes, crouching near or examining the tires/body, trying door or trunk handles, or pacing/circling the vehicle while repeatedly looking around. Report only when the person is NOT entering or driving the vehicle."

## Why it was flagged

The observation lasts at least 3 seconds, as the condition `(M1.et − M1.st) >= 3` requires (defined as `(end − start) ≥ value`).

## Method and provenance

The video was sampled at 1.0 Hz: one frame in every 24 of a 24 fps video. Detections of the same relation at most 2 s apart were merged into one interval. The video model ran with temperature 0.0 and seed 42. Detection mode: visual. Rule parameters: rule defaults. WatchOut's lineage of this detection records M1 as the interval from 0:02 to 0:07. Source of truth: contract 3a7ba6788633811d9473c91f2d2cef9b65a5598a171c0058cf4530c0441c220e.

## Limits

These limits concern the whole detection.

- The system does not record a confidence value for visual detections.
- The system does not record what in the images led to each visual detection.
- Times are approximate: they depend on the sampling rate of the video analysis.
- Some information is not saved by the system and is reported as not available. Not available here: audio rule (EventSpec has no suspicious_near_vehicle/B); Re-ID similarity (Chroma stores the embeddings, not the match similarity); interval confidence (VisualPerInterval has no confidence column); key frames (this WatchOut version does not store key frames).
