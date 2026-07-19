# Migration map

The `src/ogami_oanda` package is the production source of truth. Root modules
remain only as public compatibility facades; they must not be imported by src.

| Legacy surface | src source of truth | State | Facade reason / removal gate |
| --- | --- | --- | --- |
| `fLineAnalysis.MainAnalysis` / `fAnalysis_order_Main.wrap_all_analysis` | `application.services.MarketAnalysisService`, `strategy.line.LineCandidateBuilder` | FACADE | Preserve legacy dict/result callers until those callers use `OrderIntent`. |
| `classPosition.order_information` reporting and lifecycle state | `domain.positions.ManagedPosition`, `application.services.ClosureReportingService` | FACADE | Slot-shaped reporting view remains for root callers. |
| `classPositionControl.position_control` | `application.services.PositionPortfolioService`, `PositionService` | FACADE | Injected portfolio mode projects immutable slots back to `position_classes`. |
| `main_exe.py` | `entrypoints.live.LiveApplication` | FACADE | Keeps historical startup pending-order cancellation only in the legacy launcher. |
| `main_exe_euro.py`, `main_exe_aud.py` | `entrypoints.live.build_live_application` | FACADE | Pair selection is passed as an argument; no global-pair mutation remains. |
| OANDA / Discord / CSV | `adapters.oanda`, `adapters.notifications`, `adapters.repositories` | SOURCE | One OANDA client is shared by the live composition. |

No major live symbol is `PENDING`. A facade can be removed only after its root
callers are migrated, its focused parity tests remain green, and a release has
run the offline acceptance matrix.
