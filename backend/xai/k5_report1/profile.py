"""The profile of Report 1: every step of the plan, for a technical reader.

Sections, in order: the event and its rule, what was observed, why it was flagged, confidences
and reinforcement between modalities, method and provenance, limits. The system writes the last
two: they hold only facts with a fixed sentence. What was observed ends with the key frame of the
detection: the LLM says when it is, and the system shows its image below, with a caption.
"""

from xai.contract.plan import StepType
from xai.reporting.profile import ReportProfile, SectionSpec

REPORT1 = ReportProfile(
    number=1,
    name="report1",
    only_in_report2=False,
    sections=(
        SectionSpec("Event and rule", step_types=(StepType.CONCLUSION,)),
        SectionSpec("What was observed", step_types=(StepType.OBSERVATION, StepType.CONTEXT)),
        SectionSpec(
            "Why it was flagged", step_types=(StepType.CONDITION, StepType.TEMPORAL, StepType.IDENTITY)
        ),
        SectionSpec(
            "Confidences and reinforcement",
            step_types=(StepType.REINFORCEMENT,),
            step_ids=("s_prov_confidences", "s_prov_modality_association"),
        ),
        SectionSpec("Method and provenance", step_types=(StepType.PROVENANCE,), by_system=True),
        SectionSpec("Limits", step_types=(StepType.LIMIT,), by_system=True),
    ),
    cites_rule_definition=True,
    figure_section="What was observed",
)
