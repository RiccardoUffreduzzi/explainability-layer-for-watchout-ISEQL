# Detection report: vehicle collision

## Event and rule

The system detected an event with rule `vehicle_collision/C`, from 0:06 to 0:10 (frames 144–240), from the video branch of the rule. In plain words, the event is a vehicle collision. In the rule, M1.arg1 is the dark sedan. The rule that was executed:

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

From 0:06 to 0:10 (frames 144–240), the video model saw collision damage on the dark sedan, selected by `σ_{pred="vehicle_collision" ∧ arg1="vehicle"}(M1)`. For the video model, `vehicle_collision` means: "A vehicle has visible collision damage: broken windshield, dented hood or doors, deployed airbags, smoke from the hood, or another object embedded in the vehicle."

## Confidences and reinforcement

The event was detected by both video and audio, in the same time interval. The association of the two modalities is recorded as: detected by both video and audio, at overlapping times. The audio detection goes from 0:00 to 0:07.5, and the video detection of this row from 0:06 to 0:10.

## Method and provenance

The video was sampled at 1.0 Hz: one frame in every 24 of a 24 fps video. Detections of the same relation at most 2 s apart were merged into one interval. The video model ran with temperature 0.0 and seed 42. Detection mode: multimodal. Rule parameters: rule defaults. WatchOut's lineage of this detection records M1 as the interval from 0:06 to 0:10. Source of truth: contract 265bbc60d1fd06ddccd57fc4bce15bf61560cb69fb8ff5bfa613ceb64238df6d.

## Limits

These limits concern the whole detection.

- The system does not record a confidence value for visual detections.
- The system does not record what in the images led to each visual detection.
- Times are approximate: they depend on the sampling rate of the video analysis.
- Some information is not saved by the system and is reported as not available. Not available here: Re-ID similarity (Chroma stores the embeddings, not the match similarity); interval confidence (VisualPerInterval has no confidence column); key frames (this WatchOut version does not store key frames).
