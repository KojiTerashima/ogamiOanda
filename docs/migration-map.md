# Migration map

`src/ogami_oanda` is the source of truth for the production live call graph.
Root modules keep historical import names, but the normal USD/JPY, EUR/USD, and
AUD/USD launchers all enter the same `src` composition.

## State definitions

- `SOURCE`: production behavior is implemented in `src/ogami_oanda`.
- `FACADE`: the root public API delegates to `SOURCE` and preserves its legacy
  arguments, return values, or view shape.
- `RETAINED_LEGACY`: an old implementation remains for characterization or an
  excluded diagnostic/experiment, but is not reachable from the production
  live call graph.
- `PENDING`: production live behavior still depends on the old implementation.

## Production live surfaces

| Legacy surface | Source of truth | State | Evidence / removal gate |
| --- | --- | --- | --- |
| `fLineAnalysis.MainAnalysis` | `application.services.MarketAnalysisService`, `strategy.line.LineCandidateBuilder` | FACADE | Three-pair line/candidate/plan/payload contracts and root-facade contracts must remain green. |
| `fLineAnalysis.LineOrderCoordinator` | `strategy.line.LineCandidateCoordinator`, `LineCandidateBuilder`, `MarketAnalysisService`, `OrderPlanner` | FACADE | Public candidate helpers keep their historical signatures; order creation returns legacy views of immutable source plans and never constructs `classOrderCreate.Order`. |
| `fAnalysis_order_Main.wrap_all_analysis` | `fLineAnalysis.MainAnalysis` facade | FACADE | Remove only after all root analysis callers consume `MarketAnalysisResult` or `OrderIntent`. |
| `classPositionControl.position_control` | `PositionPortfolioService`, `PositionService` | FACADE | Default construction uses one shared `OandaClient`; public update/query/catch-up/reset methods re-project immutable slots into the legacy 15-slot view. |
| `classPosition.managed_position_view` | `domain.positions.ManagedPosition` | FACADE | Retained while root callers inspect `position_classes`, `positions_information`, and closed-result views. |
| `classPosition.order_information` reporting class variables | `ClosureReportingService`, `PortfolioAnalytics` | FACADE | CSV records, cumulative values, latest/pivot summaries, and the closed compatibility view are projected from the source-owned close event. |
| `main_exe.py` | `entrypoints.live.build_live_application` | FACADE | Uses the historical secondary account and opts in to startup cancellation; dry-run suppresses that mutation. |
| `main_exe_euro.py` | same live composition with `pair="EUR_USD"` | FACADE | Remove after launcher users move to `ogami-oanda-live --pair EUR_USD`. |
| `main_exe_aud.py` | same live composition with `pair="AUD_USD"` | FACADE | Remove after launcher users move to `ogami-oanda-live --pair AUD_USD`. |
| OANDA pricing/candles/orders/trades | `adapters.oanda` | SOURCE | OANDA imports are architecture-gated to this package; one account client is shared by market, execution, and query adapters. |
| Discord notifications | `adapters.notifications.DiscordNotifier` | SOURCE | `requests` is architecture-gated to this adapter. |
| Trade-history CSV | `adapters.repositories.CsvTradeHistoryRepository` | SOURCE | Application code depends only on `TradeHistoryRepository`. |
| one-second loop and JST wall clock | `infrastructure.runtime.PollingLoop`, `SystemClock` | SOURCE | `time.sleep`, `time.monotonic`, and `datetime.now` are architecture-gated to runtime infrastructure. |
| YAML and root-token compatibility settings | `infrastructure.config` | SOURCE | Business limits are exposed as `application.settings.TradingSettings`; secrets stay at the composition boundary. |

There are no `PENDING` symbols on the production live call graph.

## Retained comparison and excluded surfaces

| Root surface | State | Why it remains | Removal gate |
| --- | --- | --- | --- |
| `fLineAnalysis._LegacyMainAnalysis`, `_LegacyLineOrderCoordinator`, and historical line helpers | RETAINED_LEGACY | Independent behavior oracle for ordered line/candidate comparisons. | Remove after captured fixtures and at least one released live version no longer require root parity. |
| `classPosition.order_information` direct lifecycle methods | RETAINED_LEGACY | Characterization and excluded inspection/backtest scripts still exercise the old mutable object. Normal `position_control` construction never creates it; its reporting projection is a facade as listed above. | Migrate direct diagnostic callers to `ManagedPosition` plus reporting/query views. |
| `classOanda.Oanda` | RETAINED_LEGACY | `classInspection.py`, `test_loop.py`, and manual diagnostic scripts are outside this migration's live scope. The new live composition never imports it. | Port or retire those excluded callers, then replace the root name with an adapter-backed facade. |
| `send_notice.line_send` | RETAINED_LEGACY | Preserves historical routing and duplicate suppression for root scripts. | Root scripts must accept `Notifier` before removal. |
| `position_control_for_test`, `archive/`, `ForTestOandaClass.py`, root `test_*.py` | RETAINED_LEGACY | Explicitly excluded experiments or diagnostics. | Promote only with an offline contract and no production dependency on test code. |

The retained rows are not hidden production dependencies: the architecture
gate forbids every `src` module from importing a root module, and entrypoint
contracts prove that the normal launchers use the `src` composition.
