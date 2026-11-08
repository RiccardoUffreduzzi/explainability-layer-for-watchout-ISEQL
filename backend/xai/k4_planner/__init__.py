# K4, the explanation planner: from the source of truth of K2 to the plan read by K5, K6 and K7.
#
# The core of K4 imports only xai.contract, the standard library and pydantic: it never sees
# WatchOut, K1 or K2, and reads the source of truth only through SourceOfTruthView.
