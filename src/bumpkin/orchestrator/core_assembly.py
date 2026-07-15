from __future__ import annotations

from bumpkin.orchestrator import output_assembly as orchestrator_output_assembly
from bumpkin.orchestrator.state import CorePipelineState
from bumpkin.prompt_pack import PromptPackMetadata

CoreAnalysisResult = orchestrator_output_assembly.CoreAnalysisResult


def _assemble_core_analysis_result_from_state(
    state: CorePipelineState,
    prompt_metadata: PromptPackMetadata,
) -> CoreAnalysisResult:
    return orchestrator_output_assembly.assemble_core_analysis_result(
        state=state,
        prompt_metadata=prompt_metadata,
    )
