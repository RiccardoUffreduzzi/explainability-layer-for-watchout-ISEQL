from api.analysis_controller import (
    AnalysisStartController,
    AnalysisLogsController,
    AnalysisStatusController,
    AnalysisListController,
    AnalysisDetectController,
    AnalysisVideoController,
    AnalysisThumbnailController,
    AnalysisStopController,
    AnalysisDeleteController,
    VLMModelsController,
)
from api.database_controller import (
    DatabaseUploadController,
    DatabaseDownloadController,
    DatabaseResetController,
)
from api.events_controller import EventsDetectController
from api.schema_controller import (
    SchemaController,
    EventTypesController,
)
from api.event_registry_controller import (
    EventRegistryController,
    EventRegistryItemController,
)
from api.iseql_compile_controller import IseqlCompileController
from api.iseql_preview_controller import IseqlPreviewController
from api.iseql_model_compile_controller import IseqlModelCompileController
from api.iseql_vocabulary_controller import IseqlVocabularyController
from api.config_controller import ConfigController
from api.relations_controller import RelationsController
from api.object_memory_controller import (
    ObjectMemoryStatsController,
    ObjectMemoryObjectsController,
)
from service.impl.analysis_service_impl import AnalysisServiceImpl

_analysis_service = AnalysisServiceImpl()

ROUTES = {
    '/analysis/start': AnalysisStartController(_analysis_service),
    '/analysis/list': AnalysisListController(_analysis_service),
    '/analysis/{analysis_id}/logs': AnalysisLogsController(_analysis_service),
    '/analysis/{analysis_id}/status': AnalysisStatusController(_analysis_service),
    '/analysis/{analysis_id}/detect': AnalysisDetectController(_analysis_service),
    '/analysis/{analysis_id}/video': AnalysisVideoController(_analysis_service),
    '/analysis/{analysis_id}/thumbnail': AnalysisThumbnailController(_analysis_service),
    '/analysis/{analysis_id}/stop': AnalysisStopController(_analysis_service),
    '/analysis/{analysis_id}/delete': AnalysisDeleteController(_analysis_service),
    '/vlm/models': VLMModelsController(),
    '/db/upload': DatabaseUploadController(),
    '/db/download': DatabaseDownloadController(),
    '/db/reset': DatabaseResetController(_analysis_service),
    '/events/detect': EventsDetectController(),
    '/schema': SchemaController(),
    '/events/types': EventTypesController(),
    '/events': EventRegistryController(),
    '/events/{event_id}': EventRegistryItemController(),
    '/iseql/compile': IseqlCompileController(),
    '/iseql/preview': IseqlPreviewController(),
    '/iseql/model/compile': IseqlModelCompileController(),
    '/iseql/vocabulary': IseqlVocabularyController(),
    '/analysis/{analysis_id}/memory/stats': ObjectMemoryStatsController(),
    '/analysis/{analysis_id}/memory/objects': ObjectMemoryObjectsController(),
    '/config': ConfigController(),
    '/config/{key}': ConfigController(),
    '/relations': RelationsController(),
}
