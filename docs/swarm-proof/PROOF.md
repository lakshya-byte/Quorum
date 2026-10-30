# Verifier proof matrix (real runs)

### inventory-lib / feature-bulk-discounts

| criterion | kind | hard | original | reference | bad:tests-deleted |
|---|---|---|---|---|---|
| build | build | yes | PASS | PASS | PASS |
| no_regression | no_regression | yes | PASS | PASS | FAIL |
| policy | policy | yes | FAIL | PASS | FAIL |
| security | security | yes | PASS | PASS | PASS |
| secrets | secrets | yes | PASS | PASS | PASS |
| acceptance | acceptance_tests | yes | FAIL | PASS | PASS |
| lint | lint_typecheck | yes | PASS | PASS | PASS |

### inventory-lib / refactor-split-stock

| criterion | kind | hard | original | reference | bad:api-broken | bad:tests-deleted |
|---|---|---|---|---|---|---|
| build | build | yes | PASS | PASS | PASS | PASS |
| no_regression | no_regression | yes | PASS | PASS | PASS | FAIL |
| policy | policy | yes | FAIL | PASS | PASS | FAIL |
| security | security | yes | PASS | PASS | PASS | PASS |
| secrets | secrets | yes | PASS | PASS | PASS | PASS |
| characterization | characterization | yes | PASS | PASS | PASS | PASS |
| api_surface | api_surface | yes | PASS | PASS | FAIL | PASS |
| lint | lint_typecheck | yes | PASS | PASS | PASS | PASS |
| size | complexity_metric | yes | FAIL | PASS | PASS | PASS |
| readability | advisory_rubric | advisory | SKIP | SKIP | SKIP | SKIP |

### react-notes / ui-improve

| criterion | kind | hard | original | reference | bad:tests-deleted-overflow-remains |
|---|---|---|---|---|---|
| build | build | yes | PASS | PASS | PASS |
| no_regression | no_regression | yes | PASS | PASS | FAIL |
| policy | policy | yes | FAIL | PASS | FAIL |
| security | security | yes | PASS | PASS | PASS |
| secrets | secrets | yes | PASS | PASS | PASS |
| ui_console | ui_build_console | yes | PASS | PASS | PASS |
| ui_overflow | ui_overflow | yes | FAIL | PASS | FAIL |
| ui_axe | ui_axe | yes | FAIL | PASS | PASS |
| ui_smoke | ui_smoke | yes | PASS | PASS | PASS |
| vision | advisory_vision | advisory | SKIP | SKIP | SKIP |

