# Detection report: gunshot or explosion

## Event and rule

The system detected an event with rule `gunshot_or_explosion/A`, from 0:05 to 0:10 (frames 120–240). In plain words, the event is a gunshot or an explosion. In the rule, M1.arg1 is the silver SUV parked near a building. The rule that was executed:

    π_{M1.arg1, M1.st, M1.et} (
      σ_{(pred="gunshot_visible" ∧ arg1="person") ∨ (pred="explosion_visible" ∧ (arg1="vehicle" ∨ arg1="object"))}(M1)
    )

## What was observed

The rule accepts either of two predicates, `gunshot_visible` or `explosion_visible`, as `σ_{(pred="gunshot_visible" ∧ arg1="person") ∨ (pred="explosion_visible" ∧ (arg1="vehicle" ∨ arg1="object"))}(M1)` says. From 0:05 to 0:10 (frames 120–240), the video model saw an explosion at the silver SUV: the predicate of the interval is `explosion_visible`. For the video model, `explosion_visible` means: "A visible explosion: fireball, large smoke cloud, debris flying through the air, or shattered windows. Report the VehicleID or nearest object ID."

## Method and provenance

The video was sampled at 1.0 Hz: one frame in every 24 of a 24 fps video. Detections of the same relation at most 2 s apart were merged into one interval. The video model ran with temperature 0.0 and seed 42. Detection mode: visual. Rule parameters: rule defaults. WatchOut's lineage of this detection records M1 as the interval from 0:05 to 0:10. Source of truth: contract cb20c646d57952bb9ecf8e02b7f100314d143154ee48685c704841f93bd977a7.

## Limits

These limits concern the whole detection.

- The system does not record a confidence value for visual detections.
- The system does not record what in the images led to each visual detection.
- Times are approximate: they depend on the sampling rate of the video analysis.
- Some information is not saved by the system and is reported as not available. Not available here: Re-ID similarity (Chroma stores the embeddings, not the match similarity); interval confidence (VisualPerInterval has no confidence column); key frames (this WatchOut version does not store key frames).
